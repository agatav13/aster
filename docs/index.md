# Aster — dokumentacja techniczna i użytkownika

Aster to webowa aplikacja do **odkrywania, oceniania i porządkowania
filmów** zbudowana w Django. Dane filmowe pochodzą z publicznego API
[The Movie Database (TMDB)](https://www.themoviedb.org/), a użytkownicy
prowadzą własne listy filmów oraz wystawiają oceny
z dokładnością do pół gwiazdki.

## Szybkie linki

|  | Gdzie |
|---|---|
| Aplikacja produkcyjna | <https://aster-1lf7.onrender.com/> |
| Repozytorium | <https://github.com/agatav13/aster> |
| Dokumentacja (ten serwis) | <https://agatav13.github.io/aster/> |

## Jak czytać tę dokumentację

Dokumentacja jest podzielona zgodnie z klasycznym cyklem wytwarzania
oprogramowania:

1. [Wymagania](requirements/functional.md) — co system robi i z jakimi ograniczeniami.
2. [UX/UI](ux/sitemap.md) — jak użytkownik się porusza, jak wyglądają ekrany.
3. [Architektura](architecture/system.md) — jak system jest zbudowany i jakie dane przechowuje.
4. [Implementacja](implementation/modules.md) — kluczowe moduły, wzorce, instrukcja wdrożenia.
5. [Testy](testing/strategy.md) — strategia jakości i wygenerowane raporty.
6. [Utrzymanie](maintenance/admin-guide.md) — podręczniki administratora i użytkownika końcowego oraz historia wersji.

## Kontakt i licencja

Projekt powstał w ramach przedmiotu *Programowanie aplikacji
webowych*. Kod źródłowy udostępniony jest na licencji
[MIT](https://github.com/agatav13/aster/blob/main/LICENSE).
