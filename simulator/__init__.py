"""Synthetic, football-realistic match event simulator."""

from .engine import MatchConfig, MatchEngine, expected_goals, pass_difficulty, simulate_match
from .models import Event, Player, Tactics, Team
from .teams import TEAMS

__all__ = [
    "Event",
    "MatchConfig",
    "MatchEngine",
    "Player",
    "TEAMS",
    "Tactics",
    "Team",
    "expected_goals",
    "pass_difficulty",
    "simulate_match",
]
