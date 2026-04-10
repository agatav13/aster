from decimal import Decimal

from django.db import models


class Genre(models.Model):
    name: str = models.CharField("Name", max_length=50, unique=True)
    tmdb_id: int | None = models.IntegerField("TMDB id", unique=True, null=True, blank=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "genre"
        verbose_name_plural = "genres"
        # Reuses the original table created in accounts/0002 to avoid a DB rename.
        # The model lives in the movies app at the Django level; the underlying
        # table name is a one-line cosmetic concern only.
        db_table = "accounts_genre"

    def __str__(self) -> str:
        return self.name


class Movie(models.Model):
    tmdb_id: int = models.IntegerField("TMDB id", unique=True)
    title: str = models.CharField("Title", max_length=255)
    original_title: str = models.CharField("Original title", max_length=255, blank=True)
    overview: str = models.TextField("Overview", blank=True)
    release_date: "models.DateField | None" = models.DateField(
        "Release date", null=True, blank=True
    )
    runtime_minutes: int | None = models.IntegerField(
        "Runtime (minutes)", null=True, blank=True
    )
    poster_url: str = models.URLField("Poster URL", max_length=500, blank=True)
    backdrop_url: str = models.URLField("Backdrop URL", max_length=500, blank=True)
    original_language: str = models.CharField(
        "Original language", max_length=10, blank=True
    )
    average_rating: Decimal = models.DecimalField(
        "Average rating", max_digits=3, decimal_places=2, default=Decimal("0.00")
    )
    ratings_count: int = models.IntegerField("Ratings count", default=0)
    popularity: Decimal | None = models.DecimalField(
        "Popularity", max_digits=10, decimal_places=2, null=True, blank=True
    )
    genres = models.ManyToManyField(Genre, related_name="movies", blank=True)
    tmdb_synced_at = models.DateTimeField("Last TMDB sync", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-popularity", "title"]
        indexes = [
            models.Index(fields=["title"]),
            models.Index(fields=["-popularity"]),
        ]

    def __str__(self) -> str:
        return self.title
