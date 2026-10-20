"""Possession-based match engine that produces football-realistic events.

The engine walks through a match one on-ball action at a time. Each team's
tactics (pressing, tempo, directness, width), player attributes and a
momentum value that drifts over the match shape which actions happen and
how often they succeed. The output is a list of `Event`s with coordinates,
timestamps and per-event metrics (pass difficulty, ball speed, xG, sprint
speed...) that downstream agents can aggregate and explain.

Internally the ball position is tracked in an "attacking frame" where the
team in possession always attacks towards ax = 105. `_abs` converts that to
absolute pitch coordinates for the output.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

from .models import PITCH_LENGTH, PITCH_WIDTH, Event, Player, Team

HALF_SECONDS = 45 * 60
SPRINT_THRESHOLD_KMH = 30.0
GOAL_Y = PITCH_WIDTH / 2


@dataclass
class MatchConfig:
    seed: int = 7
    match_id: str = "M001"
    venue: str = "Riverside Park"
    kickoff_utc: str = "2026-10-24T15:00:00Z"


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def expected_goals(ax: float, ay: float) -> float:
    """xG from distance and visible goal angle, in the attacking frame."""
    dx = PITCH_LENGTH - ax
    dy = abs(ay - GOAL_Y)
    distance = math.hypot(dx, dy)
    # Angle subtended by the 7.32 m goal mouth.
    half = 3.66
    angle = abs(math.atan2(half - dy, dx) + math.atan2(half + dy, dx)) if dx > 0 else 0.0
    logit = -1.1 - 0.11 * distance + 1.6 * angle
    return round(_clamp(1 / (1 + math.exp(-logit)), 0.01, 0.95), 3)


def pass_difficulty(distance: float, forward: float, under_pressure: bool, ax_end: float) -> float:
    """0 (trivial) to 1 (very hard)."""
    d = 0.35 * _clamp(distance / 45, 0, 1)
    d += 0.25 * _clamp(forward / 30, 0, 1)
    d += 0.2 if under_pressure else 0.0
    d += 0.2 * _clamp((ax_end - 70) / 35, 0, 1)
    return round(_clamp(d, 0.02, 0.98), 2)


class MatchEngine:
    def __init__(self, home: Team, away: Team, config: MatchConfig | None = None):
        self.home = home
        self.away = away
        self.cfg = config or MatchConfig()
        self.rng = random.Random(self.cfg.seed)
        self.events: list[Event] = []
        self.t = 0.0
        self.period = 1
        self.period_start = 0.0
        self.score = [0, 0]
        # Positive momentum favours the home side, negative the away side.
        self.momentum = 0.0
        self.attacking: Team = home
        self.carrier: Player = home.by_position("MF")[0]
        self.ax = 52.5
        self.ay = 34.0

    # ------------------------------------------------------------------ utils
    def _defending(self) -> Team:
        return self.away if self.attacking is self.home else self.home

    def _abs(self, ax: float, ay: float, team: Team | None = None) -> tuple[float, float]:
        team = team or self.attacking
        if team is self.home:
            return round(ax, 1), round(ay, 1)
        return round(PITCH_LENGTH - ax, 1), round(PITCH_WIDTH - ay, 1)

    def _team_momentum(self, team: Team) -> float:
        return self.momentum if team is self.home else -self.momentum

    def _emit(self, type_: str, team: Team, player: Player | None = None, **kw) -> Event:
        # Match clock restarts at 45:00 for the second half, while `t`
        # keeps counting elapsed playing time so the stream stays ordered.
        clock = (self.period - 1) * HALF_SECONDS + (self.t - self.period_start)
        ev = Event(
            match_id=self.cfg.match_id,
            event_id=len(self.events) + 1,
            t=round(self.t, 1),
            period=self.period,
            minute=int(clock // 60),
            second=int(clock % 60),
            type=type_,
            team_id=team.id,
            player_id=player.id if player else None,
            score=(self.score[0], self.score[1]),
            **kw,
        )
        self.events.append(ev)
        return ev

    def _advance(self, seconds: float) -> None:
        self.t += seconds

    def _pick_receiver(self, team: Team, ax_end: float, exclude: Player | None) -> Player:
        if ax_end < 30:
            pool = team.by_position("DF") + team.by_position("MF")[:1]
        elif ax_end < 70:
            pool = team.by_position("MF") + team.by_position("DF")[1:3]
        else:
            pool = team.by_position("FW") + team.by_position("MF")
        pool = [p for p in pool if p is not exclude] or [p for p in team.players if p is not exclude]
        return self.rng.choice(pool)

    def _pick_defender(self, ax: float) -> Player:
        team = self._defending()
        # ax is in the attackers' frame; deep in their half means the
        # defending forwards are the ones pressing.
        if ax < 40:
            pool = team.by_position("FW") + team.by_position("MF")
        elif ax < 70:
            pool = team.by_position("MF")
        else:
            pool = team.by_position("DF") + team.by_position("MF")[:1]
        return self.rng.choice(pool)

    # ------------------------------------------------------------- lifecycle
    @staticmethod
    def _team_meta(team: Team) -> dict:
        return {
            "id": team.id,
            "name": team.name,
            "short_name": team.short_name,
            "colors": list(team.colors),
            "formation": team.formation,
            "players": [
                {"id": p.id, "name": p.name, "number": p.number, "position": p.position} for p in team.players
            ],
        }

    def run(self) -> list[Event]:
        self._emit(
            "match_start",
            self.home,
            metrics={
                "home": self._team_meta(self.home),
                "away": self._team_meta(self.away),
                "venue": self.cfg.venue,
                "kickoff_utc": self.cfg.kickoff_utc,
                "weather": self.rng.choice(["clear", "light rain", "overcast", "windy"]),
                "seed": self.cfg.seed,
            },
        )
        for period, kicker in ((1, self.home), (2, self.away)):
            self.period = period
            self.period_start = self.t
            stoppage = self.rng.randint(1, 5) * 60
            self._kickoff(kicker)
            while self.t < self.period_start + HALF_SECONDS + stoppage:
                self._step()
            self._emit(
                "period_end",
                self.attacking,
                metrics={"period": period, "stoppage_seconds": stoppage},
            )
        self._emit("match_end", self.home, metrics={"final_score": {"home": self.score[0], "away": self.score[1]}})
        return self.events

    def _kickoff(self, team: Team) -> None:
        self.attacking = team
        self.ax, self.ay = 52.5, 34.0
        self.carrier = team.by_position("FW")[0] if team.by_position("FW") else team.by_position("MF")[0]
        self._emit("kickoff", team, self.carrier, x=52.5, y=34.0, metrics={"period": self.period})

    def _turnover(self, new_team: Team, new_carrier: Player, reason: str, ax_lost: float, ay_lost: float) -> None:
        old = self.attacking
        self.attacking = new_team
        self.carrier = new_carrier
        # Flip to the new attackers' frame.
        self.ax, self.ay = PITCH_LENGTH - ax_lost, PITCH_WIDTH - ay_lost
        x, y = self._abs(self.ax, self.ay)
        self._emit(
            "possession_change",
            new_team,
            new_carrier,
            x=x,
            y=y,
            metrics={"from_team": old.id, "reason": reason},
        )
        # Winning the ball nudges momentum towards the winner.
        self.momentum = _clamp(self.momentum + (0.04 if new_team is self.home else -0.04), -1, 1)

    # ------------------------------------------------------------------ step
    def _step(self) -> None:
        # Momentum mean-reverts and drifts.
        self.momentum = _clamp(self.momentum * 0.995 + self.rng.gauss(0, 0.02), -1, 1)

        team = self.attacking
        defending = self._defending()
        mom = self._team_momentum(team)

        under_pressure = False
        press_zone = 1.3 if self.ax < 45 else (1.0 if self.ax < 75 else 0.8)
        if self.rng.random() < defending.tactics.press_intensity * 0.35 * press_zone:
            under_pressure = True
            presser = self._pick_defender(self.ax)
            x, y = self._abs(self.ax, self.ay)
            self._emit(
                "pressure",
                defending,
                presser,
                x=x,
                y=y,
                related_player_id=self.carrier.id,
                metrics={"intensity": round(defending.tactics.press_intensity * press_zone, 2)},
            )
            self._advance(self.rng.uniform(0.5, 1.5))

        shot_zone = self.ax > 86 and abs(self.ay - GOAL_Y) < 18
        roll = self.rng.random()
        if shot_zone and roll < 0.06 + 0.1 * self.carrier.finishing + 0.03 * mom:
            self._shot(under_pressure)
        elif roll < 0.78:
            self._pass(under_pressure)
        else:
            self._carry(under_pressure)

    # ---------------------------------------------------------------- actions
    def _pass(self, under_pressure: bool) -> None:
        team, p = self.attacking, self.carrier
        tac = team.tactics
        long_ball = self.rng.random() < 0.08 + 0.2 * tac.directness
        distance = self.rng.uniform(25, 50) if long_ball else self.rng.lognormvariate(2.5, 0.45)
        distance = _clamp(distance, 4, 60)
        forward_bias = 0.15 + 0.6 * tac.directness
        angle = self.rng.gauss(0, 1.1 - 0.5 * forward_bias)
        dx = distance * math.cos(angle)
        dy = distance * math.sin(angle) * (0.7 + 0.6 * tac.width)
        end_ax = _clamp(self.ax + dx, 1, PITCH_LENGTH - 1)
        end_ay = _clamp(self.ay + dy, 1, PITCH_WIDTH - 1)
        distance = math.hypot(end_ax - self.ax, end_ay - self.ay)
        forward = end_ax - self.ax

        difficulty = pass_difficulty(distance, forward, under_pressure, end_ax)
        p_success = _clamp(
            0.62 + 0.38 * p.passing - 0.45 * difficulty + 0.08 * self._team_momentum(team), 0.15, 0.97
        )
        success = self.rng.random() < p_success
        ball_speed = _clamp(self.rng.gauss(35 + distance * 1.1, 6), 20, 110)
        flight = distance / (ball_speed / 3.6)
        progressive = forward >= 10 and end_ax > 40
        line_breaking = forward >= 15 and difficulty > 0.45

        receiver = self._pick_receiver(team, end_ax, p) if success else None
        x, y = self._abs(self.ax, self.ay)
        ex, ey = self._abs(end_ax, end_ay)
        self._emit(
            "pass",
            team,
            p,
            x=x,
            y=y,
            end_x=ex,
            end_y=ey,
            outcome="complete" if success else "incomplete",
            related_player_id=receiver.id if receiver else None,
            metrics={
                "distance_m": round(distance, 1),
                "difficulty": difficulty,
                "success_probability": round(p_success, 2),
                "ball_speed_kmh": round(ball_speed, 1),
                "progressive": progressive,
                "line_breaking": line_breaking,
                "under_pressure": under_pressure,
                "long_ball": long_ball,
            },
        )
        self._advance(flight + self.rng.uniform(0.8, 3.5) * (1.4 - 0.6 * team.tactics.tempo))

        if success:
            self.carrier = receiver
            self.ax, self.ay = end_ax, end_ay
            return

        # Failed pass: out of play near the touchline, otherwise intercepted.
        defending = self._defending()
        if end_ay <= 2 or end_ay >= PITCH_WIDTH - 2:
            self._advance(self.rng.uniform(5, 12))
            new_carrier = self._pick_receiver(defending, PITCH_LENGTH - end_ax, None)
            self._turnover(defending, new_carrier, "throw_in", end_ax, end_ay)
            x, y = self._abs(self.ax, self.ay)
            self._emit("throw_in", defending, new_carrier, x=x, y=y)
        else:
            # Most loose passes are simply recovered; a clean read of the
            # pass that cuts it out is logged as an interception.
            interceptor = self._pick_defender(end_ax)
            ix, iy = self._abs(end_ax, end_ay)
            kind = "interception" if self.rng.random() < 0.3 else "ball_recovery"
            self._emit(kind, defending, interceptor, x=ix, y=iy, related_player_id=p.id)
            self._turnover(defending, interceptor, kind, end_ax, end_ay)

    def _carry(self, under_pressure: bool) -> None:
        team, p = self.attacking, self.carrier
        distance = self.rng.uniform(3, 18)
        angle = self.rng.gauss(0, 0.7)
        end_ax = _clamp(self.ax + distance * math.cos(angle), 1, PITCH_LENGTH - 1)
        end_ay = _clamp(self.ay + distance * math.sin(angle), 1, PITCH_WIDTH - 1)
        distance = math.hypot(end_ax - self.ax, end_ay - self.ay)
        top_speed = _clamp(self.rng.gauss(p.pace * (0.65 + distance / 50), 1.5), 8, p.pace)
        duration = distance / (top_speed / 3.6 * 0.8)

        take_on = under_pressure or self.rng.random() < 0.25
        x, y = self._abs(self.ax, self.ay)
        ex, ey = self._abs(end_ax, end_ay)

        if take_on:
            defender = self._pick_defender(self.ax)
            p_win = _clamp(
                0.5 + (p.pace - 31) / 20 - 0.35 * defender.tackling + 0.1 * self._team_momentum(team), 0.15, 0.85
            )
            if self.rng.random() >= p_win:
                self._advance(duration * 0.5)
                defending = self._defending()
                foul = self.rng.random() < 0.18
                self._emit(
                    "tackle",
                    defending,
                    defender,
                    x=x,
                    y=y,
                    outcome="foul" if foul else "won",
                    related_player_id=p.id,
                    metrics={"attacker_win_probability": round(p_win, 2)},
                )
                if foul:
                    self._foul(defender, p)
                else:
                    self._turnover(defending, defender, "tackle", self.ax, self.ay)
                return
            self._emit(
                "take_on",
                team,
                p,
                x=x,
                y=y,
                outcome="success",
                related_player_id=defender.id,
                metrics={"win_probability": round(p_win, 2)},
            )

        self._emit(
            "carry",
            team,
            p,
            x=x,
            y=y,
            end_x=ex,
            end_y=ey,
            metrics={"distance_m": round(distance, 1), "top_speed_kmh": round(top_speed, 1)},
        )
        if top_speed >= SPRINT_THRESHOLD_KMH:
            self._emit(
                "sprint",
                team,
                p,
                x=ex,
                y=ey,
                metrics={
                    "top_speed_kmh": round(top_speed, 1),
                    "distance_m": round(distance, 1),
                    "threshold_kmh": SPRINT_THRESHOLD_KMH,
                },
            )
        self._advance(duration + self.rng.uniform(0.3, 1.2))
        self.ax, self.ay = end_ax, end_ay

    def _foul(self, offender: Player, victim: Player) -> None:
        defending = self._defending()
        x, y = self._abs(self.ax, self.ay)
        card = None
        r = self.rng.random()
        if r < 0.015:
            card = "red"
        elif r < 0.17:
            card = "yellow"
        self._emit("foul", defending, offender, x=x, y=y, related_player_id=victim.id, metrics={"card": card} if card else {})
        if card:
            self._emit("card", defending, offender, x=x, y=y, outcome=card)
        self._advance(self.rng.uniform(15, 40))
        self._emit("free_kick", self.attacking, victim, x=x, y=y)

    def _shot(self, under_pressure: bool) -> None:
        team, p = self.attacking, self.carrier
        defending = self._defending()
        xg = expected_goals(self.ax, self.ay)
        if under_pressure:
            xg = round(xg * 0.75, 3)
        shot_speed = _clamp(self.rng.gauss(85 + 25 * p.finishing, 10), 45, 130)
        p_goal = _clamp(xg * (0.8 + 0.3 * p.finishing) + 0.03 * self._team_momentum(team), 0.005, 0.9)

        r = self.rng.random()
        if r < p_goal:
            outcome = "goal"
        elif r < p_goal + 0.28:
            outcome = "saved"
        elif r < p_goal + 0.48:
            outcome = "blocked"
        else:
            outcome = "off_target"

        x, y = self._abs(self.ax, self.ay)
        gx, gy = self._abs(PITCH_LENGTH, GOAL_Y + self.rng.uniform(-3.5, 3.5))
        self._emit(
            "shot",
            team,
            p,
            x=x,
            y=y,
            end_x=gx,
            end_y=gy,
            outcome=outcome,
            metrics={
                "xg": xg,
                "shot_speed_kmh": round(shot_speed, 1),
                "distance_m": round(math.hypot(PITCH_LENGTH - self.ax, GOAL_Y - self.ay), 1),
                "under_pressure": under_pressure,
            },
        )
        self._advance(self.rng.uniform(1, 3))

        if outcome == "goal":
            idx = 0 if team is self.home else 1
            self.score[idx] += 1
            self.momentum = _clamp(self.momentum + (0.12 if team is self.home else -0.12), -1, 1)
            self._emit("goal", team, p, x=x, y=y, metrics={"xg": xg, "shot_speed_kmh": round(shot_speed, 1)})
            self._advance(self.rng.uniform(45, 75))
            self._kickoff(defending)
        elif outcome == "saved":
            gk = defending.by_position("GK")[0]
            self._emit("save", defending, gk, x=gx, y=gy, related_player_id=p.id, metrics={"xg_faced": xg})
            if self.rng.random() < 0.35:
                self._corner()
            else:
                self._turnover(defending, gk, "save", PITCH_LENGTH - 2, GOAL_Y)
        elif outcome == "blocked":
            if self.rng.random() < 0.4:
                self._corner()
            else:
                blocker = self._pick_defender(self.ax)
                self._turnover(defending, blocker, "block", self.ax, self.ay)
        else:
            self._advance(self.rng.uniform(15, 30))
            gk = defending.by_position("GK")[0]
            self._turnover(defending, gk, "goal_kick", PITCH_LENGTH - 6, GOAL_Y)
            x, y = self._abs(self.ax, self.ay)
            self._emit("goal_kick", defending, gk, x=x, y=y)

    def _corner(self) -> None:
        team = self.attacking
        taker = max(team.players, key=lambda pl: pl.passing if pl.position != "GK" else 0)
        side = self.rng.choice([0.5, PITCH_WIDTH - 0.5])
        self._advance(self.rng.uniform(15, 30))
        self.ax, self.ay = PITCH_LENGTH - 0.5, side
        x, y = self._abs(self.ax, self.ay)
        self._emit("corner", team, taker, x=x, y=y)
        self.carrier = taker


def simulate_match(home: Team, away: Team, config: MatchConfig | None = None) -> list[Event]:
    return MatchEngine(home, away, config).run()
