from django import forms
from django.contrib.auth import authenticate
from django.contrib.auth.forms import PasswordResetForm, UserCreationForm

from .models import Genre, User


class RegisterForm(UserCreationForm):
    email = forms.EmailField(label="Adres e-mail")
    display_name = forms.CharField(
        label="Nick lub imię i nazwisko (opcjonalnie)",
        max_length=120,
        required=False,
    )
    favorite_genres = forms.ModelMultipleChoiceField(
        label="Ulubione gatunki",
        queryset=Genre.objects.none(),
        required=True,
        widget=forms.CheckboxSelectMultiple,
        help_text="Wybierz przynajmniej jeden gatunek.",
        error_messages={"required": "Wybierz przynajmniej jeden ulubiony gatunek."},
    )

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("email", "display_name", "favorite_genres")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["favorite_genres"].queryset = Genre.objects.order_by("name")

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        existing_user = User.objects.filter(email__iexact=email).first()
        if existing_user and existing_user.is_active:
            raise forms.ValidationError("Konto z tym adresem e-mail już istnieje.")
        if existing_user and not existing_user.is_active:
            raise forms.ValidationError(
                "Konto istnieje, ale nie jest aktywne. Użyj ponownej wysyłki linku aktywacyjnego."
            )
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data["email"].strip().lower()
        user.is_active = False
        user.is_email_verified = False
        if commit:
            user.save()
            user.favorite_genres.set(self.cleaned_data["favorite_genres"])
        return user


class LoginForm(forms.Form):
    email = forms.EmailField(label="Adres e-mail")
    password = forms.CharField(label="Hasło", widget=forms.PasswordInput)

    error_messages = {
        "invalid_login": "Nieprawidłowy adres e-mail lub hasło.",
        "inactive": "Konto nie jest jeszcze aktywne. Sprawdź e-mail aktywacyjny.",
    }

    def __init__(self, *args, request=None, **kwargs):
        self.request = request
        self.user_cache = None
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned_data = super().clean()
        email = cleaned_data.get("email", "").strip().lower()
        password = cleaned_data.get("password")

        if not email or not password:
            return cleaned_data

        user = User.objects.filter(email__iexact=email).first()
        if user and user.check_password(password) and not user.is_active:
            raise forms.ValidationError(self.error_messages["inactive"])

        self.user_cache = authenticate(self.request, email=email, password=password)
        if self.user_cache is None:
            raise forms.ValidationError(self.error_messages["invalid_login"])

        return cleaned_data

    def get_user(self):
        return self.user_cache


class ResendActivationForm(forms.Form):
    email = forms.EmailField(label="Adres e-mail")

    def clean_email(self):
        return self.cleaned_data["email"].strip().lower()


class AppPasswordResetForm(PasswordResetForm):
    email = forms.EmailField(label="Adres e-mail")
