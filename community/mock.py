"""Shared dataclasses for community views."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from movies.models import Movie


@dataclass
class FeedItem:
    user_id: int
    user_name: str
    movie: Movie
    score: Decimal | None  # set when the user rated the movie
    watched: bool  # set when the user has a Watched mark
    when_label: str  # relative caption inside the card ("3 godz. temu")
    timestamp: datetime  # most recent of (rating.created_at, watched.updated_at)

    @property
    def verb_label(self) -> str:
        if self.score is not None and self.watched:
            return "obejrzał(a) i ocenił(a)"
        if self.score is not None:
            return "ocenił(a) film"
        return "obejrzał(a)"


@dataclass
class FeedGroup:
    label: str  # date bucket header: "Dzisiaj", "Wczoraj", "3 dni temu", …
    items: list[FeedItem]
