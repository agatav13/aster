from django.db import migrations, models


def seed_genres(apps, schema_editor):
    Genre = apps.get_model("accounts", "Genre")
    genres = [
        "Akcja",
        "Animacja",
        "Dokumentalny",
        "Dramat",
        "Fantasy",
        "Historyczny",
        "Horror",
        "Komedia",
        "Kryminał",
        "Przygodowy",
        "Romans",
        "Sci-Fi",
        "Thriller",
    ]
    for name in genres:
        Genre.objects.get_or_create(name=name)


def unseed_genres(apps, schema_editor):
    Genre = apps.get_model("accounts", "Genre")
    Genre.objects.filter(
        name__in=[
            "Akcja",
            "Animacja",
            "Dokumentalny",
            "Dramat",
            "Fantasy",
            "Historyczny",
            "Horror",
            "Komedia",
            "Kryminał",
            "Przygodowy",
            "Romans",
            "Sci-Fi",
            "Thriller",
        ]
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0001_initial"),
    ]

    operations = [
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
                    models.CharField(max_length=50, unique=True, verbose_name="Nazwa"),
                ),
            ],
            options={
                "verbose_name": "gatunek",
                "verbose_name_plural": "gatunki",
                "ordering": ["name"],
            },
        ),
        migrations.AddField(
            model_name="user",
            name="favorite_genres",
            field=models.ManyToManyField(
                blank=True,
                related_name="users",
                to="accounts.genre",
                verbose_name="Ulubione gatunki",
            ),
        ),
        migrations.RunPython(seed_genres, unseed_genres),
    ]
