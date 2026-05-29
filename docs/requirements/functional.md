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
- **Przebieg:** formularz pod sekcją „Komentarze". Treść (≤ 2000 znaków) zapisywana z `status=visible`. Tylko autor komentarza może go usunąć.
- **Moderacja społecznościowa:** każdy zalogowany użytkownik może zgłosić cudzy komentarz — zob. [UC-11](#uc-11-zglaszanie-komentarza). Po przekroczeniu progu zgłoszeń komentarz automatycznie zmienia status na `flagged` i znika z listy publicznej (filtr `visible_comments_for`) do czasu decyzji moderatora (zob. [UC-10](#uc-10-administracja-danymi)).
- **Roadmapa:** automatyczne ocenianie toksyczności (`toxicity_score`) — pole istnieje w modelu, ale nie jest jeszcze zasilane przez klasyfikator; obecnie zgłoszenia są w pełni społecznościowe.

### UC-09 Edycja profilu

- **Aktor:** Użytkownik
- **Przebieg:** zmiana nazwy wyświetlanej (`/auth/display-name/`) lub ulubionych gatunków (`/auth/genres/`).

### UC-10 Administracja danymi

- **Aktor:** Administrator
- **Przebieg:** logowanie do panelu Django pod `<DJANGO_ADMIN_URL>` (domyślnie `/admin/`). Możliwe operacje: dezaktywacja użytkowników, moderacja komentarzy, edycja gatunków, ręczna synchronizacja z TMDB.
- **Moderacja komentarzy:** lista komentarzy pokazuje licznik zgłoszeń i inline ze zgłoszeniami (`CommentReport`). Komentarze automatycznie oznaczone jako `flagged` (zob. [UC-11](#uc-11-zglaszanie-komentarza)) czekają na decyzję. Dwie akcje masowe: **Ukryj** (→ `hidden`) i **Przywróć** (→ `visible`, czyści zgłoszenia komentarza). Osobny widok `CommentReport` pozwala przeglądać same zgłoszenia.

### UC-11 Zgłaszanie komentarza {#uc-11-zglaszanie-komentarza}

- **Aktor:** Użytkownik
- **Cel:** Zgłosić cudzy komentarz łamiący zasady społeczności.
- **Przebieg główny:**
    1. Przy komentarzu innego użytkownika rozwija kontrolkę **„Zgłoś"**.
    2. Wybiera powód: spam / treść obraźliwa / spoiler / inne (albo **„Anuluj"**, by zwinąć formularz).
    3. System zapisuje wiersz `CommentReport` — jedno zgłoszenie na parę `(komentarz, zgłaszający)` (`uq_comment_report_pair`) — i pokazuje marker **„Zgłoszono"**, by uniemożliwić ponowne zgłoszenie.
- **Reguła automatyczna:** gdy `Comment.REPORTS_TO_FLAG` (domyślnie **3**) różnych użytkowników zgłosi wciąż widoczny komentarz, jego status zmienia się automatycznie z `visible` na `flagged` i komentarz znika z listy publicznej do czasu przeglądu przez moderatora.
- **Warunki brzegowe:** nie można zgłosić własnego komentarza; pojedyncze zgłoszenie nie ukrywa komentarza natychmiast — dopiero przekroczenie progu.

### UC-12 Prywatny dziennik filmowy {#uc-12-prywatny-dziennik-filmowy}

- **Aktor:** Użytkownik
- **Cel:** Prowadzić prywatne, widoczne tylko dla siebie notatki o filmach — prywatny odpowiednik publicznych komentarzy.
- **Przebieg główny:**
    1. Na stronie filmu, w sekcji **„Prywatny dziennik"** (renderowanej wyłącznie dla zalogowanych), wpisuje notatkę (≤ 2000 znaków) i zapisuje.
    2. Własne notatki do tego filmu wyświetlają się od najnowszej; autor może każdą usunąć.
    3. Pod `/auth/journal/` (**„Mój dziennik"**, link w menu konta) widzi wszystkie swoje notatki ze wszystkich filmów jako chronologiczną oś czasu z miniaturami plakatów.
- **Reguła:** `MovieNote` celowo **nie** ma ograniczenia unikalności `(user, movie)` — użytkownik może mieć wiele wpisów na ten sam film (dziennik, nie pojedyncze edytowalne pole). Notatki nigdy nie są widoczne publicznie ani dla innych użytkowników.

## Historie użytkownika (user stories)

Historie odpowiadają ścieżkom opisanym szczegółowo w
[Ścieżkach użytkownika](../ux/user-journeys.md) — każda historia kończy się
linkiem do testu, który ją weryfikuje (E2E tam, gdzie istnieje pełna ścieżka
przeglądarkowa, w pozostałych przypadkach test jednostkowy/integracyjny).

| ID | Jako… | chcę… | aby… | Test |
|---|---|---|---|---|
| US-01 | gość | założyć konto i aktywować je linkiem z e-maila | móc oceniać filmy | `tests/e2e/test_register_login.py` |
| US-02 | użytkownik | przeglądać szczegóły filmu, ocenić go i napisać komentarz | dzielić się opinią | `tests/e2e/test_browse_rate_comment.py` |
| US-03 | użytkownik | dodać film do listy „do obejrzenia", a potem do „obejrzanych" | śledzić własną historię oglądania | `tests/e2e/test_watchlist.py` |
| US-04 | użytkownik | zresetować hasło przez link e-mail | odzyskać dostęp do konta | `accounts/tests.py::test_password_reset_sends_email`, `…::test_password_reset_confirm_changes_password` |
| US-05 | użytkownik | zgłosić obraźliwy komentarz | utrzymać higienę dyskusji | `movies/tests.py::test_report_creates_row_with_reason`, `…::test_comment_auto_flags_at_threshold` |
| US-06 | administrator | ukryć / przywrócić zgłoszony komentarz | egzekwować decyzje moderacyjne | `movies/tests.py::test_visible_comments_filters_out_non_visible` (+ panel Django) |
| US-07 | użytkownik | prowadzić prywatny dziennik filmowy | notować przemyślenia tylko dla siebie | `movies/tests.py::test_journal_lists_user_notes`, `…::test_detail_page_shows_only_own_notes` |

## Reguły biznesowe

- E-mail jest jedynym identyfikatorem konta (`USERNAME_FIELD = "email"`).
- Konto bez aktywacji nie może się zalogować (`is_active=False`).
- Każdy użytkownik wystawia **co najwyżej jedną** ocenę na film (`UniqueConstraint` `uq_user_movie_rating`).
- Każdy użytkownik ma **co najwyżej jeden** wpis statusu na film (`uq_user_movie_status`); zmiana z „watchlist" na „watched" to UPDATE tego samego wiersza.
- Każdy użytkownik może zgłosić dany komentarz **co najwyżej raz** (`uq_comment_report_pair`); po `Comment.REPORTS_TO_FLAG` (domyślnie 3) zgłoszeniach od różnych użytkowników komentarz automatycznie przechodzi w status `flagged`.
- `MovieNote` **nie** ma ograniczenia unikalności `(user, movie)` — użytkownik może mieć wiele notatek na ten sam film; notatki są prywatne (zawsze filtrowane po właścicielu, brak zapytań „widoczne publicznie").
