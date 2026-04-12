import time

from django.core.management.base import BaseCommand, CommandError

from movies.models import Movie
from movies.services import sync_movie_credits
from movies.tmdb import TmdbApiError, TmdbClient, TmdbConfigError


class Command(BaseCommand):
    help = "Backfill director and cast credits from TMDB for cached movies that have none."

    def add_arguments(self, parser: object) -> None:
        parser.add_argument(  # type: ignore[attr-defined]
            "--sleep",
            type=float,
            default=0.25,
            help="Seconds to wait between TMDB requests (rate-limit courtesy).",
        )

    def handle(self, *args: object, **options: object) -> None:
        sleep_seconds: float = options["sleep"]  # type: ignore[index]
        try:
            client = TmdbClient()
        except TmdbConfigError as exc:
            raise CommandError(str(exc)) from exc

        movies = Movie.objects.filter(credits__isnull=True).distinct()
        total = movies.count()
        if total == 0:
            self.stdout.write(self.style.SUCCESS("All cached movies already have credits."))
            return

        self.stdout.write(f"Found {total} movies without credits. Backfilling...")

        ok = 0
        failed = 0
        for i, movie in enumerate(movies.iterator(), 1):
            try:
                detail = client.get_movie(movie.tmdb_id)
            except TmdbApiError as exc:
                self.stderr.write(f"  [{i}/{total}] TMDB error for {movie.title} (tmdb_id={movie.tmdb_id}): {exc}")
                failed += 1
                continue

            if detail.credits:
                sync_movie_credits(movie, detail.credits, client)
                credit_count = movie.credits.count()
                self.stdout.write(f"  [{i}/{total}] {movie.title}: {credit_count} credits synced.")
            else:
                self.stdout.write(f"  [{i}/{total}] {movie.title}: no credits on TMDB.")

            ok += 1
            if i < total:
                time.sleep(sleep_seconds)

        self.stdout.write(
            self.style.SUCCESS(f"Done. Backfilled {ok} movies, {failed} failed.")
        )
