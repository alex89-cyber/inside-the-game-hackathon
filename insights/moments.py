"""Detects the moments worth talking about, with the evidence behind them.

Each `Moment` carries a type, an importance score and a `why` dict of
numbers taken from `MatchState`. The explainer and narrator agents turn
that evidence into language; they never have to guess why something
mattered, because the detector already says so.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .state import MatchState

SPEED_TAG_KMH = 34.0
SHOT_SPEED_TAG_KMH = 110.0
BIG_CHANCE_XG = 0.25
PASS_MILESTONES = (50, 75)
CONTROL_SEQUENCE = 10
CHAOS_CHANGES_PER_MIN = 4.5
CHECK_EVERY_SECONDS = 60
COOLDOWN_SECONDS = 6 * 60


@dataclass
class Moment:
    id: str
    t: float
    minute: int
    type: str
    team_id: str
    importance: float  # 0..1, drives what reaches the screen
    why: dict[str, Any] = field(default_factory=dict)
    player_id: str | None = None
    player_name: str | None = None
    event_id: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


class MomentDetector:
    def __init__(self, state: MatchState) -> None:
        self.state = state
        self.names: dict[str, str] = {}
        self._count = 0
        self._last_check = 0.0
        self._cooldown: dict[str, float] = {}
        self._sequence_team: str | None = None
        self._sequence_len = 0
        self._tilt_prev: dict[str, float] = {}
        self._pass_milestones: set[tuple[str, int]] = set()

    def process(self, e: dict[str, Any]) -> list[Moment]:
        """Call after `state.ingest(e)`. Returns the moments this event created."""
        if e["type"] == "match_start":
            for side in ("home", "away"):
                for p in e["metrics"][side].get("players", []):
                    self.names[p["id"]] = p["name"]
            return []

        found: list[Moment] = []
        handler = getattr(self, f"_on_{e['type']}", None)
        if handler:
            found.extend(handler(e))
        found.extend(self._sequence(e))
        if e["t"] - self._last_check >= CHECK_EVERY_SECONDS:
            self._last_check = e["t"]
            found.extend(self._trends(e))
        return found

    # --------------------------------------------------------------- helpers
    def _moment(self, e: dict[str, Any], type_: str, importance: float, why: dict[str, Any], team_id: str | None = None, player_id: str | None = None) -> Moment:
        self._count += 1
        pid = (player_id if player_id is not None else e.get("player_id")) or None
        return Moment(
            id=f"mom-{self._count:04d}",
            t=e["t"],
            minute=e["minute"],
            type=type_,
            team_id=team_id or e["team_id"],
            importance=round(min(1.0, importance), 2),
            why=why,
            player_id=pid,
            player_name=self.names.get(pid) if pid else None,
            event_id=e.get("event_id"),
        )

    def _cool(self, key: str, t: float) -> bool:
        """True if `key` may fire now; starts its cooldown."""
        if t - self._cooldown.get(key, -1e9) < COOLDOWN_SECONDS:
            return False
        self._cooldown[key] = t
        return True

    def _team_name(self, team_id: str) -> str:
        return self.state.snapshot()["teams"][team_id]["name"]

    # -------------------------------------------------------- event handlers
    def _on_goal(self, e: dict[str, Any]) -> list[Moment]:
        s = e["score"]
        scorer_home = e["team_id"] == self.state.home_id
        mine, theirs = (s["home"], s["away"]) if scorer_home else (s["away"], s["home"])
        if mine == theirs:
            game_state = "equaliser"
        elif (mine, theirs) == (1, 0):
            game_state = "opener"
        elif mine == theirs + 1:
            game_state = "go_ahead"
        elif mine > theirs:
            game_state = "extends_lead"
        else:
            game_state = "pulls_one_back"
        player = self.state.players.get(e.get("player_id"))
        goals = player.goals if player else 1
        why = {
            "xg": e["metrics"].get("xg"),
            "shot_speed_kmh": e["metrics"].get("shot_speed_kmh"),
            "game_state": game_state,
            "score": s,
            "player_goals_today": goals,
            "team_xg_so_far": round(self.state.teams[e["team_id"]].xg, 2),
        }
        if e["metrics"].get("xg", 1) < 0.08:
            why["against_the_odds"] = True
        late = e["minute"] >= 80
        out = [self._moment(e, "goal", 0.9 + (0.1 if late else 0), why)]
        if goals in (2, 3):
            out.append(self._moment(e, "milestone", 0.85, {"milestone": "brace" if goals == 2 else "hat_trick", "goals": goals}))
        return out

    def _on_shot(self, e: dict[str, Any]) -> list[Moment]:
        out = []
        m = e["metrics"]
        if e.get("outcome") != "goal" and m.get("xg", 0) >= BIG_CHANCE_XG:
            out.append(self._moment(e, "big_chance", 0.6 + m["xg"] / 2, {"xg": m["xg"], "outcome": e.get("outcome"), "distance_m": m.get("distance_m")}))
        if m.get("shot_speed_kmh", 0) >= SHOT_SPEED_TAG_KMH:
            out.append(self._moment(e, "speed_tag", 0.45, {"metric": "shot_speed_kmh", "value": m["shot_speed_kmh"], "threshold": SHOT_SPEED_TAG_KMH}))
        return out

    def _on_save(self, e: dict[str, Any]) -> list[Moment]:
        xg = e["metrics"].get("xg_faced", 0)
        if xg >= BIG_CHANCE_XG:
            return [self._moment(e, "key_save", 0.6 + xg / 2, {"xg_faced": xg})]
        return []

    def _on_sprint(self, e: dict[str, Any]) -> list[Moment]:
        v = e["metrics"].get("top_speed_kmh", 0)
        if v >= SPEED_TAG_KMH:
            return [self._moment(e, "speed_tag", 0.4, {"metric": "top_speed_kmh", "value": v, "distance_m": e["metrics"].get("distance_m"), "threshold": SPEED_TAG_KMH})]
        return []

    def _on_pass(self, e: dict[str, Any]) -> list[Moment]:
        out = []
        m = e["metrics"]
        if e.get("outcome") == "complete" and m.get("line_breaking") and m.get("difficulty", 0) >= 0.7:
            out.append(
                self._moment(
                    e,
                    "line_breaker",
                    0.3 + m["difficulty"] / 4,
                    {"difficulty": m["difficulty"], "success_probability": m.get("success_probability"), "distance_m": m["distance_m"], "receiver_id": e.get("related_player_id"), "receiver_name": self.names.get(e.get("related_player_id", ""))},
                )
            )
        p = self.state.players.get(e.get("player_id"))
        if p:
            for n in PASS_MILESTONES:
                if p.passes == n and (p.player_id, n) not in self._pass_milestones:
                    self._pass_milestones.add((p.player_id, n))
                    out.append(self._moment(e, "milestone", 0.3, {"milestone": f"{n}_passes", "pass_accuracy": round(p.pass_accuracy, 2)}))
        return out

    def _on_card(self, e: dict[str, Any]) -> list[Moment]:
        red = e.get("outcome") == "red"
        return [self._moment(e, "card", 0.85 if red else 0.35, {"card": e.get("outcome")})]

    # ------------------------------------------------------------- patterns
    def _sequence(self, e: dict[str, Any]) -> list[Moment]:
        """Control: a long chain of completed passes by one team."""
        if e["type"] != "pass":
            if e["type"] in ("possession_change", "goal", "kickoff"):
                self._sequence_team, self._sequence_len = None, 0
            return []
        if e.get("outcome") != "complete":
            self._sequence_team, self._sequence_len = None, 0
            return []
        if e["team_id"] != self._sequence_team:
            self._sequence_team, self._sequence_len = e["team_id"], 0
        self._sequence_len += 1
        if self._sequence_len == CONTROL_SEQUENCE and self._cool(f"control:{e['team_id']}", e["t"]):
            return [self._moment(e, "control", 0.5, {"consecutive_passes": self._sequence_len, "possession_share": self.state.possession().get(e["team_id"])}, player_id="")]
        return []

    def _trends(self, e: dict[str, Any]) -> list[Moment]:
        if e["t"] < 8 * 60:
            return []
        out = []
        w = self.state.window_stats()
        for tid in (self.state.home_id, self.state.away_id):
            tilt = w[tid]["field_tilt"]
            prev = self._tilt_prev.get(tid, 0.5)
            if tilt >= 0.7 and prev <= 0.5 and self._cool(f"momentum:{tid}", e["t"]):
                out.append(
                    self._moment(e, "momentum_shift", 0.65, {"field_tilt_last_5": tilt, "field_tilt_before": prev, "xg_last_5": w[tid]["xg"], "final_third_passes_last_5": w[tid]["final_third_passes"]}, team_id=tid, player_id="")
                )
            self._tilt_prev[tid] = tilt
            if w[tid]["pressures"] >= 18 and self._cool(f"press:{tid}", e["t"]):
                out.append(
                    self._moment(e, "pressing_spell", 0.55, {"pressures_last_5": w[tid]["pressures"], "turnovers_won_last_5": w[tid]["turnovers_won"], "ppda": self.state.snapshot()["teams"][tid]["ppda"]}, team_id=tid, player_id="")
                )
        rate = w["_match"]["possession_changes_per_min"]
        if rate >= CHAOS_CHANGES_PER_MIN and self._cool("chaos", e["t"]):
            out.append(self._moment(e, "chaos", 0.5, {"possession_changes_per_min": rate}, team_id=e["team_id"], player_id=""))
        return out
