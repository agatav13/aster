from django.contrib import admin

from .models import Genre, Movie


@admin.register(Genre)
class GenreAdmin(admin.ModelAdmin):
    list_display = ("name", "tmdb_id")
    search_fields = ("name",)
    ordering = ("name",)


@admin.register(Movie)
class MovieAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "release_date",
        "popularity",
        "average_rating",
        "tmdb_synced_at",
    )
    list_filter = ("genres", "original_language")
    search_fields = ("title", "original_title")
    filter_horizontal = ("genres",)
    readonly_fields = ("created_at", "updated_at", "tmdb_synced_at")
