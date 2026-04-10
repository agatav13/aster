from django.core.management.base import BaseCommand

from movies.services import normalize_all_genres


class Command(BaseCommand):
    help = (
        "Consolidate the Genre table to canonical Polish names. Safe to run "
        "repeatedly. Use this to recover from a botched sync that left "
        "English-named duplicates in the database."
    )

    def handle(self, *args: object, **options: object) -> None:
        report = normalize_all_genres()
        self.stdout.write(
            self.style.SUCCESS(
                f"Upserted {report['upserted']} canonical genres, "
                f"merged {report['merged_orphans']} English orphans, "
                f"renamed {report['renamed_orphans']} loose rows."
            )
        )
