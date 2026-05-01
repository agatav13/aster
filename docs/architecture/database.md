# Baza danych

Aster używa **SQLite** w środowisku developerskim oraz
**PostgreSQL**.

## Diagram ERD

```mermaid
erDiagram
    USER ||--o{ RATING : wystawia
    USER ||--o{ COMMENT : pisze
    USER ||--o{ USER_MOVIE_STATUS : oznacza
    USER }o--o{ GENRE : "ulubione (m2m)"
    USER ||--o{ FOLLOW : "obserwuje (jako follower)"
    USER ||--o{ FOLLOW : "obserwowany (jako followee)"

    MOVIE ||--o{ RATING : ocena
    MOVIE ||--o{ COMMENT : komentowany
    MOVIE ||--o{ USER_MOVIE_STATUS : status
    MOVIE }o--o{ GENRE : klasyfikacja
    MOVIE ||--o{ MOVIE_CREDIT : "obsada/reżyseria"
    PERSON ||--o{ MOVIE_CREDIT : występuje

    USER {
        bigint id PK
        string email UK
        string display_name
        boolean is_active
        boolean is_email_verified
        boolean is_staff
        boolean is_superuser
        string password
        datetime created_at
        datetime updated_at
        datetime last_login
    }
    GENRE {
        bigint id PK
        string name UK
        int tmdb_id UK "nullable"
    }
    MOVIE {
        bigint id PK
        int tmdb_id UK
        string title
        string original_title
        text overview
        date release_date
        int runtime_minutes
        string poster_url
        string backdrop_url
        string original_language
        decimal average_rating
        int ratings_count
        decimal popularity
        datetime tmdb_synced_at
        datetime created_at
        datetime updated_at
    }
    RATING {
        bigint id PK
        bigint user_id FK
        bigint movie_id FK
        decimal score "0.5–5.0 step 0.5"
        datetime created_at
        datetime updated_at
    }
    USER_MOVIE_STATUS {
        bigint id PK
        bigint user_id FK
        bigint movie_id FK
        string status "watchlist | watched"
        datetime created_at
        datetime updated_at
    }
    COMMENT {
        bigint id PK
        bigint user_id FK
        bigint movie_id FK
        text content
        string status "visible | flagged | hidden | deleted"
        decimal toxicity_score
        datetime created_at
        datetime updated_at
        datetime moderated_at
    }
    PERSON {
        bigint id PK
        int tmdb_id UK
        string name
        string profile_url
    }
    MOVIE_CREDIT {
        bigint id PK
        bigint movie_id FK
        bigint person_id FK
        string credit_type "cast | director"
        string character
        int order
    }
    FOLLOW {
        bigint id PK
        bigint follower_id FK
        bigint followee_id FK
        datetime created_at
    }
```

## Tabele

### `accounts_user`

| Kolumna | Typ | Uwagi |
|---|---|---|
| `id` | bigint PK | |
| `email` | varchar UNIQUE | login + identyfikator |
| `display_name` | varchar(120) | opcjonalna nazwa wyświetlana |
| `is_active` | bool | `False` do momentu aktywacji e-maila |
| `is_email_verified` | bool | redundantna z `is_active`, użyteczna w przyszłej moderacji |
| `is_staff`, `is_superuser` | bool | dostęp do `/admin/` |
| `password` | varchar | hash PBKDF2 |
| `created_at`, `updated_at` | datetime | audyt |

### `accounts_genre`

> **Uwaga historyczna:** model `Genre` został przeniesiony z `accounts`
> do `movies` w migracji `accounts/0003_relocate_genre_to_movies.py`,
> ale tabela zachowała nazwę `accounts_genre` (`db_table` w meta) by
> uniknąć zbędnego RENAME.

| Kolumna | Typ | Uwagi |
|---|---|---|
| `id` | bigint PK | |
| `name` | varchar(50) UNIQUE | polska nazwa gatunku |
| `tmdb_id` | int UNIQUE NULL | identyfikator z TMDB; `NULL` = lokalny gatunek |

### `movies_movie`

Główna tabela katalogowa. Zsynchronizowana z TMDB przez `tmdb_id`.

| Kolumna | Typ | Uwagi |
|---|---|---|
| `id` | bigint PK | |
| `tmdb_id` | int UNIQUE | identyfikator z TMDB |
| `title`, `original_title` | varchar(255) | |
| `overview` | text | |
| `release_date` | date | nullable |
| `runtime_minutes` | int | nullable |
| `poster_url`, `backdrop_url` | varchar(500) | URL-e CDN TMDB |
| `original_language` | varchar(10) | ISO-639-1 |
| **`average_rating`** | decimal(3,2) | **cache** średniej z `ratings` |
| **`ratings_count`** | int | **cache** liczby ratingów |
| `popularity` | decimal(10,2) | z TMDB |
| `tmdb_synced_at` | datetime | ostatnia synchronizacja |
| `created_at`, `updated_at` | datetime | |

### `movies_rating`

Ocena użytkownika. Półgwiazdkowa precyzja.

| Kolumna | Typ | Uwagi |
|---|---|---|
| `id` | bigint PK | |
| `user_id` | bigint FK → user | ON DELETE CASCADE |
| `movie_id` | bigint FK → movie | ON DELETE CASCADE |
| `score` | decimal(2,1) | 0,5 ≤ score ≤ 5,0; krok 0,5 |
| `created_at`, `updated_at` | datetime | |

- **`UniqueConstraint(user, movie)`** — jedna ocena na film na użytkownika.
- **`CheckConstraint`** — score między 0,5 a 5,0 (krok pilnowany przez walidator formularza, nie przez DB).

### `movies_usermoviestatus`

Lista „do obejrzenia" / „obejrzane" w jednej tabeli. Pole `status`
przełącza stan.

| Kolumna | Typ | Uwagi |
|---|---|---|
| `id` | bigint PK | |
| `user_id` | bigint FK → user | |
| `movie_id` | bigint FK → movie | |
| `status` | varchar(20) | `'watchlist'` lub `'watched'` |

- **`UniqueConstraint(user, movie)`** — jeden status na film na użytkownika; przejście `watchlist` → `watched` to UPDATE.

### `movies_comment`

Komentarze pod filmem. Pola `toxicity_score` i statusy
`flagged`/`hidden` są przygotowane na przyszłą wersję.

| Kolumna | Typ | Uwagi |
|---|---|---|
| `id` | bigint PK | |
| `user_id` | bigint FK → user | |
| `movie_id` | bigint FK → movie | |
| `content` | text(2000) | |
| `status` | varchar(20) | `visible` / `flagged` / `hidden` / `deleted` |
| `toxicity_score` | decimal(5,4) | nullable (rezerwacja na ver_2) |
| `created_at`, `updated_at` | datetime | |
| `moderated_at` | datetime | nullable |

### `movies_person` i `movies_moviecredit`

Obsada i reżyseria z TMDB.

`movies_person` — jedna osoba (aktor lub reżyser).

| Kolumna | Typ | Uwagi |
|---|---|---|
| `tmdb_id` | int UNIQUE | |
| `name` | varchar(255) | |
| `profile_url` | varchar(500) | URL zdjęcia z TMDB |

`movies_moviecredit` — łącznik m2m z dodatkowymi atrybutami.

| Kolumna | Typ | Uwagi |
|---|---|---|
| `movie_id` | bigint FK | |
| `person_id` | bigint FK | |
| `credit_type` | varchar(20) | `cast` lub `director` |
| `character` | varchar(255) | tylko dla cast |
| `order` | int | kolejność na liście |

- **`UniqueConstraint(movie, person, credit_type)`** — bez duplikatów.

### `community_follow`

Relacja „follower → followee" zasilająca feed znajomych w
[`community/services.build_feed_groups`](https://github.com/agatav13/aster/blob/main/community/services.py).

| Kolumna | Typ | Uwagi |
|---|---|---|
| `id` | bigint PK | |
| `follower_id` | bigint FK → user | obserwujący; ON DELETE CASCADE |
| `followee_id` | bigint FK → user | obserwowany; ON DELETE CASCADE |
| `created_at` | datetime | używane do sortowania w listingu „znajomi" |

- **`UniqueConstraint(follower, followee)`** (`uq_follow_pair`) — jedna relacja na parę.
- **`CheckConstraint(follower != followee)`** (`ck_follow_not_self`) — blokuje self-follow.
- Indeksy `(follower, -created_at)` i `(followee, -created_at)` — wspierają zapytania feedu („kogo obserwuję") i listy followers (panel profilu publicznego).
