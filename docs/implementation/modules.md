# Moduły, algorytmy i wzorce projektowe

Sekcja przechodzi przez **siedem kluczowych ścieżek kodu**, które
najlepiej wyjaśniają architekturę aplikacji. Pełny kod żyje w
repozytorium — tu pokazujemy wzorce i decyzje.

## Struktura projektu

```
config/          — settings.py, urls.py, wsgi.py
accounts/        — User, formularze auth, e-maile aktywacyjne, profil + ustawienia
core/            — editorial landing dla anonimów + dashboard (community shelf + watchlist + feed znajomych)
movies/          — katalog, oceny, komentarze, statusy, integracja TMDB, shelves
community/       — Follow model, feed znajomych, profile publiczne
feedback/        — widget zgłoszeń przekierowujący do GitHub Issues
templates/       — wszystkie szablony DTL (auth, movies, community, partials, e-maile)
static/          — CSS, JS, ikony
tests/           — e2e/ (Playwright), perf/ (locust)
```

> **Uwaga o `community/`:** aplikacja ma własny model `Follow`
> (migracja `community/0001_initial.py`) i serwis
> [`build_feed_groups`](https://github.com/agatav13/aster/blob/main/community/services.py),
> który łączy `Rating` i `UserMovieStatus` obserwowanych użytkowników w
> deduplikowany feed pogrupowany po datach. Widoki: `FeedView`
> (`/community/`), `PeopleView` (`/community/people/`),
> `UserProfileView` (`/community/u/<id>/` — read-only profil publiczny)
> oraz `follow_toggle` (POST). Plik `community/mock.py` został
> ograniczony do dataclass’ów `FeedItem` / `FeedGroup` używanych przez
> serwis i szablony.

## 1. Rejestracja z weryfikacją e-mail — `accounts/views.py:RegisterView`

Wzorzec: **Form + post-save side effect** w `form_valid`.

```python
class RegisterView(FormView):
    template_name = "accounts/register.html"
    form_class = RegisterForm
    success_url = reverse_lazy("accounts:activation_sent")

    def form_valid(self, form):
        user = form.save()  # is_active=False
        try:
            send_activation_email(user)
            messages.success(self.request, "Konto zostało utworzone...")
        except Exception:
            logger.exception(...)
            messages.warning(self.request, "Wysyłka e-maila się nie powiodła...")
        return super().form_valid(form)
```

Decyzja: **wysyłka maila NIE jest atomiczna z zapisem usera**. Jeżeli
SMTP padnie, konto powstaje, użytkownik dostaje komunikat ostrzegawczy
i może użyć `/auth/resend-activation/`.

## 2. Generowanie i weryfikacja tokenu aktywacyjnego — `accounts/utils.py`, `views.ActivateAccountView`

Wzorzec: **stateless token** Django (`default_token_generator`). Brak
osobnej tabeli `ActivationToken` — token deterministycznie generowany z
kombinacji `user.pk + user.password + last_login + timestamp`.

```python
def send_activation_email(user: User) -> None:
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    activation_path = reverse("accounts:activate", kwargs={"uidb64": uid, "token": token})
    activation_url = f"{settings.APP_BASE_URL}{activation_path}"
    ...
```

Token unieważnia się po pierwszej zmianie hasła (zmienia się hash) i
po `PASSWORD_RESET_TIMEOUT` (24 h).

## 3. Model danych — `movies/models.py`

Najistotniejsze decyzje:

- **`UserMovieStatus`** zamiast osobnych tabel watchlist/watched. Pole `status` przełącza stan, `UniqueConstraint(user, movie)` blokuje duplikaty.
- **`Rating.score` jako `DecimalField(max_digits=2, decimal_places=1)`** + `MinValueValidator(0.5)` + `MaxValueValidator(5.0)` + `CheckConstraint`. Krok 0,5 pilnowany przez walidator formularza.
- **Cache aggregates** — `Movie.average_rating` i `Movie.ratings_count` aktualizowane w warstwie serwisowej, NIE przez signals. Świadoma decyzja: signals są niewidoczne i utrudniają testowanie.
- **`Comment.toxicity_score` + `STATUS_CHOICES` z `flagged`/`hidden`** — schemat gotowy, widok publiczny już teraz filtruje na `status='visible'`.
- **`MovieCredit` jako through-table m2m** Person↔Movie z dodatkowymi atrybutami (`credit_type`, `character`, `order`). Indeks `(movie, credit_type, order)` daje od razu posortowaną obsadę bez sortowania w Pythonie.

## 4. Service layer — `movies/services.py` (ok. 1000 linii)

Wzorzec: **Service layer / Application service**. Views są cienkie, serwisy zawierają:

- **Transakcyjność** — operacje wieloetapowe (`upsert_rating`, `set_movie_status`, `delete_own_comment`) opakowane w `transaction.atomic`.
- **Cache-first dla TMDB** — `fetch_and_cache_movie(tmdb_id)` zagląda najpierw do bazy, potem do TMDB, potem zapisuje:

```python
def fetch_and_cache_movie(tmdb_id: int) -> Movie | None:
    if not (movie := Movie.objects.filter(tmdb_id=tmdb_id).first()):
        ...  # try TMDB, persist
    if _credits_stale(movie):
        backfill_credits(movie)  # MovieCredit + Person
    return movie
```

- **Refresh aggregates** po każdej operacji ratingowej:

```python
@transaction.atomic
def upsert_rating(user, movie, score: Decimal) -> Rating:
    rating, _ = Rating.objects.update_or_create(
        user=user, movie=movie, defaults={"score": score}
    )
    _refresh_movie_aggregates(movie)
    return rating

def _refresh_movie_aggregates(movie: Movie) -> None:
    aggr = movie.ratings.aggregate(avg=Avg("score"), n=Count("id"))
    Movie.objects.filter(pk=movie.pk).update(
        average_rating=aggr["avg"] or Decimal("0.00"),
        ratings_count=aggr["n"] or 0,
    )
```

- **Visible comments query** używa indeksu `(movie, status, -created_at)`:

```python
def visible_comments_for(movie: Movie) -> QuerySet[Comment]:
    return movie.comments.filter(status=Comment.VISIBLE).select_related("user").order_by("-created_at")
```

- **Shelves (rails na stronie `/movies/`)** — `fetch_trending_shelf`,
  `fetch_top_rated_shelf`, `fetch_genre_shelf`,
  `fetch_community_top_rated_shelf`,
  `fetch_seeded_recommendations_shelf`,
  `fetch_continue_exploring_shelf`, `fetch_polish_cinema_shelf`. Każda
  funkcja zwraca `list[MovieListItem]` (cap = `SHELF_LIMIT`) i
  **łyka błędy** (`TmdbApiError`, `TmdbConfigError`) — zwraca pustą
  listę i loguje `warning`/`debug`. Widok (`MovieListView._build_shelves`)
  filtruje puste rails na końcu, dzięki czemu nigdy nie renderuje
  zatytułowanej półki bez kafelków. Personalne rails
  („Bo oceniłeś wysoko", „Kontynuuj odkrywanie") są źródłowane z
  ratingów użytkownika i credits z `MovieCredit`; już oglądane / ocenione
  filmy są wykluczane przez `_interacted_tmdb_ids`.

## 5. Klient TMDB — `movies/tmdb.py`

Wzorzec: **Adapter** + **typed payloads** (modele Pydantic v2 — `TmdbMovieSummary`, `TmdbMovieDetail`, `TmdbCredits`).

- `httpx.Client` z timeoutem konfigurowalnym przez ENV (domyślnie 3 s — TMDB jest na ścieżce krytycznej, fallback do lokalnej bazy + pusta półka są bezpieczne).
- Centralne wyjątki: `TmdbApiError`, `TmdbConfigError` (separate config-vs-runtime errors).
- Wszystkie zapytania dodają `language=pl-PL` (lub wartość ze `settings.TMDB_LANGUAGE`).
- `append_to_response` używane do pobrania szczegółów + credits w jednym GET (`/movie/<id>?append_to_response=credits`).
- **Cache odpowiedzi:** każde GET trafia do Django cache pod kluczem `sha256(url+params)` z TTL `TMDB_RESPONSE_CACHE_TTL` (domyślnie 900 s). W produkcji backend to Redis (`REDIS_URL`), więc cache jest współdzielony między workerami Gunicorna — bez tego trafność spada do `1/N_workers` i resetuje się na każdym deploju.

## 6. Class-based vs function-based views — `movies/views.py`

Decyzja stylu: **CBV dla widoków renderujących templatkę**, **FBV dla akcji POST modyfikujących stan**.

```python
class MovieListView(TemplateView):  # renderuje listę
    template_name = "movies/list.html"
    def get_context_data(self, **kwargs): ...

@login_required
@require_POST
def update_movie_rating(request, tmdb_id: int):  # POST endpoint
    movie = get_object_or_404(Movie, tmdb_id=tmdb_id)
    ...
```

Powód: CBV dają darmowo `get_context_data`, mixiny (`LoginRequiredMixin`).
FBV są krótsze i czytelniejsze dla wąskich akcji, gdzie cały handler to
walidacja + 1 wywołanie serwisowe.

### htmx na widoku szczegółów

Akcje `update_status`, `update_rating`, `create_comment` i
`delete_comment` rozpoznają nagłówek `HX-Request`: zamiast `302` redirectu
zwracają fragment HTML (`templates/movies/_actions.html`,
`_user_rating_cell.html`, `_comments_section.html`), który htmx
podmienia w docelowym kontenerze. Dzięki temu klik „Oceń" /
„Obejrzane" / „Wyślij komentarz" nie powoduje pełnego reloadu strony.
Pełna ścieżka POST → redirect zostaje zachowana jako fallback dla
klientów bez JS.

## 7. Konfiguracja środowiskowa — `config/settings.py`

Wzorzec: **12-factor** — wszystkie różnice dev/prod sterowane zmiennymi
środowiskowymi z bezpiecznymi domyślnymi.

```python
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "change-me")
DEBUG = env_bool("DJANGO_DEBUG", True)
DATABASES = {"default": dj_database_url.config(default=None) or _SQLITE}

if not DEBUG:  # production hardening
    SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", True)
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = int(os.getenv("SECURE_HSTS_SECONDS", "31536000"))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_REFERRER_POLICY = "same-origin"
    X_FRAME_OPTIONS = "DENY"
```

Decyzja: **harden tylko gdy `DEBUG=False`**, by lokalny `runserver`
działał bez SSL.

## Komendy administracyjne

W `movies/management/commands/`:

| Komenda | Cel |
|---|---|
| `sync_tmdb_genres` | Jednorazowy import 19 kanonicznych gatunków TMDB |
| `sync_tmdb_popular --pages N` | Pobranie *N* stron popularnych filmów (po 20 sztuk) |
| `backfill_credits` | Uzupełnienie obsady i reżyserii dla istniejących filmów (gdy `Person`/`MovieCredit` zostały dodane po `Movie`) |
| `normalize_genres` | Naprawa polskich nazw gatunków (gdyby TMDB zwróciło angielskie etykiety) |

Pełna instrukcja użycia: [Podręcznik administratora](../maintenance/admin-guide.md#synchronizacja-z-tmdb).

## Wzorce projektowe — podsumowanie

| Wzorzec | Lokalizacja |
|---|---|
| **Service layer** | `movies/services.py`, `accounts/utils.py` |
| **Adapter** | `movies/tmdb.py` (Aster ↔ TMDB) |
| **Form template method** (Django) | `RegisterForm.save()`, `LoginForm.clean()` |
| **Through-table** (m2m z atrybutami) | `MovieCredit` |
| **Cache-first / lazy loading** | `fetch_and_cache_movie` |
| **Stateless token** | `default_token_generator` w aktywacji i password reset |
| **12-factor configuration** | `config/settings.py` |
| **Progressive enhancement** | toggle gatunków, modal oceny — działają bez JS w trybie minimalnym |
