# Historia wersji

## Gdzie szukać

Pełna lista zmian żyje w pliku [`CHANGELOG.md`](https://github.com/agatav13/aster/blob/main/CHANGELOG.md)
w korzeniu repozytorium. Pełni rolę pojedynczego źródła prawdy o tym,
co zostało dodane, zmienione, usunięte lub naprawione w każdym wydaniu.

## Konwencje

### Format wpisów — Keep a Changelog

Każda nowa wersja dostaje własną sekcję z datą wydania i pogrupowanymi
zmianami zgodnie z formatem [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/):

| Grupa | Co zawiera |
|---|---|
| **Added** | Nowe funkcjonalności |
| **Changed** | Zmiany w istniejącej funkcjonalności |
| **Deprecated** | Funkcje, które zostaną usunięte w przyszłej wersji |
| **Removed** | Usunięte funkcjonalności |
| **Fixed** | Naprawione błędy |
| **Security** | Łatki bezpieczeństwa |

Sekcja `[Unreleased]` na górze pliku zbiera zmiany po ostatnim wydaniu —
zostaje przemianowana na konkretną wersję w momencie release.

### Numeracja wersji — Semantic Versioning

Aplikacja stosuje [Semantic Versioning 2.0.0](https://semver.org/spec/v2.0.0.html)
w formacie `MAJOR.MINOR.PATCH`:

| Przyrost | Kiedy |
|---|---|
| `MAJOR` (X.0.0) | Niezgodne wstecz zmiany API/UI/DB |
| `MINOR` (0.X.0) | Nowe funkcjonalności kompatybilne wstecz |
| `PATCH` (0.0.X) | Naprawy błędów kompatybilne wstecz |

Wersja jest deklarowana w `pyproject.toml` (pole `version`) i tagowana
w gicie jako `vX.Y.Z`.

### Powiązanie commitów z wpisami

Repozytorium używa konwencji [Conventional Commits](https://www.conventionalcommits.org/):
prefiksy `feat:`, `fix:`, `refactor:`, `chore:`, `test:`, `docs:`,
`security:` ułatwiają mapowanie commitów na sekcje changeloga przy
wydaniu.

## Plan wsparcia

Projekt utrzymywany w ramach przedmiotu *Programowanie aplikacji
webowych*. Zgłoszenia błędów i propozycje funkcjonalności są
przyjmowane przez [GitHub Issues](https://github.com/agatav13/aster/issues).
