# Raporty testowe

Sekcja zbiera **realne wyniki** z uruchomień każdej warstwy testów.
Wszystkie raporty są regenerowalne — komendy podane przy każdym
artefakcie.

## Jednostkowe + integracyjne (pytest)

```bash
uv run pytest --cov --cov-report=term --cov-report=html:docs/assets/tests/coverage
```

**Wynik z 18 kwietnia 2026:**

```
============================== 135 passed, 3 deselected in 9.30s ===============================
TOTAL                                              1270    218    83%
```

- **135 testów** zaliczonych, **0 nieudanych**
- **83% pokrycia** kodu produkcyjnego (`accounts/`, `core/`, `movies/`, `config/`)
- 3 testy E2E pominięte (uruchamiane osobnym workflow'em)

Pełny raport HTML: [`docs/assets/tests/coverage/index.html`](../assets/tests/coverage/index.html).

## E2E (Playwright)

```bash
DJANGO_ALLOW_ASYNC_UNSAFE=true uv run pytest tests/e2e -m e2e -v
```

**Wynik z 18 kwietnia 2026:**

```
tests/e2e/test_browse_rate_comment.py::test_browse_rate_comment[chromium] PASSED
tests/e2e/test_register_login.py::test_register_activate_login[chromium]   PASSED
tests/e2e/test_watchlist.py::test_watchlist_then_watched[chromium]         PASSED

============================== 3 passed in 6.56s ===============================
```

Każdy test pokrywa jedną ścieżkę użytkownika z [User Journeys](../ux/user-journeys.md).

## Wydajność (locust) {#wydajnosc}

Skrypt: [`tests/perf/locustfile.py`](https://github.com/agatav13/aster/blob/main/tests/perf/locustfile.py).

**Procedura uruchomienia:**

```bash
# Terminal 1 — produkcyjny serwer
DJANGO_DEBUG=False \
DJANGO_SECRET_KEY=local-perf-key \
DJANGO_ALLOWED_HOSTS=127.0.0.1,localhost \
uv run gunicorn config.wsgi --workers 1 --bind 127.0.0.1:8000

# Terminal 2 — seed użytkownika
uv run manage.py shell -c "from accounts.models import User; \
  User.objects.create_user(email='perf-user@example.com', \
    password='PerfPass!23456', is_active=True, is_email_verified=True)"

# Terminal 2 — uruchomienie locusta
uv run locust -f tests/perf/locustfile.py \
  --host http://127.0.0.1:8000 \
  --users 50 --spawn-rate 10 --run-time 5m \
  --headless --html docs/assets/perf/report.html
```

**Pass criteria** (sprawdzane manualnie po uruchomieniu):

- p95 < 500 ms dla `/`, `/movies/`, `/movies/<id>/`
- error rate < 1%
- 50 użytkowników jednocześnie sustained

Raport HTML powstaje w `docs/assets/perf/report.html` po każdym
uruchomieniu. **Brak automatyzacji w CI** — runners GitHub Actions są
zbyt zmienne dla wiarygodnych liczb.

## Bezpieczeństwo {#bezpieczenstwo}

### bandit (kod Python)

```bash
uv run bandit -r accounts core movies config -ll
```

**Wynik z 18 kwietnia 2026:**

```
Total issues (by severity):
  Undefined: 0
  Low:       39   (typowe false positives — np. import `random`)
  Medium:    0
  High:      0
```

- **Zero znalezisk medium+** (próg blokujący w CI).
- 39 znalezisk low są raportowane informacyjnie i nie blokują merge.

Pełny JSON: [`docs/assets/security/bandit-report.json`](../assets/security/bandit-report.json).

### pip-audit (CVE zależności)

```bash
uv run pip-audit
```

**Wynik z 18 kwietnia 2026:**

```
No known vulnerabilities found
```

- Wcześniejsze uruchomienie znalazło 5 CVE w Django 5.2.12 → bumped do 5.2.13 (kompatybilna minor) → clean.

Pełny JSON: [`docs/assets/security/pip-audit-report.json`](../assets/security/pip-audit-report.json).

### Django check --deploy

```bash
DJANGO_DEBUG=False DJANGO_SECRET_KEY="<random 64+>" \
DJANGO_ALLOWED_HOSTS=aster-1lf7.onrender.com \
uv run manage.py check --deploy --fail-level WARNING
```

**Wynik z 18 kwietnia 2026:**

```
System check identified no issues (0 silenced).
```

- Wcześniejsze uruchomienie wykryło 5 ostrzeżeń (W004 HSTS, W008 SSL redirect, W012 SESSION_COOKIE_SECURE, W016 CSRF_COOKIE_SECURE, W009 słaby SECRET_KEY).
- Wszystkie naprawione w `config/settings.py` (warunkowe hardening dla `DEBUG=False`).

Pełny output: [`docs/assets/security/django-deploy-check.txt`](../assets/security/django-deploy-check.txt).

## Dostępność {#dostepnosc}

```bash
npx --yes pa11y https://aster-1lf7.onrender.com/auth/login/
npx --yes pa11y https://aster-1lf7.onrender.com/auth/register/
npx --yes pa11y https://aster-1lf7.onrender.com/movies/
npx --yes pa11y https://aster-1lf7.onrender.com/movies/<id>/
```

**Wynik z 18 kwietnia 2026:**

| Strona | Wynik | Standard |
|---|---|---|
| `/auth/login/` | ✅ No issues found | WCAG2AA |
| `/auth/register/` | ✅ No issues found | WCAG2AA |
| `/movies/` | ✅ No issues found | WCAG2AA |
| `/movies/687163/` | ✅ No issues found | WCAG2AA |

Pełne raporty HTML: [`docs/assets/a11y/`](../assets/a11y/).
