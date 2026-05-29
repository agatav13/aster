from decimal import Decimal

from django.db import migrations
from django.db.models import Avg, Count


def recompute_rating_aggregates(apps, schema_editor) -> None:
    """Resync Movie.average_rating / ratings_count from the ratings table.

    The cached aggregates on Movie are only refreshed inside the rating
    service helpers (upsert_rating / remove_rating). Deleting Rating rows
    by any other path — e.g. cascading from a User deletion in the admin —
    leaves the cached values stale. This one-shot, idempotent backfill
    rebuilds them from the source of truth so every movie reflects only the
    ratings that still exist. Mirrors movies.services._refresh_movie_rating_aggregates.
    """
    Movie = apps.get_model("movies", "Movie")
    Rating = apps.get_model("movies", "Rating")

    stats_by_movie = {
        row["movie_id"]: row
        for row in Rating.objects.values("movie_id").annotate(
            avg=Avg("score"), total=Count("id")
        )
    }

    updated: list = []
    for movie in Movie.objects.all().iterator():
        stats = stats_by_movie.get(movie.pk)
        if not stats or not stats["total"] or stats["avg"] is None:
            movie.average_rating = Decimal("0.00")
            movie.ratings_count = 0
        else:
            movie.average_rating = Decimal(str(stats["avg"])).quantize(Decimal("0.01"))
            movie.ratings_count = stats["total"]
        updated.append(movie)

    if updated:
        Movie.objects.bulk_update(
            updated, ["average_rating", "ratings_count"], batch_size=500
        )


class Migration(migrations.Migration):
    dependencies = [
        ("movies", "0011_movienote"),
    ]

    operations = [
        migrations.RunPython(recompute_rating_aggregates, migrations.RunPython.noop),
    ]
