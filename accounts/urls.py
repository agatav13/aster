from django.contrib.auth import views as auth_views
from django.urls import path, reverse_lazy

from .forms import AppPasswordResetForm
from .views import (
    ActivateAccountView,
    ActivationSentView,
    EditDisplayNameView,
    EditFavoriteGenresView,
    LoginView,
    LogoutView,
    ProfileView,
    RegisterView,
    ResendActivationView,
)

app_name = "accounts"

urlpatterns = [
    path("register/", RegisterView.as_view(), name="register"),
    path("login/", LoginView.as_view(), name="login"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("profile/", ProfileView.as_view(), name="profile"),
    path("display-name/", EditDisplayNameView.as_view(), name="edit_display_name"),
    path("genres/", EditFavoriteGenresView.as_view(), name="edit_favorite_genres"),
    path("activate/<uidb64>/<token>/", ActivateAccountView.as_view(), name="activate"),
    path("activation-sent/", ActivationSentView.as_view(), name="activation_sent"),
    path("resend-activation/", ResendActivationView.as_view(), name="resend_activation"),
    path(
        "password-reset/",
        auth_views.PasswordResetView.as_view(
            form_class=AppPasswordResetForm,
            template_name="accounts/password_reset_form.html",
            email_template_name="accounts/emails/password_reset_email.txt",
            html_email_template_name="accounts/emails/password_reset_email.html",
            subject_template_name="accounts/emails/password_reset_subject.txt",
            success_url=reverse_lazy("accounts:password_reset_done"),
        ),
        name="password_reset",
    ),
    path(
        "password-reset/done/",
        auth_views.PasswordResetDoneView.as_view(
            template_name="accounts/password_reset_done.html"
        ),
        name="password_reset_done",
    ),
    path(
        "reset/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(
            template_name="accounts/password_reset_confirm.html",
            success_url=reverse_lazy("accounts:password_reset_complete"),
        ),
        name="password_reset_confirm",
    ),
    path(
        "reset/done/",
        auth_views.PasswordResetCompleteView.as_view(
            template_name="accounts/password_reset_complete.html"
        ),
        name="password_reset_complete",
    ),
]

