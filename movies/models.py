from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class Genre(models.Model):
    name: str = models.CharField("Name", max_length=50, unique=True)
    tmdb_id: int | None = models.IntegerField(
        "TMDB id", unique=True, null=True, blank=True
    )

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


class UserMovieStatus(models.Model):
    """Tracks a user's relationship with a movie (watchlist or watched).

    Maps to the `user_movie_statuses` table from docs/database-design.md.
    Replaces separate `watchlist` and `watched_movies` tables by letting a
    single row flip between the two states via `status`.
    """

    WATCHLIST = "watchlist"
    WATCHED = "watched"
    STATUS_CHOICES = [
        (WATCHLIST, "Do obejrzenia"),
        (WATCHED, "Obejrzane"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="movie_statuses",
    )
    movie = models.ForeignKey(
        Movie,
        on_delete=models.CASCADE,
        related_name="user_statuses",
    )
    status: str = models.CharField("Status", max_length=20, choices=STATUS_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "movie"], name="uq_user_movie_status"
            ),
        ]
        indexes = [
            models.Index(fields=["user", "status"]),
        ]
        verbose_name = "user movie status"
        verbose_name_plural = "user movie statuses"

    def __str__(self) -> str:
        return f"{self.user} → {self.movie} ({self.status})"


class Rating(models.Model):
    """User's 0.5–5 star rating for a movie (half-star precision).

    Maps to the `ratings` table from docs/database-design.md. The cached
    `movies.average_rating` / `movies.ratings_count` aggregates are
    refreshed by the service layer whenever a rating is inserted, updated
    or deleted.
    """

    MIN_SCORE = Decimal("0.5")
    MAX_SCORE = Decimal("5.0")
    SCORE_STEP = Decimal("0.5")

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="ratings",
    )
    movie = models.ForeignKey(
        Movie,
        on_delete=models.CASCADE,
        related_name="ratings",
    )
    score: Decimal = models.DecimalField(
        "Ocena",
        max_digits=2,
        decimal_places=1,
        validators=[
            MinValueValidator(Decimal("0.5")),
            MaxValueValidator(Decimal("5.0")),
        ],
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "movie"], name="uq_user_movie_rating"
            ),
            models.CheckConstraint(
                condition=models.Q(score__gte=Decimal("0.5"))
                & models.Q(score__lte=Decimal("5.0")),
                name="ck_rating_score_half_5",
            ),
        ]
        indexes = [
            models.Index(fields=["movie"]),
        ]
        verbose_name = "rating"
        verbose_name_plural = "ratings"

    def __str__(self) -> str:
        return f"{self.user} → {self.movie}: {self.score}/5"


class Person(models.Model):
    """Actor or director fetched from TMDB credits."""

    tmdb_id: int = models.IntegerField("TMDB id", unique=True)
    name: str = models.CharField("Name", max_length=255)
    profile_url: str = models.URLField("Profile image URL", max_length=500, blank=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "person"
        verbose_name_plural = "people"

    def __str__(self) -> str:
        return self.name


class MovieCredit(models.Model):
    """Links a Person to a Movie as either cast or director."""

    CAST = "cast"
    DIRECTOR = "director"
    CREDIT_TYPE_CHOICES = [
        (CAST, "Aktor"),
        (DIRECTOR, "Reżyser"),
    ]

    movie = models.ForeignKey(
        Movie,
        on_delete=models.CASCADE,
        related_name="credits",
    )
    person = models.ForeignKey(
        Person,
        on_delete=models.CASCADE,
        related_name="credits",
    )
    credit_type: str = models.CharField(
        "Credit type", max_length=20, choices=CREDIT_TYPE_CHOICES
    )
    character: str = models.CharField("Character", max_length=255, blank=True)
    order: int = models.IntegerField("Billing order", default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["movie", "person", "credit_type"],
                name="uq_movie_person_credit",
            ),
        ]
        indexes = [
            models.Index(fields=["movie", "credit_type", "order"]),
        ]
        ordering = ["order"]
        verbose_name = "movie credit"
        verbose_name_plural = "movie credits"

    def __str__(self) -> str:
        return f"{self.person.name} — {self.movie.title} ({self.get_credit_type_display()})"


class Comment(models.Model):
    """User comment on a movie.

    Maps to the `comments` table from docs/database-design.md. The `status`
    field is the hook for the moderation flow from phase 2 — the feed view
    filters on `VISIBLE` so `FLAGGED`, `HIDDEN` and `DELETED` comments drop
    out of the public list without any extra plumbing.
    """

    VISIBLE = "visible"
    FLAGGED = "flagged"
    HIDDEN = "hidden"
    DELETED = "deleted"
    STATUS_CHOICES = [
        (VISIBLE, "Widoczny"),
        (FLAGGED, "Zgłoszony"),
        (HIDDEN, "Ukryty"),
        (DELETED, "Usunięty"),
    ]

    MAX_LENGTH = 2000

    movie = models.ForeignKey(
        Movie,
        on_delete=models.CASCADE,
        related_name="comments",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="comments",
    )
    content: str = models.TextField("Treść", max_length=MAX_LENGTH)
    status: str = models.CharField(
        "Status",
        max_length=20,
        choices=STATUS_CHOICES,
        default=VISIBLE,
    )
    toxicity_score = models.DecimalField(
        "Toxicity score",
        max_digits=5,
        decimal_places=4,
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    moderated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["movie", "status", "-created_at"],
                name="ix_comments_movie_status",
            ),
        ]
        verbose_name = "comment"
        verbose_name_plural = "comments"

    def __str__(self) -> str:
        preview = self.content[:40] + ("…" if len(self.content) > 40 else "")
        return f"{self.user} → {self.movie}: {preview}"
