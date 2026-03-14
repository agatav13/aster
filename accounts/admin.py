from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import Genre, User


@admin.register(Genre)
class GenreAdmin(admin.ModelAdmin):
    list_display = ("name",)
    search_fields = ("name",)


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    model = User
    ordering = ("email",)
    list_display = (
        "email",
        "display_name",
        "is_active",
        "is_email_verified",
        "is_staff",
    )
    search_fields = ("email", "display_name", "favorite_genres__name")
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Dane profilu", {"fields": ("display_name", "favorite_genres")}),
        (
            "Uprawnienia",
            {
                "fields": (
                    "is_active",
                    "is_email_verified",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                )
            },
        ),
        ("Daty", {"fields": ("last_login", "date_joined", "created_at", "updated_at")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": (
                    "email",
                    "display_name",
                    "favorite_genres",
                    "password1",
                    "password2",
                ),
            },
        ),
    )
    readonly_fields = ("created_at", "updated_at", "last_login", "date_joined")
    filter_horizontal = ("favorite_genres", "groups", "user_permissions")
