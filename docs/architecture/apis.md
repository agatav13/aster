# API i integracje

Aster nie udostępnia własnego publicznego REST API. Komunikacja
z przeglądarką odbywa się klasycznie — Django renderuje HTML, akcje
modyfikujące stan to formularze POST. Sekcja opisuje:

1. **Adresy URL** wystawiane na zewnątrz (do przeglądarki).
2. **Integracje** z usługami trzecimi (TMDB, Brevo/SMTP).

## Endpointy aplikacji

Pełna mapa: [UX → Mapa serwisu](../ux/sitemap.md). Tutaj — krótki
przegląd kontraktu wybranych endpointów modyfikujących stan.

### `POST /movies/<tmdb_id>/status/`

Aktualizuje status oglądania (watchlist / watched).

| Pole formularza | Typ | Wartości | Opis |
|---|---|---|---|
| `csrfmiddlewaretoken` | string | — | wymagane |
| `action` | string | `watchlist` / `watched` | docelowy status |

Odpowiedź: `302` redirect na `/movies/<tmdb_id>/`. Komunikat w sesji.

### `POST /movies/<tmdb_id>/rating/`

Wystawia, modyfikuje lub usuwa ocenę.

| Pole | Wartości | Opis |
|---|---|---|
| `action` | `save` / `delete` | tryb |
| `score` | string „0.5" – „5.0" co 0.5 | wymagane gdy `action=save` |

### `POST /movies/<tmdb_id>/comments/`

Tworzy komentarz.

| Pole | Opis |
|---|---|
| `content` | text, max 2000 znaków |

### `POST /movies/<tmdb_id>/comments/<comment_id>/delete/`

Usuwa komentarz. Tylko autor (sprawdzane w `services.delete_own_comment`).

### `POST /community/people/<user_id>/follow/`

Toggle obserwowania innego użytkownika. Idempotentny: jeśli relacja
istnieje — usuwa, w przeciwnym razie tworzy `community.Follow`.

| Pole | Wartości | Opis |
|---|---|---|
| `csrfmiddlewaretoken` | string | wymagane |
| `next` | string (relatywny URL) | opcjonalny — ścieżka redirectu po toggle (domyślnie `community:people`) |

Walidacja: `400` przy próbie obserwowania samego siebie,
`404` gdy `user_id` nie wskazuje aktywnego konta.

## Integracja z TMDB

Klient w [`movies/tmdb.py`](https://github.com/agatav13/aster/blob/main/movies/tmdb.py)
opakowuje `httpx.Client` i wystawia metody domeny:

- **Katalog i wyszukiwanie:** `discover_popular(...)`, `search_movies`,
  `genre_list`, `list_trending(time_window)`, `list_top_rated`,
  `list_now_playing`, `list_upcoming`.
- **Szczegóły filmu:** `movie_details`, `movie_credits`,
  `get_movie_recommendations(tmdb_id)` (rekomendacje TMDB dla pojedynczego
  filmu — używane przez rail „Bo oceniłeś wysoko").
- **Filmografia osoby:** `get_person_movie_credits(person_id)` —
  agreguje cast + crew, normalizuje do `TmdbMovieSummary`, deduplikuje po
  `id`. Zasila rail „Kontynuuj odkrywanie".

Metoda `discover_popular` przyjmuje opcjonalne filtry kluczowe
(`with_genres`, `with_original_language`, `vote_count_gte`, `sort_by`),
dzięki czemu jeden punkt wejścia obsługuje zarówno listy gatunkowe, jak
i editorial-rail „Polskie kino".

- **Base URL:** `https://api.themoviedb.org/3` (zmienna `TMDB_API_BASE_URL`)
- **Authoryzacja:** klucz v3 jako parametr `api_key=` (zmienna `TMDB_API_KEY`)
- **Język:** `language=pl-PL` (zmienna `TMDB_LANGUAGE`)
- **Timeout:** 3 s domyślnie (zmienna `TMDB_REQUEST_TIMEOUT`). Tak agresywna wartość celowa: TMDB jest na ścieżce krytycznej renderu listingu, a fallback do lokalnej bazy + pusta półka są bezpieczne.
- **Cache odpowiedzi:** każde GET trafia do Django cache pod kluczem `sha256(url+params)` z TTL `TMDB_RESPONSE_CACHE_TTL` (domyślnie 900 s). W produkcji backendem jest Redis (`REDIS_URL`), więc cache jest współdzielony między workerami Gunicorna.
- **Obsługa błędów:** `TmdbApiError` (4xx/5xx, network), `TmdbConfigError` (brak klucza). Service layer łapie i zwraca puste wyniki + log warning.

### Przykład: pobranie szczegółów filmu

```python
from movies.tmdb import default_client

client = default_client()
data = client.movie_details(tmdb_id=27205, append=("credits",))
# data["title"], data["overview"], data["credits"]["cast"], data["credits"]["crew"]
```

W aplikacji zamiast bezpośredniego użycia klienta zwykle wywołujemy
funkcje serwisowe (`movies/services.py`):
`fetch_and_cache_movie(tmdb_id)`, `discover_tmdb_movies(...)`,
`search_tmdb_movies(query)`. Funkcje te realizują strategię
„cache-first": najpierw lokalna baza, w razie miss — TMDB + zapis do
bazy.

### Atrybucja TMDB

Aplikacja używa danych TMDB i **musi** wyświetlać atrybucję zgodnie z
ich regulaminem. Atrybucja znajduje się w stopce serwisu i w README.

## Integracja e-mail

Dwa backendy do wyboru, wybierane na podstawie obecności
`BREVO_API_KEY`:

| Tryb | Backend | Konfiguracja |
|---|---|---|
| Brevo (preferowane w prod) | `anymail.backends.brevo.EmailBackend` | `BREVO_API_KEY` |
| SMTP (Gmail, MailHog itp.) | `django.core.mail.backends.smtp.EmailBackend` | `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS` |

Wysyłane wiadomości:

- **Aktywacja konta** — `accounts/utils.py:send_activation_email` korzysta z szablonów `accounts/emails/activation_email.{txt,html}`.
- **Reset hasła** — wbudowany `auth_views.PasswordResetView` z polskimi szablonami `accounts/emails/password_reset_email.{txt,html}`.

`DEFAULT_FROM_EMAIL` używany jako adres nadawcy.
