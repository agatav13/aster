from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from .models import User


def send_activation_email(user: User) -> None:
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    activation_path = reverse(
        "accounts:activate", kwargs={"uidb64": uid, "token": token}
    )
    activation_url = f"{settings.APP_BASE_URL}{activation_path}"
    context = {
        "user": user,
        "activation_url": activation_url,
    }
    subject = "Aktywuj konto w aplikacji filmowej"
    text_body = render_to_string("accounts/emails/activation_email.txt", context)
    html_body = render_to_string("accounts/emails/activation_email.html", context)

    email = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        to=[user.email],
    )
    email.attach_alternative(html_body, "text/html")
    email.send()
