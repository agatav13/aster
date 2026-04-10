from django.core.management.base import BaseCommand, CommandError

from movies.services import sync_all_genres
from movies.tmdb import TmdbApiError, TmdbClient, TmdbConfigError


class Command(BaseCommand):
    help = "Sync the genre dictionary from TMDB into the local Genre table."

    def handle(self, *args: object, **options: object) -> None:
        try:
            client = TmdbClient()
        except TmdbConfigError as exc:
            raise CommandError(str(exc)) from exc

        try:
            count = sync_all_genres(client)
        except TmdbApiError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(self.style.SUCCESS(f"Synced {count} genres from TMDB."))
