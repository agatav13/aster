import logging

from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.tokens import default_token_generator
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode
from django.views import View
from django.views.generic import FormView, TemplateView, UpdateView

from .forms import FavoriteGenresForm, LoginForm, RegisterForm, ResendActivationForm
from .models import User
from .utils import send_activation_email

logger = logging.getLogger(__name__)


class RegisterView(FormView):
    template_name = "accounts/register.html"
    form_class = RegisterForm
    success_url = reverse_lazy("accounts:activation_sent")

    def dispatch(self, request: HttpRequest, *args, **kwargs) -> HttpResponse:
        if request.user.is_authenticated:
            return redirect("dashboard")
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        user = form.save()
        logger.info("Registered new user id=%s email=%s", user.pk, user.email)
        try:
            send_activation_email(user)
            logger.info("Sent activation email to user id=%s", user.pk)
            messages.success(
                self.request,
                "Konto zostało utworzone. Sprawdź skrzynkę e-mail i aktywuj konto.",
            )
        except Exception:
            logger.exception(
                "Activation email failed for user id=%s email=%s", user.pk, user.email
            )
            messages.warning(
                self.request,
                "Konto zostało utworzone, ale wysyłka e-maila się nie powiodła. "
                "Sprawdź konfigurację SMTP i użyj ponownej wysyłki linku.",
            )
        return super().form_valid(form)


class ActivationSentView(TemplateView):
    template_name = "accounts/activation_sent.html"


class LoginView(FormView):
    template_name = "accounts/login.html"
    form_class = LoginForm
    success_url = reverse_lazy("dashboard")

    def dispatch(self, request: HttpRequest, *args, **kwargs) -> HttpResponse:
        if request.user.is_authenticated:
            return redirect("dashboard")
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["request"] = self.request
        return kwargs

    def form_valid(self, form):
        user = form.get_user()
        login(self.request, user)
        logger.info("User logged in id=%s email=%s", user.pk, user.email)
        messages.success(self.request, "Zalogowano pomyślnie.")
        return super().form_valid(form)


class ActivateAccountView(View):
    template_name = "accounts/activation_result.html"

    def get(self, request: HttpRequest, uidb64: str, token: str) -> HttpResponse:
        try:
            uid = force_str(urlsafe_base64_decode(uidb64))
            user = User.objects.get(pk=uid)
        except (TypeError, ValueError, OverflowError, User.DoesNotExist):
            logger.warning("Activation failed: invalid uidb64=%r", uidb64)
            raise Http404("Nie znaleziono użytkownika.")

        context = {"success": False, "already_active": False}
        if user.is_active and user.is_email_verified:
            logger.debug("Activation no-op: user id=%s already active", user.pk)
            context["already_active"] = True
            return render(request, self.template_name, context)

        if default_token_generator.check_token(user, token):
            user.is_active = True
            user.is_email_verified = True
            user.save(update_fields=["is_active", "is_email_verified", "updated_at"])
            logger.info("Activated user id=%s email=%s", user.pk, user.email)
            context["success"] = True
        else:
            logger.warning(
                "Activation failed: invalid/expired token for user id=%s", user.pk
            )

        return render(request, self.template_name, context)


class ResendActivationView(FormView):
    template_name = "accounts/resend_activation.html"
    form_class = ResendActivationForm
    success_url = reverse_lazy("accounts:activation_sent")

    def form_valid(self, form):
        email = form.cleaned_data["email"]
        user = User.objects.filter(email__iexact=email).first()

        if user and not user.is_active:
            try:
                send_activation_email(user)
                logger.info("Resent activation email to user id=%s", user.pk)
            except Exception:
                logger.exception(
                    "Resend activation email failed for user id=%s", user.pk
                )
                messages.error(
                    self.request,
                    "Nie udało się ponownie wysłać wiadomości. Sprawdź konfigurację SMTP.",
                )
                return redirect("accounts:resend_activation")
            messages.success(self.request, "Wysłaliśmy nowy link aktywacyjny.")
        elif user and user.is_active:
            messages.info(self.request, "To konto jest już aktywne. Możesz się zalogować.")
        else:
            messages.info(
                self.request,
                "Jeśli konto istnieje, wiadomość aktywacyjna została wysłana ponownie.",
            )
        return super().form_valid(form)


class LogoutView(View):
    http_method_names = ["post"]

    def post(self, request: HttpRequest) -> HttpResponse:
        user_id = request.user.pk if request.user.is_authenticated else None
        logout(request)
        logger.info("User logged out id=%s", user_id)
        messages.info(request, "Wylogowano pomyślnie.")
        return redirect("home")


class EditFavoriteGenresView(LoginRequiredMixin, UpdateView):
    template_name = "accounts/edit_favorite_genres.html"
    form_class = FavoriteGenresForm
    success_url = reverse_lazy("dashboard")

    def get_object(self, queryset=None) -> User:
        return self.request.user

    def form_valid(self, form):
        logger.info(
            "User id=%s updated favorite_genres to %s",
            self.request.user.pk,
            list(form.cleaned_data["favorite_genres"].values_list("pk", flat=True)),
        )
        messages.success(self.request, "Ulubione gatunki zostały zaktualizowane.")
        return super().form_valid(form)

