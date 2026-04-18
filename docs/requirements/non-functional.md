# Wymagania niefunkcjonalne

Wymagania niefunkcjonalne (NFR) opisują **jak dobrze** system ma
działać — odpowiadają na pytania o czas odpowiedzi, odporność na
ataki, możliwość wzrostu, zgodność ze standardami dostępności.

## Wydajność

Cel: aplikacja ma działać responsywnie dla pojedynczego użytkownika
i nie degradować się gwałtownie pod normalnym ruchem (~50 osób
jednocześnie).

| Parametr | Wartość docelowa | Pomiar |
|---|---|---|
| p95 czasu odpowiedzi (`/`, `/movies/`, `/movies/<id>/`) | < 500 ms | locust 50 użytkowników, 5 min |
| Średni czas odpowiedzi katalogu (z miss cache TMDB) | < 1 s | locust |
| Maksymalna liczba użytkowników jednoczesnych | ≥ 50 | locust |
| Wskaźnik błędów (HTTP 5xx) | < 1 % | locust |

**Co to znaczy „p95 < 500 ms"?** 95% żądań zostaje obsłużonych w
mniej niż pół sekundy — pozostałe 5% (ogon dystrybucji) może być
wolniejszych, np. z powodu zimnego cache TMDB lub odświeżania średnich
ocen.

**Mechanizmy wspierające wydajność:**

- **Cache średnich ocen** w kolumnach `Movie.average_rating` i
  `Movie.ratings_count` — eliminuje agregację `AVG/COUNT` przy każdym
  wyświetleniu listy filmów.
- **Cache-first dla TMDB** — `fetch_and_cache_movie` pyta najpierw
  lokalną bazę, dopiero w razie miss sięga do API.
- **Indeksy bazy danych** na często filtrowanych kolumnach
  (komentarze, statusy oglądania).
- **Paginacja** wyników listy filmów (Django `Paginator`).

Pomiary i procedurę odtworzenia opisuje [Raporty testowe → Wydajność](../testing/reports.md#wydajnosc).
Skrypt: [`tests/perf/locustfile.py`](https://github.com/agatav13/aster/blob/main/tests/perf/locustfile.py).

## Bezpieczeństwo

Aplikacja korzysta z domyślnego stosu zabezpieczeń Django oraz
trzech automatycznych skanerów uruchamianych na każdym PR
(workflow `.github/workflows/security.yml`).

| Mechanizm | Realizacja |
|---|---|
| Hashing haseł | Django PBKDF2 (`AUTH_PASSWORD_VALIDATORS`) |
| Wymagania jakości haseł | Walidatory: minimalna długość, różność od e-maila, blokada popularnych haseł, blokada haseł czysto numerycznych |
| Weryfikacja e-mail | Token jednorazowy (24 h ważności) przed `is_active=True` |
| CSRF | Middleware `django.middleware.csrf.CsrfViewMiddleware` + token w każdym formularzu |
| HTTPS | `SECURE_SSL_REDIRECT=True` w produkcji + HSTS (1 rok, include subdomains, preload) |
| Cookies | `SESSION_COOKIE_SECURE=True`, `CSRF_COOKIE_SECURE=True` w produkcji |
| Klikjacking | `X_FRAME_OPTIONS = "DENY"` |
| Ochrona przed XSS | Auto-escape w szablonach Django + `SECURE_CONTENT_TYPE_NOSNIFF` |
| Static analysis (kod) | `bandit -ll` (medium+ severity) na każdym PR |
| Vulnerable deps | `pip-audit` na każdym PR |
| Audyt konfiguracji | `manage.py check --deploy --fail-level WARNING` |

**Trzy warstwy automatycznych skanerów:**

1. **bandit** — szuka niebezpiecznych wzorców w kodzie Pythona
   (np. `eval`, hardcoded passwords, słabe algorytmy kryptograficzne).
2. **pip-audit** — porównuje zainstalowane wersje pakietów z bazą CVE
   (PyPI Advisory Database). Wykrył np. 5 CVE w Django 5.2.12 → wymusił
   bump do 5.2.13.
3. **`manage.py check --deploy`** — wbudowany audyt produkcyjny Django
   (HSTS, secure cookies, SSL redirect, długość SECRET_KEY itp.).

Pełne raporty: [Raporty testowe → Bezpieczeństwo](../testing/reports.md#bezpieczenstwo).

### Zaakceptowane ryzyka (ver_1)

- **Brak rate limiting** na endpointach logowania i rejestracji — do
  wdrożenia. Ryzyko: brute-force
  haseł, spam rejestracji.
- **Brak 2FA** — kompromis między prostotą onboardingu a poziomem
  bezpieczeństwa kont. Akceptowalny dla aplikacji o niskim zagrożeniu
  (brak danych płatniczych, brak danych wrażliwych).

## Skalowalność

Aster jest zaprojektowany dla **pojedynczej instancji** Django
hostowanej na Render.com. Skalowanie horyzontalne (wiele workerów,
rozproszony cache, kolejkowanie zadań) nie jest wspierane w bieżącej
wersji.

**Limit obecnej architektury:** ~50 użytkowników jednocześnie
(potwierdzone testami locust).

**Mechanizmy skalowalności:**

- **Cache średnich ocen** (`Movie.average_rating`, `Movie.ratings_count`) —
  unika kosztownego `AVG/COUNT` przy każdym wyświetleniu listy.
- **Indeksy bazy** na `(movie, status, -created_at)` dla komentarzy
  oraz `(user, status)` dla statusów oglądania — pozwalają na szybkie
  filtrowanie list bez full scan.
- **Paginacja** wyników listy filmów (Django `Paginator`).
- **Stateless serwery** — sesje w bazie, brak danych w pamięci procesu,
  co umożliwia trywialne dodanie kolejnych instancji w ver_2.
- **WhiteNoise** z manifestowaną kompresją — statyki serwowane z
  gzip/Brotli bezpośrednio przez Gunicorna, bez potrzeby CDN.

## Dostępność (accessibility)

Aplikacja przeszła automatyczny audyt **pa11y** (silnik
HTML_CodeSniffer, standard WCAG2AA) na czterech kluczowych stronach:

| Strona | Wynik |
|---|---|
| `/auth/login/` | bez błędów |
| `/auth/register/` | bez błędów |
| `/movies/` | bez błędów |
| `/movies/<id>/` | bez błędów |

**Co to znaczy „WCAG2AA"?** Web Content Accessibility Guidelines 2.x
poziom AA — międzynarodowy standard dostępności wymagany m.in. przez
przepisy UE (Dyrektywa o dostępności stron internetowych instytucji
publicznych). Pokrywa kontrast tekstu, etykiety formularzy, obsługę
klawiatury, struktury nagłówków.

**Dodatkowe praktyki obecne w szablonach:**

- **Semantyczny HTML5** (`<header>`, `<nav>`, `<main>`, `<article>`, `<section>`, `<form>`) — pomaga czytnikom ekranu zrozumieć strukturę strony.
- **Etykiety formularzy** powiązane z polami przez `for`/`id`.
- **Atrybuty `aria-label`** na ikonach i przyciskach bez tekstu (np. przycisk wyszukiwania w nagłówku).
- **`aria-pressed`** na przyciskach trybu (watchlist/watched) — informuje czytnik ekranu o aktualnym stanie.
- **Atrybut `alt`** na każdym `<img>` (np. „Plakat: {tytuł filmu}").
- **`role="group"` + `aria-labelledby`** na siatce wyboru gatunków — grupuje powiązane checkboxy w czytniku ekranu.
- **`visually-hidden`** klasy zamiast `display:none` dla treści przeznaczonych dla czytników ekranu (np. ukryta etykieta pola komentarza).
- **Kontrast kolorów** — paleta zaprojektowana z myślą o WCAG AA (warm charcoal vs. parchment, dusty rose accent).

Pełny raport: [Raporty testowe → Dostępność](../testing/reports.md#dostepnosc).

## Kompatybilność

- **Przeglądarki:** Chromium, Firefox, Safari w aktualnych wersjach (testowane przez Playwright na Chromium w CI).
- **Język interfejsu:** polski. Treści użytkownika (komentarze) bez ograniczeń językowych.
- **Responsywność:** Bootstrap 5 + autorski CSS — siatka filmów dostosowuje się od mobilnych do desktopowych szerokości.
- **API zewnętrzne:** TMDB v3 (publiczne, bez SLA — patrz [Architektura → API](../architecture/apis.md)).
- **Wersja Python:** 3.13 (wymagana, sprawdzana w `.python-version`).
