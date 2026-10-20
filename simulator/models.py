"""Data model for synthetic football matches.

Coordinates use a 105 x 68 metre pitch. The home team always attacks
towards x = 105 and the away team towards x = 0, in both halves, so
consumers never have to flip coordinates at half time.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

PITCH_LENGTH = 105.0
PITCH_WIDTH = 68.0


@dataclass(frozen=True)
class Player:
    id: str
    name: str
    number: int
    position: str  # GK, DF, MF, FW
    pace: float  # top sprint speed in km/h
    passing: float  # 0..1
    finishing: float  # 0..1
    tackling: float  # 0..1


@dataclass(frozen=True)
class Tactics:
    """How a team plays. All values are 0..1."""

    press_intensity: float
    tempo: float
    directness: float
    width: float


@dataclass(frozen=True)
class Team:
    id: str
    name: str
    short_name: str
    colors: tuple[str, str]
    formation: str
    tactics: Tactics
    players: tuple[Player, ...]

    def by_position(self, position: str) -> list[Player]:
        return [p for p in self.players if p.position == position]


@dataclass
class Event:
    """One match event. Serialised as one JSON line per event."""

    match_id: str
    event_id: int
    t: float  # elapsed playing seconds since kick-off; monotonic across halves
    period: int
    minute: int  # match clock; second half starts at 45:00
    second: int
    type: str
    team_id: str
    player_id: str | None = None
    x: float | None = None
    y: float | None = None
    end_x: float | None = None
    end_y: float | None = None
    outcome: str | None = None
    related_player_id: str | None = None
    metrics: dict[str, Any] = field(default_factory=dict)
    score: tuple[int, int] = (0, 0)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["score"] = {"home": self.score[0], "away": self.score[1]}
        return {k: v for k, v in d.items() if v is not None and v != {}}
