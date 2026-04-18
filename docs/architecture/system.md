# Architektura systemu

Aster to klasyczna **trójwarstwowa aplikacja monolityczna** zbudowana
w Django. Warstwy są wyraźnie rozdzielone, ale działają w jednym
procesie WSGI.

## Diagram kontekstu (poziom 1)

```mermaid
graph LR
    User(["Użytkownik<br/>przeglądarka"])
    Admin(["Administrator<br/>przeglądarka"])
    Aster["Aster<br/>(Django + Gunicorn)"]
    Postgres[("PostgreSQL<br/>Render Managed")]
    TMDB[(TMDB API v3)]
    Brevo[(Brevo / SMTP)]
    Render["Render.com<br/>platforma hostingowa"]

    User -->|HTTPS| Aster
    Admin -->|HTTPS| Aster
    Aster -->|psycopg| Postgres
    Aster -->|HTTPS GET| TMDB
    Aster -->|API key / SMTP| Brevo
    Render -->|deploy<br/>build.sh| Aster
```

## Diagram komponentów (poziom 2)

```mermaid
graph TD
    subgraph Browser["Przeglądarka"]
        UI["HTML/CSS/JS<br/>Bootstrap 5 + custom"]
    end

    subgraph Aster["Proces Aster (Gunicorn worker)"]
        URLs["URL conf<br/>config/urls.py"]
        Views["Views<br/>(class-based + function-based)"]
        Forms["Forms<br/>(walidacja + UI)"]
        Services["Service layer<br/>movies/services.py"]
        Models["ORM Models<br/>accounts/, movies/"]
        Admin["Django Admin"]
        TmdbClient["TMDB client<br/>movies/tmdb.py"]
        Email["E-mail backend<br/>(Brevo lub SMTP)"]
        WhiteNoise["WhiteNoise<br/>static files"]
    end

    DB[(PostgreSQL / SQLite)]
    TMDB[(TMDB API)]
    BrevoOrSMTP[(Brevo / Gmail SMTP)]

    UI -->|HTTPS| URLs
    URLs --> Views
    Views --> Forms
    Views --> Services
    Services --> Models
    Services --> TmdbClient
    Models --> DB
    TmdbClient -->|httpx| TMDB
    Views --> Email
    Email --> BrevoOrSMTP
    URLs -.->|/static/| WhiteNoise
    Admin --> Models
```

## Warstwy

### 1. Prezentacja

- **Szablony Django** w `templates/`.
- **Bootstrap 5** + autorski CSS (`static/css/`).
- **JavaScript progresywny** (`static/js/`) — modal oceny, toggle
  „pokaż więcej gatunków". Aplikacja działa bez JS w trybie minimalnym.

### 2. Logika aplikacji

- **Views** — cienka warstwa, deleguje większość pracy do serwisów. Stosujemy mieszankę class-based (`TemplateView`, `FormView`, `UpdateView`) i function-based (akcje POST `update_status`, `update_rating`, `create_comment`, `delete_comment`).
- **Forms** — walidacja danych z GET/POST oraz cleanup (np. normalizacja e-maila).
- **Services** (`movies/services.py`, `accounts/utils.py`) — całość logiki domenowej: cache średnich ocen, integracja z TMDB, wysyłka maili aktywacyjnych, transakcyjność przy ratingach i statusach.

### 3. Dane

- **ORM Django** mapuje modele (`accounts.User`, `movies.Movie`, `movies.Rating`, `movies.Comment`, `movies.UserMovieStatus`, `movies.Person`, `movies.MovieCredit`, `movies.Genre`) na tabele PostgreSQL/SQLite.
- **Migracje** w `accounts/migrations/`, `movies/migrations/` — w tym data migration `0003_seed_all_tmdb_genres.py` zapełniający słownik gatunków.
- **Kompletny opis schematu** w [Architektura → Baza danych](database.md).
