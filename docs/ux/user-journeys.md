# Ścieżki użytkownika

Trzy główne ścieżki. Każda kończy się odsyłaczem do testu
E2E, który ją automatycznie weryfikuje.

Wszystkie wireframe'y (lo-fi, Excalidraw) leżą w katalogu
[`docs/assets/wireframes/lo-fi/`](https://github.com/agatav13/aster/tree/main/docs/assets/wireframes/lo-fi)
na GitHubie — kolumna „Ekran" linkuje do konkretnego pliku.

## Ścieżka 1 — Rejestracja, aktywacja, pierwsze logowanie

**Persona:** Gość chce założyć konto, aby móc oceniać filmy.

| # | Cel użytkownika | Akcja | Reakcja systemu | Ekran |
|---|---|---|---|---|
| 1 | Założyć konto | Otwiera `/auth/register/` | Wyświetlenie formularza rejestracji | [login-panel.png](https://github.com/agatav13/aster/blob/main/docs/assets/wireframes/lo-fi/login-panel.png) |
| 2 | Podać dane | Wpisuje e-mail, opcjonalnie nazwę, hasło ×2, zaznacza ulubione gatunki | Walidacja po stronie klienta i serwera | [login-panel.png](https://github.com/agatav13/aster/blob/main/docs/assets/wireframes/lo-fi/login-panel.png) |
| 3 | Zatwierdzić | Klika **Utwórz konto** | Tworzony użytkownik z `is_active=False`, wysyłany e-mail aktywacyjny, redirect na `/auth/activation-sent/` | — |
| 4 | Aktywować konto | Klika link w mailu (`/auth/activate/<uid>/<token>/`) | Token weryfikowany, `is_active=True`, `is_email_verified=True`, ekran potwierdzenia | — |
| 5 | Zalogować się | Otwiera `/auth/login/`, wpisuje e-mail i hasło, klika **Zaloguj się** | `authenticate()` zwraca usera, redirect na `/` z banerem „Zalogowano pomyślnie" | [login-panel.png](https://github.com/agatav13/aster/blob/main/docs/assets/wireframes/lo-fi/login-panel.png) |

**Weryfikacja automatyczna:** [`tests/e2e/test_register_login.py`](https://github.com/agatav13/aster/blob/main/tests/e2e/test_register_login.py)

---

## Ścieżka 2 — Przeglądanie, ocena, komentarz

**Persona:** Zalogowany użytkownik chce ocenić obejrzany film i podzielić się opinią.

| # | Cel użytkownika | Akcja | Reakcja systemu | Ekran |
|---|---|---|---|---|
| 1 | Znaleźć film | Otwiera `/movies/`, wpisuje frazę w wyszukiwarce | TMDB-search live + lokalna baza, lista pasujących pozycji | [search-results.png](https://github.com/agatav13/aster/blob/main/docs/assets/wireframes/lo-fi/search-results.png) |
| 2 | Wejść na szczegóły | Klika kafelek filmu | Ładowanie `/movies/<tmdb_id>/`, fetch szczegółów + obsady z TMDB (cache lokalny) | [film-page.png](https://github.com/agatav13/aster/blob/main/docs/assets/wireframes/lo-fi/film-page.png) |
| 3 | Wystawić ocenę | Klika **Oceń film** → modal → wybiera 4★ → klika **Zapisz** | POST `movies:update_rating` z `score=4.0`. Średnia i licznik filmu odświeżone | [rating-page.png](https://github.com/agatav13/aster/blob/main/docs/assets/wireframes/lo-fi/rating-page.png) |
| 4 | Skomentować | W sekcji „Komentarze" wpisuje treść, klika **Wyślij** | POST `movies:create_comment`, komentarz pojawia się na liście jako pierwszy | [film-page.png](https://github.com/agatav13/aster/blob/main/docs/assets/wireframes/lo-fi/film-page.png) |

**Weryfikacja automatyczna:** [`tests/e2e/test_browse_rate_comment.py`](https://github.com/agatav13/aster/blob/main/tests/e2e/test_browse_rate_comment.py)

---

## Ścieżka 3 — Lista „do obejrzenia" i „obejrzane"

**Persona:** Użytkownik buduje własną historię oglądania.

| # | Cel użytkownika | Akcja | Reakcja systemu | Ekran |
|---|---|---|---|---|
| 1 | Zaplanować film | Na `/movies/<id>/` klika **Obejrzyj później** | Powstaje wpis `UserMovieStatus(status='watchlist')`, przycisk zmienia podpis na „Na liście „do obejrzenia"" i `aria-pressed=true` | [film-page.png](https://github.com/agatav13/aster/blob/main/docs/assets/wireframes/lo-fi/film-page.png) |
| 2 | Oznaczyć jako obejrzane | Po seansie klika **Dodaj do obejrzanych** | Ten sam wiersz `UserMovieStatus` zmienia `status` na `'watched'` (UPDATE, nie INSERT). Przycisk pokazuje stan aktywny | [film-page.png](https://github.com/agatav13/aster/blob/main/docs/assets/wireframes/lo-fi/film-page.png) |
| 3 | Sprawdzić własne oceny | Otwiera profil → „Moje oceny" *(roadmapa)* | Lista filmów z wystawionymi ocenami i statusami | [user-ratings.png](https://github.com/agatav13/aster/blob/main/docs/assets/wireframes/lo-fi/user-ratings.png) |

**Weryfikacja automatyczna:** [`tests/e2e/test_watchlist.py`](https://github.com/agatav13/aster/blob/main/tests/e2e/test_watchlist.py)

---

## Wnioski projektowe

- **Wszystkie trzy ścieżki happy-path mają test E2E.** Regresja w jednej zostaje wychwycona w CI (`.github/workflows/e2e.yml`) zanim trafi na produkcję.
- **Statusy `watchlist` / `watched`** modelowane jednym wierszem ułatwiają przejście (UPDATE zamiast DELETE+INSERT) i upraszczają zapytania.
