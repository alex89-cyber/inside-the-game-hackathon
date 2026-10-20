"""Incremental match state built from the live event stream.

`MatchState.ingest(event)` updates team and player aggregates one event at
a time, so the same code serves live play and post-match recaps. The state
is the shared memory the agents read from: every number an agent quotes
should come from here rather than from the model's imagination.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any

WINDOW_SECONDS = 5 * 60


@dataclass
class PlayerStats:
    player_id: str
    team_id: str
    passes: int = 0
    passes_complete: int = 0
    difficulty_sum: float = 0.0
    progressive_passes: int = 0
    line_breaking_passes: int = 0
    carries: int = 0
    carry_distance_m: float = 0.0
    sprints: int = 0
    top_speed_kmh: float = 0.0
    shots: int = 0
    xg: float = 0.0
    goals: int = 0
    tackles_won: int = 0
    interceptions: int = 0
    pressures: int = 0
    fouls: int = 0
    cards: list[str] = field(default_factory=list)

    @property
    def pass_accuracy(self) -> float:
        return self.passes_complete / self.passes if self.passes else 0.0

    @property
    def avg_pass_difficulty(self) -> float:
        return self.difficulty_sum / self.passes if self.passes else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "player_id": self.player_id,
            "team_id": self.team_id,
            "passes": self.passes,
            "pass_accuracy": round(self.pass_accuracy, 3),
            "avg_pass_difficulty": round(self.avg_pass_difficulty, 2),
            "progressive_passes": self.progressive_passes,
            "line_breaking_passes": self.line_breaking_passes,
            "carry_distance_m": round(self.carry_distance_m, 1),
            "sprints": self.sprints,
            "top_speed_kmh": round(self.top_speed_kmh, 1),
            "shots": self.shots,
            "xg": round(self.xg, 2),
            "goals": self.goals,
            "tackles_won": self.tackles_won,
            "interceptions": self.interceptions,
            "pressures": self.pressures,
            "fouls": self.fouls,
            "cards": self.cards,
        }


@dataclass
class TeamStats:
    team_id: str
    passes: int = 0
    passes_complete: int = 0
    progressive_passes: int = 0
    final_third_passes: int = 0
    shots: int = 0
    shots_on_target: int = 0
    xg: float = 0.0
    goals: int = 0
    pressures: int = 0
    tackles_won: int = 0
    interceptions: int = 0
    fouls: int = 0
    corners: int = 0
    possession_seconds: float = 0.0
    # Opponent passes allowed in their own 60% of the pitch, for PPDA.
    opp_build_up_passes: int = 0
    def_actions_high: int = 0

    @property
    def pass_accuracy(self) -> float:
        return self.passes_complete / self.passes if self.passes else 0.0

    @property
    def ppda(self) -> float | None:
        """Passes allowed per defensive action. Lower means more intense pressing."""
        return self.opp_build_up_passes / self.def_actions_high if self.def_actions_high else None


class MatchState:
    def __init__(self) -> None:
        self.meta: dict[str, Any] = {}
        self.home_id = ""
        self.away_id = ""
        self.t = 0.0
        self.minute = 0
        self.period = 1
        self.score = {"home": 0, "away": 0}
        self.teams: dict[str, TeamStats] = {}
        self.players: dict[str, PlayerStats] = {}
        self.possession_team: str | None = None
        self._possession_since = 0.0
        self.window: deque[dict[str, Any]] = deque()
        self.events_seen = 0
        self.finished = False

    # ---------------------------------------------------------------- ingest
    def ingest(self, e: dict[str, Any]) -> None:
        self.events_seen += 1
        etype = e["type"]
        if etype == "match_start":
            self.meta = e["metrics"]
            self.home_id = self.meta["home"]["id"]
            self.away_id = self.meta["away"]["id"]
            self.teams = {tid: TeamStats(tid) for tid in (self.home_id, self.away_id)}
            return

        self._tick_possession(e["t"])
        self.t, self.minute, self.period = e["t"], e["minute"], e["period"]
        self.score = e.get("score", self.score)
        self.window.append(e)
        while self.window and self.window[0]["t"] < self.t - WINDOW_SECONDS:
            self.window.popleft()

        team = self.teams.get(e["team_id"])
        opp = self.teams.get(self._opponent(e["team_id"]))
        player = self._player(e.get("player_id"), e["team_id"])
        m = e.get("metrics", {})

        if etype == "pass":
            team.passes += 1
            player.passes += 1
            player.difficulty_sum += m.get("difficulty", 0)
            if e.get("outcome") == "complete":
                team.passes_complete += 1
                player.passes_complete += 1
            if m.get("progressive"):
                team.progressive_passes += 1
                player.progressive_passes += 1
            if m.get("line_breaking"):
                player.line_breaking_passes += 1
            if self._attacking_x(e["team_id"], e["x"]) > 70:
                team.final_third_passes += 1
            if self._attacking_x(e["team_id"], e["x"]) < 63:
                opp.opp_build_up_passes += 1
            self._set_possession(e["team_id"], e["t"])
        elif etype == "carry":
            player.carries += 1
            player.carry_distance_m += m.get("distance_m", 0)
            player.top_speed_kmh = max(player.top_speed_kmh, m.get("top_speed_kmh", 0))
            self._set_possession(e["team_id"], e["t"])
        elif etype == "sprint":
            player.sprints += 1
        elif etype == "shot":
            team.shots += 1
            player.shots += 1
            team.xg += m.get("xg", 0)
            player.xg += m.get("xg", 0)
            if e.get("outcome") in ("goal", "saved"):
                team.shots_on_target += 1
        elif etype == "goal":
            team.goals += 1
            player.goals += 1
        elif etype == "pressure":
            team.pressures += 1
            player.pressures += 1
        elif etype in ("tackle", "interception"):
            if etype == "interception" or e.get("outcome") == "won":
                if etype == "tackle":
                    team.tackles_won += 1
                    player.tackles_won += 1
                else:
                    team.interceptions += 1
                    player.interceptions += 1
                # Defensive action in the opponent's 60% of the pitch.
                if self._attacking_x(e["team_id"], e["x"]) > 42:
                    team.def_actions_high += 1
        elif etype == "foul":
            team.fouls += 1
            player.fouls += 1
        elif etype == "card":
            player.cards.append(e.get("outcome", "yellow"))
        elif etype == "corner":
            team.corners += 1
        elif etype == "possession_change":
            self._set_possession(e["team_id"], e["t"])
        elif etype == "match_end":
            self.finished = True

    # --------------------------------------------------------------- helpers
    def _opponent(self, team_id: str) -> str:
        return self.away_id if team_id == self.home_id else self.home_id

    def _attacking_x(self, team_id: str, x: float | None) -> float:
        """x in the frame where `team_id` attacks towards 105."""
        if x is None:
            return 52.5
        return x if team_id == self.home_id else 105 - x

    def _player(self, player_id: str | None, team_id: str) -> PlayerStats:
        if not player_id:
            return PlayerStats("_", team_id)
        if player_id not in self.players:
            self.players[player_id] = PlayerStats(player_id, team_id)
        return self.players[player_id]

    def _set_possession(self, team_id: str, t: float) -> None:
        if team_id != self.possession_team:
            self._tick_possession(t)
            self.possession_team = team_id

    def _tick_possession(self, t: float) -> None:
        if self.possession_team and t > self._possession_since:
            self.teams[self.possession_team].possession_seconds += t - self._possession_since
        self._possession_since = t

    # ------------------------------------------------------------- read API
    def possession(self) -> dict[str, float]:
        total = sum(ts.possession_seconds for ts in self.teams.values()) or 1
        return {tid: round(ts.possession_seconds / total, 3) for tid, ts in self.teams.items()}

    def window_stats(self) -> dict[str, dict[str, float]]:
        """Last five minutes per team: xG, final-third passes, pressures, field tilt."""
        out = {tid: {"xg": 0.0, "final_third_passes": 0, "pressures": 0, "turnovers_won": 0} for tid in self.teams}
        changes = 0
        for e in self.window:
            tid = e["team_id"]
            if tid not in out:
                continue
            if e["type"] == "shot":
                out[tid]["xg"] += e["metrics"].get("xg", 0)
            elif e["type"] == "pass" and self._attacking_x(tid, e.get("x")) > 70:
                out[tid]["final_third_passes"] += 1
            elif e["type"] == "pressure":
                out[tid]["pressures"] += 1
            elif e["type"] == "possession_change":
                out[tid]["turnovers_won"] += 1
                changes += 1
        total_ft = sum(v["final_third_passes"] for v in out.values()) or 1
        for tid, v in out.items():
            v["xg"] = round(v["xg"], 2)
            v["field_tilt"] = round(v["final_third_passes"] / total_ft, 2)
        minutes = min(WINDOW_SECONDS, max(self.t, 1)) / 60
        out["_match"] = {"possession_changes_per_min": round(changes / minutes, 2)}
        return out

    def snapshot(self) -> dict[str, Any]:
        poss = self.possession()
        teams = {}
        for tid, ts in self.teams.items():
            teams[tid] = {
                "name": self.meta[("home" if tid == self.home_id else "away")]["name"],
                "goals": ts.goals,
                "possession": poss.get(tid, 0.0),
                "passes": ts.passes,
                "pass_accuracy": round(ts.pass_accuracy, 3),
                "progressive_passes": ts.progressive_passes,
                "shots": ts.shots,
                "shots_on_target": ts.shots_on_target,
                "xg": round(ts.xg, 2),
                "pressures": ts.pressures,
                "ppda": round(ts.ppda, 1) if ts.ppda else None,
                "tackles_won": ts.tackles_won,
                "interceptions": ts.interceptions,
                "corners": ts.corners,
                "fouls": ts.fouls,
            }
        return {
            "minute": self.minute,
            "period": self.period,
            "score": self.score,
            "home_id": self.home_id,
            "away_id": self.away_id,
            "teams": teams,
            "last_5_min": self.window_stats(),
            "finished": self.finished,
        }

    def top_players(self, key: str, n: int = 3) -> list[dict[str, Any]]:
        ranked = sorted(self.players.values(), key=lambda p: getattr(p, key), reverse=True)
        return [p.to_dict() for p in ranked[:n]]
