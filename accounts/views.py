import logging

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


class RegisterView(FormView):
    template_name = "accounts/register.html"
    form_class = RegisterForm
    success_url = reverse_lazy("accounts:activation_sent")

    def dispatch(self, request: HttpRequest, *args, **kwargs) -> HttpResponse:
        if request.user.is_authenticated:
            return redirect("home")
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        user = form.save()
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


class LoginView(FormView):
    template_name = "accounts/login.html"
    form_class = LoginForm
    success_url = reverse_lazy("home")

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
                return redirect("accounts:resend_activation")
        return super().form_valid(form)


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
        # Imported locally to keep accounts → movies coupling out of the
        # module import graph (movies already imports accounts indirectly
        # via the user FK, and a top-level import here risks a cycle).
        from collections import Counter
        from decimal import Decimal

        from movies.models import Movie, Rating, UserMovieStatus

        ctx = super().get_context_data(**kwargs)
        user = self.request.user

        watched_rows = (
            UserMovieStatus.objects.filter(user=user, status=UserMovieStatus.WATCHED)
            .select_related("movie")
            .order_by("-updated_at")
        )
        watchlist_rows = (
            UserMovieStatus.objects.filter(user=user, status=UserMovieStatus.WATCHLIST)
            .select_related("movie")
            .order_by("-updated_at")
        )
        rated_rows = (
            Rating.objects.filter(user=user)
            .select_related("movie")
            .order_by("-updated_at")
        )

        watched_movies = [row.movie for row in watched_rows]
        watchlist_movies = [row.movie for row in watchlist_rows]
        rated_movies = [{"movie": row.movie, "score": row.score} for row in rated_rows]

        # "Library" = strictly watched movies, with the user's rating attached
        # when one exists. A rating without an explicit watched mark stays out
        # of this list (the watchlist tab covers planned-to-watch separately).
        # updated_ts uses the latest of (watched, rated) so the grid still
        # surfaces recent activity even when the rating arrived after the
        # watched mark.
        ratings_by_movie: dict[int, tuple[Decimal, float]] = {
            row.movie.pk: (row.score, row.updated_at.timestamp()) for row in rated_rows
        }
        library_entries = []
        for row in watched_rows:
            score_ts = ratings_by_movie.get(row.movie.pk)
            score = score_ts[0] if score_ts else None
            updated_ts = row.updated_at.timestamp()
            if score_ts:
                updated_ts = max(updated_ts, score_ts[1])
            library_entries.append(
                {
                    "movie": row.movie,
                    "score": score,
                    "updated_ts": updated_ts,
                    "score_int": int(score) if score is not None else 0,
                    "has_rating": score is not None,
                }
            )
        library_entries.sort(key=lambda e: e["updated_ts"], reverse=True)
        library_count = len(library_entries)
        library_rated_count = sum(1 for e in library_entries if e["has_rating"])
        library_unrated_count = library_count - library_rated_count

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
            initials = user.email.split("@", 1)[0][:2].upper()

        avg_rating: Decimal | None = None
        if rated_rows.exists():
            total = sum((row.score for row in rated_rows), Decimal("0"))
            avg_rating = (total / len(rated_movies)).quantize(Decimal("0.01"))

        top_genres: list[str] = []
        top_decade: str | None = None
        if watched_movies or rated_movies:
            movie_ids = {m.pk for m in watched_movies} | {
                row["movie"].pk for row in rated_movies
            }
            movies_qs = Movie.objects.filter(pk__in=movie_ids).prefetch_related(
                "genres"
            )
            genre_counter: Counter[str] = Counter()
            decade_counter: Counter[str] = Counter()
            for m in movies_qs:
                for g in m.genres.all():
                    genre_counter[g.name] += 1
                if m.release_date is not None:
                    decade = (m.release_date.year // 10) * 10
                    decade_counter[f"{decade}s"] += 1
            top_genres = [name for name, _ in genre_counter.most_common(3)]
            if decade_counter:
                top_decade = decade_counter.most_common(1)[0][0]

        ctx.update(
            {
                "watched_movies": watched_movies,
                "watchlist_movies": watchlist_movies,
                "rated_movies": rated_movies,
                "watched_count": len(watched_movies),
                "watchlist_count": len(watchlist_movies),
                "rated_count": len(rated_movies),
                "library_entries": library_entries,
                "library_count": library_count,
                "library_rated_count": library_rated_count,
                "library_unrated_count": library_unrated_count,
                "active_tab": active_tab_legacy,
                "active_library_tab": active_library_tab,
                "avg_rating": avg_rating,
                "top_genres": top_genres,
                "top_decade": top_decade,
                "profile_initials": initials,
                "profile_display_name": display_name or user.email,
                "profile_email": user.email,
                "profile_joined": user.date_joined,
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
