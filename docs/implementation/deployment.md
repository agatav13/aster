# Wdrożenie i konfiguracja środowisk

## Wymagania

- **Python 3.13** (sprawdzane przez `.python-version`)
- **uv** (manager pakietów Astrala)
- **Node.js 20+** — tylko jeśli chcesz lokalnie uruchamiać `pa11y`

## Środowisko developerskie

```bash
# 1. Klon i wejście do katalogu
git clone https://github.com/agatav13/aster.git
cd aster

# 2. Plik .env (minimalny)
cat > .env <<'EOF'
DJANGO_SECRET_KEY=dev-secret-change-me
DJANGO_DEBUG=True
TMDB_API_KEY=<twoj-klucz-v3>
EOF

# 3. Instalacja zależności
uv sync --group dev

# 4. Migracje
uv run manage.py migrate

# 5. Konto administratora
uv run manage.py createsuperuser

# 6. (opcjonalnie) Seed gatunków + popularnych filmów z TMDB
uv run manage.py sync_tmdb_genres
uv run manage.py sync_tmdb_popular --pages 3

# 7. Serwer dev
uv run manage.py runserver
# → http://127.0.0.1:8000/
```

### Dodatkowe grupy zależności

```bash
uv sync --group docs       # MkDocs + Material (dla mkdocs serve)
uv sync --all-extras --dev # wszystkie deps + Playwright, locust, bandit
```

## Środowisko testowe

```bash
# Wszystkie unit/integration testy z pokryciem
uv run pytest --cov

# Tylko E2E (wymagają Chromium)
uv run playwright install chromium
DJANGO_ALLOW_ASYNC_UNSAFE=true uv run pytest tests/e2e -m e2e
```

Zmienna `DJANGO_ALLOW_ASYNC_UNSAFE` jest wymagana, bo `pytest-playwright`
uruchamia kod w pętli asyncio, a `pytest-django` musi w tle wykonać
sync ORM (tworzenie testowej bazy). To znana niezgodność, opisana w
issue trackerach obu pluginów.

## Środowisko produkcyjne (Render.com)

Konfiguracja w pliku [`render.yaml`](https://github.com/agatav13/aster/blob/main/render.yaml).

### Build

Plik [`build.sh`](https://github.com/agatav13/aster/blob/main/build.sh):

```bash
#!/usr/bin/env bash
set -o errexit
uv sync --python 3.13
uv run manage.py collectstatic --noinput
uv run manage.py migrate
```

### Start

Render uruchamia: `uv run gunicorn config.wsgi:application` (parametry serwowania — port, liczba workerów — pochodzą ze zmiennych środowiskowych Render / domyślnych Gunicorna).

### Wymagane zmienne środowiskowe

| Zmienna | Wartość przykładowa | Opis |
|---|---|---|
| `DJANGO_SECRET_KEY` | losowy 64+ znaków | sekret sesji i tokenów |
| `DJANGO_DEBUG` | `False` | wyłącza tryb dev |
| `DJANGO_ALLOWED_HOSTS` | `aster-1lf7.onrender.com` | jak w hoście Render |
| `DATABASE_URL` | `postgresql://...` | z Render Managed DB |
| `REDIS_URL` | `redis://...` | współdzielony cache między workerami Gunicorna; gdy nie ustawiona, aplikacja degraduje do `LocMemCache` (cache per-proces) |
| `TMDB_API_KEY` | klucz v3 | konieczny dla katalogu |
| `TMDB_REQUEST_TIMEOUT` | `3` (domyślnie) | timeout HTTP w sekundach dla klienta TMDB |
| `TMDB_RESPONSE_CACHE_TTL` | `900` (domyślnie) | TTL cache odpowiedzi TMDB w sekundach |
| `BREVO_API_KEY` | (opcjonalnie) | jeśli chcesz Brevo zamiast SMTP |
| `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD` | — | gdy używasz SMTP |
| `DEFAULT_FROM_EMAIL` | `noreply@aster.example` | adres nadawcy |
| `APP_BASE_URL` | `https://aster-1lf7.onrender.com` | bazowy URL dla linków w mailach |
| `DJANGO_ADMIN_URL` | np. `secret-admin/` | utrudnia automatyczne skanowanie |
| `CSRF_TRUSTED_ORIGINS` | `https://aster-1lf7.onrender.com` | wymagane dla POST z innego subdomenu |

### Hardening produkcyjny (włączane gdy `DEBUG=False`)

- `SECURE_SSL_REDIRECT=True`
- `SECURE_PROXY_SSL_HEADER=('HTTP_X_FORWARDED_PROTO','https')` — bo Render terminuje SSL na proxy
- `SESSION_COOKIE_SECURE=True`, `CSRF_COOKIE_SECURE=True`
- HSTS 1 rok, include subdomains, preload
- `X_FRAME_OPTIONS='DENY'`
- `SECURE_REFERRER_POLICY='same-origin'`
- `SECURE_CONTENT_TYPE_NOSNIFF=True`
