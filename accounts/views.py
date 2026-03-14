from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.tokens import default_token_generator
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode
from django.views import View
from django.views.generic import FormView, TemplateView

from .forms import LoginForm, RegisterForm, ResendActivationForm
from .models import User
from .utils import send_activation_email


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
        try:
            send_activation_email(user)
            messages.success(
                self.request,
                "Konto zostało utworzone. Sprawdź skrzynkę e-mail i aktywuj konto.",
            )
        except Exception:
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
        login(self.request, form.get_user())
        messages.success(self.request, "Zalogowano pomyślnie.")
        return super().form_valid(form)


class ActivateAccountView(View):
    template_name = "accounts/activation_result.html"

    def get(self, request: HttpRequest, uidb64: str, token: str) -> HttpResponse:
        try:
            uid = force_str(urlsafe_base64_decode(uidb64))
            user = User.objects.get(pk=uid)
        except (TypeError, ValueError, OverflowError, User.DoesNotExist):
            raise Http404("Nie znaleziono użytkownika.")

        context = {"success": False, "already_active": False}
        if user.is_active and user.is_email_verified:
            context["already_active"] = True
            return render(request, self.template_name, context)

        if default_token_generator.check_token(user, token):
            user.is_active = True
            user.is_email_verified = True
            user.save(update_fields=["is_active", "is_email_verified", "updated_at"])
            context["success"] = True

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
            except Exception:
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
        logout(request)
        messages.info(request, "Wylogowano pomyślnie.")
        return redirect("home")

