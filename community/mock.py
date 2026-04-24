"""Mock data for the community preview.

The community features (feed, followers, curated lists) are not yet
backed by real models. This module fabricates realistic-looking data by
pairing real cached movies with fictional users, so the UI can be
designed and reviewed end-to-end before the backing models land.

Seeded by user id so a given user sees a stable feed across requests.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from decimal import Decimal

from movies.models import Movie

FAKE_USERS: list[dict[str, str]] = [
    {"name": "Ania Nowak", "initials": "AN", "tint": "rose"},
    {"name": "Marek Kowalski", "initials": "MK", "tint": "lavender"},
    {"name": "Kasia Wiśniewska", "initials": "KW", "tint": "peach"},
    {"name": "Tomek Lewandowski", "initials": "TL", "tint": "rose"},
    {"name": "Ola Zielińska", "initials": "OZ", "tint": "lavender"},
    {"name": "Piotr Dąbrowski", "initials": "PD", "tint": "peach"},
    {"name": "Natalia Krawczyk", "initials": "NK", "tint": "rose"},
    {"name": "Jakub Szymański", "initials": "JS", "tint": "lavender"},
]


ACTIVITY_VERBS: list[tuple[str, str]] = [
    ("rated", "oceniła film"),
    ("rated", "ocenił film"),
    ("watched", "obejrzała"),
    ("watched", "obejrzał"),
    ("watchlist", "dodała do listy do obejrzenia"),
    ("watchlist", "dodał do listy do obejrzenia"),
    ("commented", "skomentowała"),
    ("commented", "skomentował"),
]

COMMENT_SNIPPETS: list[str] = [
    "Najlepszy film roku, oglądałam bez słowa.",
    "Scenariusz drga, ale zdjęcia ratują całość.",
    "Trzeci seans i wciąż odkrywam nowe detale.",
    "Muzyka robi połowę roboty, zapada w pamięć.",
    "Nie spełnia oczekiwań, ale warto zobaczyć raz.",
    "Reżyseria wręcz wirtuozerska, bez kompromisów.",
]


@dataclass
class FeedItem:
    user_name: str
    user_initials: str
    user_tint: str  # "rose" | "lavender" | "peach"
    verb_key: str  # "rated" | "watched" | "watchlist" | "commented"
    verb_label: str
    movie: Movie
    score: Decimal | None
    snippet: str | None
    when_label: str  # "2h temu", "wczoraj", ...


@dataclass
class FakePerson:
    name: str
    initials: str
    tint: str
    handle: str
    bio: str
    shared_genres: list[str]
    shared_movies: int
    is_following: bool


@dataclass
class FakeList:
    title: str
    author_name: str
    author_initials: str
    author_tint: str
    description: str
    movie_count: int
    cover_movies: list[Movie]  # up to 4 for mosaic


def _rng_for(user_id: int, salt: str) -> random.Random:
    """Deterministic RNG per user so the mockup feels stable."""
    return random.Random(f"{user_id}:{salt}")


def _relative_when(offset_minutes: int) -> str:
    if offset_minutes < 60:
        return f"{offset_minutes} min temu"
    hours = offset_minutes // 60
    if hours < 24:
        return f"{hours} godz. temu"
    days = hours // 24
    if days == 1:
        return "wczoraj"
    if days < 7:
        return f"{days} dni temu"
    weeks = days // 7
    return f"{weeks} tyg. temu"


def build_feed(*, user_id: int, limit: int = 18) -> list[FeedItem]:
    rng = _rng_for(user_id, "feed")
    movies = list(Movie.objects.order_by("-popularity", "-id")[:80])
    if not movies:
        return []

    picks = rng.sample(movies, k=min(limit, len(movies)))
    items: list[FeedItem] = []
    offset = 15
    for movie in picks:
        user = rng.choice(FAKE_USERS)
        verb_key, verb_label = rng.choice(ACTIVITY_VERBS)
        score: Decimal | None = None
        snippet: str | None = None
        if verb_key == "rated":
            score = Decimal(str(rng.choice([3.0, 3.5, 4.0, 4.5, 5.0])))
        elif verb_key == "commented":
            snippet = rng.choice(COMMENT_SNIPPETS)

        offset += rng.randint(20, 240)
        when_label = _relative_when(offset)

        items.append(
            FeedItem(
                user_name=user["name"],
                user_initials=user["initials"],
                user_tint=user["tint"],
                verb_key=verb_key,
                verb_label=verb_label,
                movie=movie,
                score=score,
                snippet=snippet,
                when_label=when_label,
            )
        )
    return items


def build_people(*, user_id: int) -> dict[str, list[FakePerson]]:
    rng = _rng_for(user_id, "people")
    bios = [
        "Kino polskie i wszystko co z nim związane.",
        "Od Tarkowskiego po Denisa Villeneuve.",
        "Fanka horrorów A24, seriali i letnich premier.",
        "Zbieram listy. Dużo list. Za dużo list.",
        "Kino to rozmowa — komentuję dużo, oglądam jeszcze więcej.",
        "Spokojnie. Dwa filmy tygodniowo i kawa.",
        "Reżyseria autorska, kino europejskie, festiwale.",
        "Noc Muzealna mojego życia to sci-fi lat 70.",
    ]
    genres = [
        ["Dramat", "Romans"],
        ["Sci-Fi", "Thriller"],
        ["Horror", "Tajemnica"],
        ["Komedia", "Dramat"],
        ["Kryminał", "Thriller"],
        ["Animacja", "Familijny"],
        ["Historyczny", "Dramat"],
        ["Fantasy", "Przygodowy"],
    ]
    handles = [
        "@ania.n",
        "@marek_k",
        "@kasia.cinefilka",
        "@tomek.l",
        "@olaz",
        "@piotrd",
        "@natalia.k",
        "@jakub.s",
    ]

    shuffled = list(range(len(FAKE_USERS)))
    rng.shuffle(shuffled)

    friends: list[FakePerson] = []
    for idx in shuffled[:4]:
        u = FAKE_USERS[idx]
        friends.append(
            FakePerson(
                name=u["name"],
                initials=u["initials"],
                tint=u["tint"],
                handle=handles[idx],
                bio=bios[idx],
                shared_genres=genres[idx],
                shared_movies=rng.randint(12, 142),
                is_following=True,
            )
        )

    suggestions: list[FakePerson] = []
    for idx in shuffled[4:]:
        u = FAKE_USERS[idx]
        suggestions.append(
            FakePerson(
                name=u["name"],
                initials=u["initials"],
                tint=u["tint"],
                handle=handles[idx],
                bio=bios[idx],
                shared_genres=genres[idx],
                shared_movies=rng.randint(3, 38),
                is_following=False,
            )
        )

    return {"friends": friends, "suggestions": suggestions}


def build_lists(*, user_id: int) -> list[FakeList]:
    rng = _rng_for(user_id, "lists")
    movies = list(Movie.objects.order_by("-popularity", "-id")[:40])
    if not movies:
        return []

    presets = [
        (
            "Top 10 kultowych horrorów",
            "Ania Nowak",
            "AN",
            "rose",
            "Klasyki, które wciąż odbierają sen. Bez kompromisów.",
        ),
        (
            "Filmy na deszczowe niedziele",
            "Kasia Wiśniewska",
            "KW",
            "peach",
            "Ciepłe, wolne, dobrze zrobione. Do herbaty i koca.",
        ),
        (
            "Polska Szkoła Filmowa",
            "Marek Kowalski",
            "MK",
            "lavender",
            "Od Wajdy do Holland — fundament kina w Polsce.",
        ),
        (
            "Sci-Fi lat 70-tych",
            "Jakub Szymański",
            "JS",
            "lavender",
            "Analogowa fantastyka, gdy efekty były rzemiosłem.",
        ),
        (
            "A24 — pełna dyskografia",
            "Natalia Krawczyk",
            "NK",
            "rose",
            "Każda premiera studia A24 warta uwagi.",
        ),
        (
            "Oscar 2025: wszyscy nominowani",
            "Tomek Lewandowski",
            "TL",
            "rose",
            "Kompletna lista — best picture, reżyseria, scenariusz.",
        ),
    ]

    out: list[FakeList] = []
    for title, author, initials, tint, desc in presets:
        count = rng.randint(8, 48)
        covers = rng.sample(movies, k=min(4, len(movies)))
        out.append(
            FakeList(
                title=title,
                author_name=author,
                author_initials=initials,
                author_tint=tint,
                description=desc,
                movie_count=count,
                cover_movies=covers,
            )
        )
    return out
