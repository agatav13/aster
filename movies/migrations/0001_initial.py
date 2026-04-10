from decimal import Decimal

from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("accounts", "0002_genre_user_favorite_genres"),
    ]

    operations = [
        # Move Genre into the movies app at the Django state level only.
        # The underlying accounts_genre table is reused (see Genre.Meta.db_table)
        # to avoid a destructive ALTER TABLE RENAME and the FK churn it would
        # cause on the User.favorite_genres through table.
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name="Genre",
                    fields=[
                        (
                            "id",
                            models.BigAutoField(
                                auto_created=True,
                                primary_key=True,
                                serialize=False,
                                verbose_name="ID",
                            ),
                        ),
                        (
                            "name",
                            models.CharField(
                                max_length=50, unique=True, verbose_name="Name"
                            ),
                        ),
                    ],
                    options={
                        "verbose_name": "genre",
                        "verbose_name_plural": "genres",
                        "ordering": ["name"],
                        "db_table": "accounts_genre",
                    },
                ),
            ],
            database_operations=[],
        ),
        migrations.AddField(
            model_name="genre",
            name="tmdb_id",
            field=models.IntegerField(
                blank=True, null=True, unique=True, verbose_name="TMDB id"
            ),
        ),
        migrations.CreateModel(
            name="Movie",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("tmdb_id", models.IntegerField(unique=True, verbose_name="TMDB id")),
                ("title", models.CharField(max_length=255, verbose_name="Title")),
                (
                    "original_title",
                    models.CharField(
                        blank=True, max_length=255, verbose_name="Original title"
                    ),
                ),
                ("overview", models.TextField(blank=True, verbose_name="Overview")),
                (
                    "release_date",
                    models.DateField(blank=True, null=True, verbose_name="Release date"),
                ),
                (
                    "runtime_minutes",
                    models.IntegerField(
                        blank=True, null=True, verbose_name="Runtime (minutes)"
                    ),
                ),
                (
                    "poster_url",
                    models.URLField(blank=True, max_length=500, verbose_name="Poster URL"),
                ),
                (
                    "backdrop_url",
                    models.URLField(
                        blank=True, max_length=500, verbose_name="Backdrop URL"
                    ),
                ),
                (
                    "original_language",
                    models.CharField(
                        blank=True, max_length=10, verbose_name="Original language"
                    ),
                ),
                (
                    "average_rating",
                    models.DecimalField(
                        decimal_places=2,
                        default=Decimal("0.00"),
                        max_digits=3,
                        verbose_name="Average rating",
                    ),
                ),
                (
                    "ratings_count",
                    models.IntegerField(default=0, verbose_name="Ratings count"),
                ),
                (
                    "popularity",
                    models.DecimalField(
                        blank=True,
                        decimal_places=2,
                        max_digits=10,
                        null=True,
                        verbose_name="Popularity",
                    ),
                ),
                (
                    "tmdb_synced_at",
                    models.DateTimeField(
                        blank=True, null=True, verbose_name="Last TMDB sync"
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "genres",
                    models.ManyToManyField(
                        blank=True, related_name="movies", to="movies.genre"
                    ),
                ),
            ],
            options={
                "ordering": ["-popularity", "title"],
            },
        ),
        migrations.AddIndex(
            model_name="movie",
            index=models.Index(fields=["title"], name="movies_movi_title_652549_idx"),
        ),
        migrations.AddIndex(
            model_name="movie",
            index=models.Index(fields=["-popularity"], name="movies_movi_popular_3c541f_idx"),
        ),
    ]
