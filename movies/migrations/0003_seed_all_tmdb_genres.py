from django.db import migrations

# Canonical (tmdb_id, Polish name) pairs for every standard TMDB movie genre.
# Mirrors TMDB_GENRE_PL_NAMES in movies/services.py; duplicated here because
# data migrations cannot safely import app-level modules.
CANONICAL_GENRES: list[tuple[int, str]] = [
    (28, "Akcja"),
    (12, "Przygodowy"),
    (16, "Animacja"),
    (35, "Komedia"),
    (80, "Kryminał"),
    (99, "Dokumentalny"),
    (18, "Dramat"),
    (10751, "Familijny"),
    (14, "Fantasy"),
    (36, "Historyczny"),
    (27, "Horror"),
    (10402, "Muzyka"),
    (9648, "Tajemnica"),
    (10749, "Romans"),
    (878, "Science Fiction"),
    (10770, "Film telewizyjny"),
    (53, "Thriller"),
    (10752, "Wojenny"),
    (37, "Western"),
]


def seed_missing_genres(apps, schema_editor) -> None:
    """Create any canonical TMDB genre rows that don't exist yet.

    Deliberately minimal: does NOT touch existing rows (which may have been
    seeded without a tmdb_id by accounts/0002 and rely on `sync_tmdb_genres`
    or `upsert_genre` to get linked later). Only creates rows that are
    missing entirely, so users who never run the TMDB sync still get all
    19 canonical genres in the registration selector.
    """
    Genre = apps.get_model("movies", "Genre")
    for tmdb_id, name in CANONICAL_GENRES:
        if Genre.objects.filter(tmdb_id=tmdb_id).exists():
            continue
        if Genre.objects.filter(name__iexact=name).exists():
            continue
        Genre.objects.create(tmdb_id=tmdb_id, name=name)


def noop_reverse(apps, schema_editor) -> None:
    """Forward-only seed; rolling back would risk deleting user favorites."""
    return None


class Migration(migrations.Migration):
    dependencies = [
        ("movies", "0002_rename_sci_fi_genre"),
    ]

    operations = [
        migrations.RunPython(seed_missing_genres, noop_reverse),
    ]
