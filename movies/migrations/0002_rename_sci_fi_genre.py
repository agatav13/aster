from django.db import migrations


def rename_sci_fi(apps, schema_editor) -> None:
    Genre = apps.get_model("movies", "Genre")
    # Only rename if the new name doesn't already exist (idempotent + safe).
    if Genre.objects.filter(name="Science Fiction").exists():
        return
    Genre.objects.filter(name="Sci-Fi").update(name="Science Fiction")


def revert(apps, schema_editor) -> None:
    Genre = apps.get_model("movies", "Genre")
    if Genre.objects.filter(name="Sci-Fi").exists():
        return
    # Only revert rows that were never linked to TMDB.
    Genre.objects.filter(name="Science Fiction", tmdb_id__isnull=True).update(
        name="Sci-Fi"
    )


class Migration(migrations.Migration):
    dependencies = [
        ("movies", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(rename_sci_fi, revert),
    ]
