"""The agent crew and the orchestrator that hands work between them.

Roles:

- **Analyst** (deterministic tool agent): ingests events into `MatchState`
  and detects moments with evidence. It owns the numbers.
- **Explainer** (LLM): turns a moment plus the match snapshot into a
  headline, an explanation of why it matters and the evidence behind it.
  Its answer is checked against the evidence; ungrounded numbers trigger a
  retry with feedback, then a deterministic fallback.
- **Narrator** (LLM): live commentary lines and half/full-time recaps from
  the shared timeline.
- **Personalizer** (LLM): rewrites each insight per viewer profile (mode,
  language, favourite club and player) and decides whether it is worth
  showing to that viewer at all.
- **Director** (deterministic): turns personalized insights into timed,
  machine-readable overlay cues.

All agents read from and write to one `Blackboard`, so every handoff is a
recorded entry that later agents and the UI can inspect.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any

from insights import MatchState, Moment, MomentDetector

from .llm import LLMClient, LLMError, OfflineClient
from .offline import respond as offline_respond

EXPLAIN_THRESHOLD = 0.45
VIEWER_THRESHOLDS = {"analyst": 0.3, "casual": 0.55, "kids": 0.6, "player_focus": 0.3}

EXPLAINER_PROMPT = """You are the Explainer on a live football broadcast analytics crew.
You receive one detected match moment with its evidence and the current match snapshot.
Explain WHY the moment matters (control vs chaos, pressure, momentum, game state, individual quality), not just what happened.
Rules: use only numbers present in the input; never invent players, teams or stats; keep the explanation under 45 words.
Reply as JSON: {"headline": str (max 10 words), "explanation": str, "evidence": [{"label": str, "value": str|number}], "tactical_theme": one of "control","chaos","pressure","momentum","finishing","individual_brilliance","discipline","set_piece"}"""

NARRATOR_PROMPT = """You are the live Narrator for a football stream. Write one vivid commentary line (max 25 words) for the moment, using the explainer's insight. Use only facts in the input.
Reply as JSON: {"line": str}"""

RECAP_PROMPT = """You are the Narrator writing a match recap for a studio show. Use only the snapshot, key moments and player data provided.
Reply as JSON: {"title": str, "summary": str (60-90 words, mention xG and possession), "key_moments": [str] (max 5), "player_of_the_match": str}"""

PERSONALIZER_PROMPT = """You are the Personalizer. Rewrite the insight for one viewer.
Profiles: "analyst" = dense, numeric, tactical vocabulary; "casual" = one or two short, warm sentences, at most one number; "kids" = simple, playful, no jargon; "player_focus" = centre the viewer's favourite player.
Write in the viewer's language (ISO code in profile.language) with natural football vocabulary for that market. If the moment involves the viewer's favourite club or player, make that connection explicit.
Use only facts in the input. Reply as JSON: {"text": str, "language": str}"""


@dataclass
class Profile:
    id: str
    mode: str = "casual"  # analyst | casual | kids | player_focus
    language: str = "en"
    favorite_team: str | None = None
    favorite_player: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass
class Blackboard:
    """Shared state for the crew. Every agent output lands here."""

    moments: list[dict[str, Any]] = field(default_factory=list)
    insights: dict[str, dict[str, Any]] = field(default_factory=dict)
    commentary: list[dict[str, Any]] = field(default_factory=list)
    personalized: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    overlays: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    recaps: list[dict[str, Any]] = field(default_factory=list)
    trace: list[dict[str, Any]] = field(default_factory=list)

    def log(self, agent: str, action: str, **detail: Any) -> None:
        self.trace.append({"agent": agent, "action": action, "ts": round(time.time(), 3), **detail})


_NUM = re.compile(r"\d+(?:\.\d+)?")
# Clock and id fields are not facts a viewer should ever be told.
_BOOKKEEPING = {"t", "event_id", "id", "moment_id", "t_in", "player_id", "related_player_id"}


def _numbers(obj: Any) -> set[float]:
    """Every number that appears anywhere in a JSON-like structure."""
    found: set[float] = set()
    if isinstance(obj, bool):
        return found
    if isinstance(obj, (int, float)):
        found.add(round(float(obj), 2))
        if isinstance(obj, float) and 0 < obj <= 1:
            found.add(round(obj * 100))  # allow 0.73 to be quoted as 73%
    elif isinstance(obj, str):
        found.update(round(float(n), 2) for n in _NUM.findall(obj))
    elif isinstance(obj, dict):
        for k, v in obj.items():
            if k not in _BOOKKEEPING:
                found |= _numbers(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            found |= _numbers(v)
    return found


def ungrounded_numbers(text: str, source: Any) -> list[str]:
    allowed = _numbers(source)
    bad = []
    for n in _NUM.findall(text):
        v = round(float(n), 2)
        if v in allowed or v < 2:  # small counting words like "1" are fine
            continue
        if any(abs(v - a) <= (0.051 if a < 2 else 0.5) for a in allowed):  # rounding only
            continue
        bad.append(n)
    return bad


class Crew:
    def __init__(self, client: LLMClient | None = None, profiles: list[Profile] | None = None):
        self.client = client or OfflineClient()
        self.profiles = profiles or [Profile("analyst-en", "analyst", "en"), Profile("fan-es", "casual", "es")]
        self.state = MatchState()
        self.detector = MomentDetector(self.state)
        self.board = Blackboard()
        self.names: dict[str, str] = {}
        self._half_time_done = False

    # ------------------------------------------------------------ pipeline
    def ingest(self, event: dict[str, Any]) -> list[dict[str, Any]]:
        """Run one event through the crew. Returns the overlay cues it produced."""
        self.state.ingest(event)
        if event["type"] == "match_start":
            for side in ("home", "away"):
                for p in event["metrics"][side]["players"]:
                    self.names[p["id"]] = p["name"]
        moments = self.detector.process(event)
        cues: list[dict[str, Any]] = []
        for m in moments:
            md = m.to_dict()
            self.board.moments.append(md)
            self.board.log("analyst", "moment", moment_id=m.id, type=m.type, importance=m.importance)
            if m.importance < EXPLAIN_THRESHOLD:
                continue
            insight = self.explain(md)
            self.narrate(md, insight)
            for prof in self.profiles:
                item = self.personalize(md, insight, prof)
                if item:
                    cues.append(self.direct(md, insight, item, prof))
        if event["type"] == "period_end" and event["metrics"].get("period") == 1 and not self._half_time_done:
            self._half_time_done = True
            self.recap("half_time")
        if event["type"] == "match_end":
            self.recap("full_time")
        return cues

    def run(self, events: list[dict[str, Any]]) -> Blackboard:
        for e in events:
            self.ingest(e)
        return self.board

    # -------------------------------------------------------------- agents
    def _team_name(self, team_id: str) -> str:
        side = "home" if team_id == self.state.home_id else "away"
        return self.state.meta[side]["name"]

    def _call(self, agent: str, system: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return self.client.complete_json(system, payload)
        except (LLMError, ValueError) as exc:
            self.board.log(agent, "fallback", reason=str(exc)[:200])
            return offline_respond(payload)

    def explain(self, moment: dict[str, Any]) -> dict[str, Any]:
        snap = self.state.snapshot()
        payload = {
            "task": "explain",
            "moment": moment,
            "team_name": self._team_name(moment["team_id"]),
            "snapshot": {k: snap[k] for k in ("minute", "score", "teams", "last_5_min")},
        }
        out = self._call("explainer", EXPLAINER_PROMPT, payload)
        bad = ungrounded_numbers(f"{out.get('headline', '')} {out.get('explanation', '')}", payload)
        if bad:
            self.board.log("explainer", "grounding_retry", moment_id=moment["id"], ungrounded=bad)
            payload["feedback"] = f"These numbers are not in the input, remove them: {', '.join(bad)}"
            out = self._call("explainer", EXPLAINER_PROMPT, payload)
            if ungrounded_numbers(f"{out.get('headline', '')} {out.get('explanation', '')}", payload):
                self.board.log("explainer", "grounding_fallback", moment_id=moment["id"])
                out = offline_respond(payload)
        out["moment_id"] = moment["id"]
        self.board.insights[moment["id"]] = out
        self.board.log("explainer", "insight", moment_id=moment["id"], theme=out.get("tactical_theme"))
        return out

    def narrate(self, moment: dict[str, Any], insight: dict[str, Any]) -> dict[str, Any]:
        out = self._call("narrator", NARRATOR_PROMPT, {"task": "narrate", "moment": moment, "insight": insight})
        entry = {"t": moment["t"], "minute": moment["minute"], "moment_id": moment["id"], "line": out.get("line", "")}
        self.board.commentary.append(entry)
        self.board.log("narrator", "line", moment_id=moment["id"])
        return entry

    def personalize(self, moment: dict[str, Any], insight: dict[str, Any], prof: Profile) -> dict[str, Any] | None:
        relevance = moment["importance"]
        if prof.favorite_team and moment["team_id"] == prof.favorite_team:
            relevance += 0.15
        if prof.favorite_player and moment.get("player_id") == prof.favorite_player:
            relevance += 0.3
        if relevance < VIEWER_THRESHOLDS.get(prof.mode, 0.5):
            self.board.log("personalizer", "skip", moment_id=moment["id"], profile=prof.id, relevance=round(relevance, 2))
            return None
        payload = {
            "task": "personalize",
            "moment": moment,
            "insight": insight,
            "profile": prof.to_dict(),
            "team_name": self._team_name(moment["team_id"]),
        }
        out = self._call("personalizer", PERSONALIZER_PROMPT, payload)
        item = {"moment_id": moment["id"], "t": moment["t"], "minute": moment["minute"], **out}
        self.board.personalized.setdefault(prof.id, []).append(item)
        self.board.log("personalizer", "deliver", moment_id=moment["id"], profile=prof.id)
        return item

    def direct(self, moment: dict[str, Any], insight: dict[str, Any], item: dict[str, Any], prof: Profile) -> dict[str, Any]:
        side = "home" if moment["team_id"] == self.state.home_id else "away"
        colors = self.state.meta[side].get("colors", ["#333333", "#FFFFFF"])
        big = moment["importance"] >= 0.8
        cue = {
            "cue_id": f"{prof.id}:{moment['id']}",
            "profile": prof.id,
            "t_in": moment["t"],
            "duration_s": 12 if big else 7,
            "layout": "full_banner" if big else "lower_third",
            "theme": insight.get("tactical_theme"),
            "team_id": moment["team_id"],
            "colors": colors,
            "title": insight.get("headline"),
            "body": item.get("text"),
            "player_tag": moment.get("player_name"),
            "stat_chips": insight.get("evidence", [])[:3] if prof.mode in ("analyst", "player_focus") else [],
            "language": item.get("language", prof.language),
        }
        self.board.overlays.setdefault(prof.id, []).append(cue)
        return cue

    def recap(self, phase: str) -> dict[str, Any]:
        snap = self.state.snapshot()
        key = sorted(
            (self.board.insights[m["id"]] | {"minute": m["minute"], "importance": m["importance"]} for m in self.board.moments if m["id"] in self.board.insights),
            key=lambda i: i["importance"],
            reverse=True,
        )[:6]
        potm = self._player_of_the_match()
        payload = {"task": "recap", "phase": phase, "snapshot": snap, "key_moments": key, "player_of_the_match": potm}
        out = self._call("narrator", RECAP_PROMPT, payload)
        out["phase"] = phase
        self.board.recaps.append(out)
        self.board.log("narrator", "recap", phase=phase)
        return out

    def _player_of_the_match(self) -> dict[str, Any] | None:
        def score(p: Any) -> float:
            return p.goals * 3 + p.xg * 2 + p.progressive_passes * 0.05 + p.tackles_won * 0.15 + p.interceptions * 0.15 + p.line_breaking_passes * 0.2

        if not self.state.players:
            return None
        best = max(self.state.players.values(), key=score)
        return {"player_id": best.player_id, "name": self.names.get(best.player_id, best.player_id), **best.to_dict()}
