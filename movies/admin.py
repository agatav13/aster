from django.contrib import admin
from django.db.models import Count, QuerySet
from django.http import HttpRequest
from django.utils import timezone

from .models import Comment, CommentReport, Genre, Movie, Rating, UserMovieStatus


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


class CommentReportInline(admin.TabularInline):
    model = CommentReport
    extra = 0
    fields = ("reporter", "reason", "created_at")
    readonly_fields = ("reporter", "reason", "created_at")
    can_delete = False

    def has_add_permission(self, request: HttpRequest, obj=None) -> bool:
        return False


@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = ("user", "movie", "status", "report_count", "created_at")
    list_filter = ("status",)
    search_fields = ("user__email", "movie__title", "content")
    autocomplete_fields = ("user", "movie")
    readonly_fields = ("created_at", "updated_at", "moderated_at")
    inlines = (CommentReportInline,)
    actions = ("hide_comments", "restore_comments")

    def get_queryset(self, request: HttpRequest) -> QuerySet[Comment]:
        return super().get_queryset(request).annotate(_report_count=Count("reports"))

    @admin.display(description="Zgłoszenia", ordering="_report_count")
    def report_count(self, obj: Comment) -> int:
        return obj._report_count

    @admin.action(description="Ukryj zaznaczone komentarze")
    def hide_comments(self, request: HttpRequest, queryset: QuerySet[Comment]) -> None:
        updated = queryset.update(status=Comment.HIDDEN, moderated_at=timezone.now())
        self.message_user(request, f"Ukryto {updated} komentarzy.")

    @admin.action(description="Przywróć zaznaczone komentarze (usuwa zgłoszenia)")
    def restore_comments(
        self, request: HttpRequest, queryset: QuerySet[Comment]
    ) -> None:
        CommentReport.objects.filter(comment__in=queryset).delete()
        updated = queryset.update(status=Comment.VISIBLE, moderated_at=timezone.now())
        self.message_user(request, f"Przywrócono {updated} komentarzy.")


@admin.register(CommentReport)
class CommentReportAdmin(admin.ModelAdmin):
    list_display = ("comment", "reporter", "reason", "created_at")
    list_filter = ("reason", "created_at")
    search_fields = ("reporter__email", "comment__content")
    autocomplete_fields = ("comment", "reporter")
    readonly_fields = ("created_at",)
