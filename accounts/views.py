import logging
from itertools import groupby

from django.contrib.auth import login, logout
from django.contrib.auth import views as auth_views
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.tokens import default_token_generator
from django.db import IntegrityError
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode
from django.views import View
from django.views.generic import FormView, TemplateView, UpdateView
from django_ratelimit.decorators import ratelimit

from movies.profile import build_profile_stats
from movies.services import journal_entries

from .forms import (
    DisplayNameForm,
    FavoriteGenresForm,
    LoginForm,
    RegisterForm,
    ResendActivationForm,
)
from .models import User
from .utils import send_activation_email

logger = logging.getLogger(__name__)


class _RateLimitedFormView(FormView):
    """FormView that turns a tripped django-ratelimit (block=False) into a
    non-field form error instead of an abrupt 403, keeping the normal page."""

    ratelimit_message = "Za dużo prób. Spróbuj ponownie za chwilę."

    def post(self, request: HttpRequest, *args, **kwargs) -> HttpResponse:
        if getattr(request, "limited", False):
            form = self.get_form()
            form.add_error(None, self.ratelimit_message)
            return self.form_invalid(form)
        return super().post(request, *args, **kwargs)


@method_decorator(
    ratelimit(key="ip", rate="5/h", method="POST", block=False), name="dispatch"
)
class RegisterView(_RateLimitedFormView):
    template_name = "accounts/register.html"
    form_class = RegisterForm
    success_url = reverse_lazy("accounts:activation_sent")
    ratelimit_message = "Za dużo prób rejestracji. Spróbuj ponownie później."

    def dispatch(self, request: HttpRequest, *args, **kwargs) -> HttpResponse:
        if request.user.is_authenticated:
            return redirect("home")
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        try:
            user = form.save()
        except IntegrityError:
            # Two concurrent registrations for the same email both pass
            # clean_email's existence check; the loser lands here instead
            # of 500ing on the unique constraint.
            form.add_error("email", "Konto z tym adresem e-mail już istnieje.")
            return self.form_invalid(form)
        logger.info("Registered new user id=%s email=%s", user.pk, user.email)
        try:
            send_activation_email(user)
            logger.info("Sent activation email to user id=%s", user.pk)
        except Exception:
            logger.exception(
                "Activation email failed for user id=%s email=%s", user.pk, user.email
            )
        return super().form_valid(form)


class ActivationSentView(TemplateView):
    template_name = "accounts/activation_sent.html"


@method_decorator(
    ratelimit(key="ip", rate="10/m", method="POST", block=False), name="dispatch"
)
class LoginView(_RateLimitedFormView):
    template_name = "accounts/login.html"
    form_class = LoginForm
    success_url = reverse_lazy("home")
    ratelimit_message = "Za dużo prób logowania. Spróbuj ponownie za chwilę."

    def dispatch(self, request: HttpRequest, *args, **kwargs) -> HttpResponse:
        if request.user.is_authenticated:
            return redirect("home")
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["request"] = self.request
        return kwargs

    def form_valid(self, form):
        user = form.get_user()
        login(self.request, user)
        logger.info("User logged in id=%s email=%s", user.pk, user.email)
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


@method_decorator(
    ratelimit(key="ip", rate="5/h", method="POST", block=False), name="dispatch"
)
class ResendActivationView(_RateLimitedFormView):
    template_name = "accounts/resend_activation.html"
    form_class = ResendActivationForm
    success_url = reverse_lazy("accounts:activation_sent")
    ratelimit_message = "Za dużo prób. Spróbuj ponownie później."

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
                return redirect("accounts:resend_activation")
        return super().form_valid(form)


@method_decorator(
    ratelimit(key="ip", rate="5/h", method="POST", block=False), name="dispatch"
)
class AppPasswordResetView(auth_views.PasswordResetView):
    """Password reset with the same friendly rate-limit handling as the other
    unauthenticated email-sending endpoints — every POST triggers an outbound
    email, so without a limit one IP can email-bomb any registered address."""

    ratelimit_message = "Za dużo prób. Spróbuj ponownie później."

    def post(self, request: HttpRequest, *args, **kwargs) -> HttpResponse:
        if getattr(request, "limited", False):
            form = self.get_form()
            form.add_error(None, self.ratelimit_message)
            return self.form_invalid(form)
        return super().post(request, *args, **kwargs)


class LogoutView(View):
    http_method_names = ["post"]

    def post(self, request: HttpRequest) -> HttpResponse:
        user_id = request.user.pk if request.user.is_authenticated else None
        logout(request)
        logger.info("User logged out id=%s", user_id)
        return redirect("home")


class ProfileView(LoginRequiredMixin, TemplateView):
    template_name = "accounts/profile.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user
        stats = build_profile_stats(user)

        raw_tab = self.request.GET.get("tab")
        # Old two-of-three tab values ("watched", "rated") now both resolve to
        # the merged library view; keep the redirect implicit so saved links
        # stay working.
        tab_aliases = {
            "watched": "library",
            "rated": "library",
            "library": "library",
            "watchlist": "watchlist",
        }
        active_tab_legacy = (
            raw_tab if raw_tab in {"watched", "rated", "watchlist"} else "watched"
        )
        active_library_tab = tab_aliases.get(raw_tab, "library")

        display_name = user.display_name or ""
        name_parts = display_name.split() if display_name else []
        if len(name_parts) >= 2:
            initials = (name_parts[0][:1] + name_parts[1][:1]).upper()
        elif name_parts:
            initials = name_parts[0][:2].upper()
        else:
            initials = "U"

        ctx.update(
            {
                "watched_movies": stats.watched_movies,
                "watchlist_movies": stats.watchlist_movies,
                "rated_movies": stats.rated_movies,
                "watched_count": stats.watched_count,
                "watchlist_count": stats.watchlist_count,
                "rated_count": stats.rated_count,
                "library_entries": stats.library_entries,
                "library_count": stats.library_count,
                "library_rated_count": stats.library_rated_count,
                "library_unrated_count": stats.library_unrated_count,
                "active_tab": active_tab_legacy,
                "active_library_tab": active_library_tab,
                "avg_rating": stats.avg_rating,
                "top_genres": stats.top_genres,
                "top_decade": stats.top_decade,
                "profile_initials": initials,
                "profile_display_name": user.public_name,
                "profile_email": user.email,
                "profile_joined": user.date_joined,
            }
        )
        return ctx


class JournalView(LoginRequiredMixin, TemplateView):
    """Chronological view of the user's private movie diary across all films.

    Aggregates every MovieNote the user has written. Entries are grouped by
    the day they were written (created_at) so the page reads like a journal —
    the private counterpart to the public friends-activity feed.
    """

    template_name = "accounts/journal.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        entries = list(journal_entries(self.request.user))

        # localdate, not .date(): created_at is stored in UTC, so a note
        # written just after midnight in Europe/Warsaw would otherwise be
        # grouped under the previous day.
        groups = [
            {"date": day, "entries": list(items)}
            for day, items in groupby(
                entries, key=lambda note: timezone.localdate(note.created_at)
            )
        ]

        ctx.update(
            {
                "groups": groups,
                "notes_total": len(entries),
                "movies_count": len({note.movie_id for note in entries}),
            }
        )
        return ctx


class SettingsView(LoginRequiredMixin, TemplateView):
    template_name = "accounts/settings.html"


class EditDisplayNameView(LoginRequiredMixin, UpdateView):
    template_name = "accounts/edit_display_name.html"
    form_class = DisplayNameForm
    success_url = reverse_lazy("accounts:settings")

    def get_object(self, queryset=None) -> User:
        return self.request.user

    def form_valid(self, form):
        logger.info(
            "User id=%s updated display_name to %r",
            self.request.user.pk,
            form.cleaned_data["display_name"],
        )
        return super().form_valid(form)


class EditFavoriteGenresView(LoginRequiredMixin, UpdateView):
    template_name = "accounts/edit_favorite_genres.html"
    form_class = FavoriteGenresForm
    success_url = reverse_lazy("accounts:settings")

    def get_object(self, queryset=None) -> User:
        return self.request.user

    def form_valid(self, form):
        logger.info(
            "User id=%s updated favorite_genres to %s",
            self.request.user.pk,
            list(form.cleaned_data["favorite_genres"].values_list("pk", flat=True)),
        )
        return super().form_valid(form)
