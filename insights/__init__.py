"""Live match intelligence: aggregated state plus explainable moments."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Any

from .moments import Moment, MomentDetector
from .state import MatchState

__all__ = ["MatchState", "Moment", "MomentDetector", "analyze"]


def analyze(events: Iterable[dict[str, Any]]) -> Iterator[tuple[dict[str, Any], list[Moment], MatchState]]:
    """Feed events one by one; yield each event with the moments it produced."""
    state = MatchState()
    detector = MomentDetector(state)
    for e in events:
        state.ingest(e)
        yield e, detector.process(e), state
