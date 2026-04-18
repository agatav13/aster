# Podręcznik administratora

Dokument dla osoby utrzymującej instalację Aster — Twoje przyszłe „ja",
następca, lub recenzent oddającego projekt.

## Dostęp do panelu administracyjnego

Adres: `<APP_BASE_URL><DJANGO_ADMIN_URL>` (domyślnie `/admin/`, ale w
produkcji warto użyć trudniejszej do zgadnięcia ścieżki przez zmienną
`DJANGO_ADMIN_URL`, np. `secret-admin/`).

### Tworzenie konta superusera

```bash
uv run manage.py createsuperuser
# E-mail: admin@example.com
# Password: ********
```

Konto powstaje od razu z `is_active=True`, `is_staff=True`, `is_superuser=True`, `is_email_verified=True`.

### Logowanie

Otwórz `<DJANGO_ADMIN_URL>` → wpisz e-mail + hasło → otrzymujesz pełen panel.

## Częste operacje

### Dezaktywacja użytkownika

1. Panel → **Users**
2. Wybierz użytkownika
3. Odznacz **Is active**
4. **Save**

Skutek: użytkownik nie może się zalogować, jego treści (oceny, komentarze, statusy) zostają w bazie.

### Moderacja komentarza

1. Panel → **Comments**
2. Wybierz komentarz
3. Zmień **Status** na `hidden` (ukryty z widoku publicznego, zostaje w bazie do audytu) lub `deleted` (oznaczony do usunięcia w przyszłej operacji czyszczącej)
4. **Save**

Lista publiczna automatycznie filtruje na `status='visible'`, więc zmiana zadziała natychmiast po refreshu.

### Bulk-import filmów

Zob. [Synchronizacja z TMDB](#synchronizacja-z-tmdb).

### Zmiana nazwy gatunku

1. Panel → **Genres**
2. Wybierz wiersz
3. Edytuj **Name** i ewentualnie **TMDB id**
4. **Save**

> **Uwaga:** zmiana `tmdb_id` może rozpiąć powiązanie z TMDB; bezpiecznie zmieniaj tylko `name` (np. by wymusić polską formę).

## Synchronizacja z TMDB

Wszystkie komendy działają niezależnie i są bezpieczne do
wielokrotnego uruchomienia (idempotentne).

### Pierwsza inicjalizacja po deployu

```bash
# Zapełnij słownik gatunków (19 kanonicznych nazw TMDB → polskie tłumaczenia)
uv run manage.py sync_tmdb_genres

# Pobierz N stron popularnych filmów (po 20 sztuk = 60 filmów)
uv run manage.py sync_tmdb_popular --pages 3
```

### Aktualizacja katalogu

```bash
# Świeże popularne filmy (np. cotygodniowo)
uv run manage.py sync_tmdb_popular --pages 5

# Uzupełnij obsadę i reżyserię tam, gdzie ich brakuje
uv run manage.py backfill_credits
```

## Backup i restore {#backup-i-restore}

### PostgreSQL na Render

```bash
# Backup (lokalnie, z Render's psql connection string)
pg_dump "$DATABASE_URL" --format=custom --file=backup_$(date +%F).dump

# Restore
pg_restore --clean --if-exists --no-owner --dbname="$DATABASE_URL" backup_2026-04-18.dump
```

Zalecenie: trzymaj 4 ostatnie tygodniowe dumpy + 12 ostatnich miesięcznych. Można zautomatyzować przez GitHub Actions cron job z artefaktami (retention 30 dni).

### SQLite (dev)

Plik `db.sqlite3` w korzeniu projektu. Backup = `cp db.sqlite3 db_$(date +%F).sqlite3`.

## Monitoring

- **Render dashboard** — wykorzystanie CPU/RAM, logi runtime, statystyki HTTP.
- **Logi aplikacji** — filtruj `accounts`, `movies`, `core` na poziomie INFO. Najważniejsze zdarzenia (rejestracja, logowanie, aktywacja, wystawienie oceny, edycja profilu) są logowane z poziomem INFO.
- **Healthcheck** — Render auto-restartuje przy `/health/` zwracającym non-200.

## Typowe problemy

| Problem | Diagnoza | Rozwiązanie |
|---|---|---|
| Użytkownik nie dostaje maila aktywacyjnego | Render logs → `Activation email failed` | Sprawdź `BREVO_API_KEY` lub `EMAIL_HOST_*`. Użytkownik może użyć `/auth/resend-activation/`. |
| Lista filmów pusta na produkcji | Brak `TMDB_API_KEY` lub niesynchronizowana baza | Ustaw klucz, uruchom `sync_tmdb_popular --pages 3`. |
| Błąd 500 po deployu | Migracja wisi | Sprawdź `build.sh` w logach Render. Jeśli migracja niekompatybilna — restart manualny + `migrate --fake-initial`. |
| `CSRF verification failed` przy POST | Brakuje `CSRF_TRUSTED_ORIGINS` po dodaniu nowego subdomenu | Dodaj `https://<host>` do zmiennej `CSRF_TRUSTED_ORIGINS`. |
| Cold start > 60 s | Render free tier uśpiony | Upgrade do paid plan lub zewnętrzny pinger (np. cron-job.org co 10 min). |
