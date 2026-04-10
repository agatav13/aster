from django.db import migrations, models


class Migration(migrations.Migration):
    """Drop the old accounts.Genre state entry now that movies.Genre owns it.

    The accounts_genre table itself is intentionally NOT touched: movies.Genre
    declares db_table='accounts_genre' and the User.favorite_genres through
    table keeps its existing FK. Everything here is state-only.
    """

    dependencies = [
        ("accounts", "0002_genre_user_favorite_genres"),
        ("movies", "0001_initial"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterField(
                    model_name="user",
                    name="favorite_genres",
                    field=models.ManyToManyField(
                        blank=True,
                        related_name="users",
                        to="movies.genre",
                        verbose_name="Ulubione gatunki",
                    ),
                ),
                migrations.DeleteModel(name="Genre"),
            ],
            database_operations=[],
        ),
    ]
