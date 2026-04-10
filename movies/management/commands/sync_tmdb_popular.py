from django.core.management.base import BaseCommand, CommandError

from movies.services import upsert_movie_summary
from movies.tmdb import TmdbApiError, TmdbClient, TmdbConfigError


class Command(BaseCommand):
    help = "Pull popular movies from TMDB and upsert them locally."

    def add_arguments(self, parser: object) -> None:
        parser.add_argument(  # type: ignore[attr-defined]
            "--pages",
            type=int,
            default=1,
            help="How many pages of /discover/movie to ingest (20 movies per page).",
        )

    def handle(self, *args: object, **options: object) -> None:
        pages: int = options["pages"]  # type: ignore[index]
        try:
            client = TmdbClient()
        except TmdbConfigError as exc:
            raise CommandError(str(exc)) from exc

        total = 0
        for page in range(1, pages + 1):
            try:
                response = client.discover_popular(page=page)
            except TmdbApiError as exc:
                raise CommandError(str(exc)) from exc
            for summary in response.results:
                upsert_movie_summary(summary, client)
                total += 1
            self.stdout.write(
                f"Page {page}/{pages}: cached {len(response.results)} movies."
            )

        self.stdout.write(
            self.style.SUCCESS(f"Done. Upserted {total} movies from TMDB.")
        )
