# Stack technologiczny

| Warstwa | Technologia | Wersja | Uzasadnienie |
|---|---|---|---|
| Język | Python | 3.13 | Stabilna wersja, dobre wsparcie dla type hints i async |
| Framework webowy | Django | 5.2.13 | Dojrzały, „batteries included" (ORM, admin, auth, formularze, migracje) |
| Walidacja danych | Pydantic | 2.x | Silne typy w warstwie domenowej (np. parsowanie odpowiedzi TMDB) |
| HTTP klient | httpx | 0.28+ | Sync + async, typing-friendly, lepsze API niż `requests` |
| Konfiguracja | python-dotenv | 1.x | `.env` w developmencie, zmienne środowiskowe w produkcji |
| Baza (dev) | SQLite | wbudowane | Zero-config, idealny do iteracji |
| Baza (prod) | PostgreSQL | Render Managed | Pełne wsparcie ORM, indeksy częściowe, JSONB jeśli potrzeba |
| Sterownik DB | psycopg | 3.2+ (binary) | Najnowsza generacja sterownika postgres |
| Konfiguracja URL bazy | dj-database-url | 2.3+ | Parsuje `DATABASE_URL` |
| Serwer aplikacyjny | Gunicorn | 23.x | Stabilny WSGI |
| Statyki | WhiteNoise | 6.x | Eliminuje potrzebę osobnego CDN, kompresja Brotli/gzip + manifest |
| E-mail | django-anymail (Brevo) | 14.x | Brevo w prod (transactional), fallback SMTP |
| CSS framework | Bootstrap | 5 | Szybki prototyp, gotowe komponenty (modal, alerts) |
| Ikony | Bootstrap Icons | 1.x | Spójna paleta z BS5 |
| Manager pakietów | uv | aktualna | Szybkość, lockfile, dependency groups |
| Linter / formatter | Ruff | 0.11+ | Najszybszy w Pythonie, jeden tool zamiast Flake8+isort+Black |
| Type checker | ty | 0.0.1a7 | Eksperymentalny, lekki sprawdzacz typów Astral |
| Testy unit/integration | pytest + pytest-django | 9.x / 4.12 | Standard de facto, bogata kolekcja pluginów |
| Testy E2E | Playwright + pytest-playwright | 1.58 / 0.7 | Auto-wait, codegen, trace viewer |
| Testy wydajnościowe | locust | 2.32+ | Zapis scenariuszy w Pythonie |
| SAST | bandit | 1.8+ | Wykrywa typowe wzorce niebezpiecznego kodu |
| CVE deps | pip-audit | 2.7+ | Skanuje przeciwko PyPI Advisory Database |
| Audyt a11y | pa11y | 9.1+ | HTML_CodeSniffer / WCAG2AA |
| Hosting | Render.com | — | Free tier wystarcza dla MVP, prosty deploy z `render.yaml` |
| CI/CD | GitHub Actions | — | Cztery workflowy: test, e2e, security, docs |
| Dokumentacja | MkDocs Material | 9.5+ | Markdown-first, wbudowane wyszukiwanie, ciemny tryb |

## Lock & reproducibility

- `pyproject.toml` — deklaracje, dependency groups (`dev`, `docs`).
- `uv.lock` — przypięte wersje wszystkich tranzytywnych zależności (commitowane).
- `.python-version` — `3.13`, używane przez `uv python install`.
- `pre-commit-config.yaml` — automatyczne uruchamianie ruff i ty przed commitami.
