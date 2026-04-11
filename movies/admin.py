from django.contrib import admin

from .models import Comment, Genre, Movie, Rating, UserMovieStatus


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


@admin.register(UserMovieStatus)
class UserMovieStatusAdmin(admin.ModelAdmin):
    list_display = ("user", "movie", "status", "updated_at")
    list_filter = ("status",)
    search_fields = ("user__email", "movie__title")
    autocomplete_fields = ("user", "movie")
    readonly_fields = ("created_at", "updated_at")


@admin.register(Rating)
class RatingAdmin(admin.ModelAdmin):
    list_display = ("user", "movie", "score", "updated_at")
    list_filter = ("score",)
    search_fields = ("user__email", "movie__title")
    autocomplete_fields = ("user", "movie")
    readonly_fields = ("created_at", "updated_at")


@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = ("user", "movie", "status", "created_at")
    list_filter = ("status",)
    search_fields = ("user__email", "movie__title", "content")
    autocomplete_fields = ("user", "movie")
    readonly_fields = ("created_at", "updated_at")
