# Filmowa aplikacja - etap autoryzacji

## Wymagania

- Python 3.13
- uv

## Uruchomienie

1. Utwórz `.env` na podstawie `.env.example`.
2. Uzupełnij dane SMTP prawdziwym kontem pocztowym.
3. Zsynchronizuj środowisko przez `uv`:

```powershell
uv sync --python 3.13
```

4. Wykonaj migracje:

```powershell
uv run manage.py migrate
```

Ta komenda tworzy tabele w lokalnej bazie SQLite. W praktyce uruchamiasz ją po pierwszym pobraniu projektu i po każdej zmianie w modelach bazy.

5. Uruchom serwer:

```powershell
uv run manage.py runserver
```

6. Otwórz `http://127.0.0.1:8000/`.

## Testy

```powershell
uv run manage.py test
```

## Przydatne komendy

```powershell
uv run manage.py createsuperuser
uv run manage.py makemigrations
```

## Baza danych

Projekt działa wyłącznie na lokalnym SQLite i tworzy plik `db.sqlite3` w katalogu głównym.
