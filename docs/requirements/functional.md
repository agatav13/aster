# Wymagania funkcjonalne

Dokument opisuje co aplikacja Aster ma robić z perspektywy
użytkownika końcowego oraz administratora. Szczegóły implementacyjne
znajdują się w sekcji [Implementacja](../implementation/modules.md).

## Aktorzy systemu

| Aktor | Opis |
|---|---|
| **Gość** | Niezalogowany użytkownik. Może utworzyć konto na platformie lub się zalogować. |
| **Użytkownik** | Zarejestrowany i aktywowany. Ocenia filmy, komentuje, zarządza listami. |
| **Administrator** | Pracownik obsługi. Ma dostęp do panelu Django i może moderować treści. |

## Przypadki użycia (use cases)

### UC-01 Rejestracja i aktywacja konta

- **Aktor:** Gość → Użytkownik
- **Cel:** Założyć konto w serwisie i aktywować je linkiem z e-maila.
- **Przebieg główny:**
    1. Gość przechodzi do `/auth/register/`.
    2. Wypełnia formularz: e-mail, opcjonalna nazwa wyświetlana, hasło (×2), wybór ulubionych gatunków.
    3. System tworzy konto z `is_active=False` i wysyła e-mail aktywacyjny.
    4. Użytkownik klika link w mailu (`/auth/activate/<uid>/<token>/`).
    5. Konto zostaje oznaczone jako aktywne i zweryfikowane.
- **Warunki brzegowe:** link aktywacyjny ważny zgodnie z `PASSWORD_RESET_TIMEOUT` (24 h). Po wygaśnięciu można go wysłać ponownie z `/auth/resend-activation/`.

### UC-02 Logowanie i wylogowanie

- **Aktor:** Użytkownik
- **Przebieg:** formularz e-mail + hasło → walidacja → przekierowanie na stronę główną (`/`). Wylogowanie tylko metodą POST z formularza w nagłówku.

### UC-03 Reset hasła

- **Aktor:** Użytkownik
- **Przebieg:** standardowy flow Django (`/auth/password-reset/...`) z e-mailem zawierającym jednorazowy token i ekranem ustawienia nowego hasła.

### UC-04 Przeglądanie katalogu filmów

- **Aktor:** Użytkownik
- **Przebieg:** `/movies/` pokazuje paginowaną listę. Domyślnie — popularne filmy z TMDB (z fallbackiem do lokalnej bazy). Filtry: zapytanie tekstowe (`?q=`), gatunek (`?genre=<id>`).

### UC-05 Szczegóły filmu

- **Aktor:** Użytkownik
- **Przebieg:** `/movies/<tmdb_id>/` pokazuje plakat, opis, gatunki, reżyserię i obsadę (z TMDB credits) oraz średnią ocenę. Akcje: ocena, status oglądania, komentarze.

### UC-06 Wystawianie i zmiana oceny

- **Aktor:** Użytkownik
- **Przebieg:** modal z 10 pozycjami (0,5 – 5,0). Zapis przez POST do `movies:update_rating`. Średnia (`movies.average_rating`) i licznik (`movies.ratings_count`) aktualizowane w warstwie serwisowej (`movies/services.py`).
- **Warianty:** zmiana istniejącej oceny, usunięcie własnej oceny.

### UC-07 Zarządzanie statusem filmu

- **Aktor:** Użytkownik
- **Przebieg:** dwa przyciski na widoku szczegółów — *Obejrzyj później* (status `watchlist`) i *Dodaj do obejrzanych* (`watched`). Tabela `UserMovieStatus` reprezentuje obie listy w jednej, zmieniając pole `status`.

### UC-08 Komentowanie filmu

- **Aktor:** Użytkownik
- **Przebieg:** formularz pod sekcją „Komentarze". Treść zapisywana z `status=visible`. Tylko autor komentarza może go usunąć.
- **Roadmapa:** moderacja z polem `toxicity_score` i statusami `flagged`/`hidden`.

### UC-09 Edycja profilu

- **Aktor:** Użytkownik
- **Przebieg:** zmiana nazwy wyświetlanej (`/auth/display-name/`) lub ulubionych gatunków (`/auth/genres/`).

### UC-10 Administracja danymi

- **Aktor:** Administrator
- **Przebieg:** logowanie do panelu Django pod `<DJANGO_ADMIN_URL>` (domyślnie `/admin/`). Możliwe operacje: dezaktywacja użytkowników, moderacja komentarzy (zmiana statusu na `hidden`), edycja gatunków, ręczna synchronizacja z TMDB.

## Historie użytkownika (user stories)

Historie odpowiadają ścieżkom opisanym szczegółowo w
[Ścieżkach użytkownika](../ux/user-journeys.md) — każda historia kończy się
linkiem do testu E2E, który ją weryfikuje.

| ID | Jako… | chcę… | aby… | Test E2E |
|---|---|---|---|---|
| US-01 | gość | założyć konto i aktywować je linkiem z e-maila | móc oceniać filmy | `tests/e2e/test_register_login.py` |
| US-02 | użytkownik | przeglądać szczegóły filmu, ocenić go i napisać komentarz | dzielić się opinią | `tests/e2e/test_browse_rate_comment.py` |
| US-03 | użytkownik | dodać film do listy „do obejrzenia", a potem do „obejrzanych" | śledzić własną historię oglądania | `tests/e2e/test_watchlist.py` |
| US-04 | użytkownik | zresetować hasło przez link e-mail | odzyskać dostęp do konta | (ręczne — patrz UC-03) |
| US-05 | administrator | ukryć obraźliwy komentarz | utrzymać higienę dyskusji | (panel Django) |

## Reguły biznesowe

- E-mail jest jedynym identyfikatorem konta (`USERNAME_FIELD = "email"`).
- Konto bez aktywacji nie może się zalogować (`is_active=False`).
- Każdy użytkownik wystawia **co najwyżej jedną** ocenę na film (`UniqueConstraint` `uq_user_movie_rating`).
- Każdy użytkownik ma **co najwyżej jeden** wpis statusu na film (`uq_user_movie_status`); zmiana z „watchlist" na „watched" to UPDATE tego samego wiersza.
