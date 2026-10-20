"""Live second-screen server.

Simulates a match, runs it through the agent crew for one viewer profile
and streams everything to the browser as Server-Sent Events. The pitch and
stats never wait for the model: the Analyst runs inline, and the LLM agents
work through their queue in the background, so their output lands a few
seconds after the moment, the way a real broadcast graphic would.

- `event`: raw on-ball events for the animated pitch
- `state`: the shared match snapshot (score, stats, last five minutes)
- `cue`: personalized overlay cues from the Director
- `line`: live commentary from the Narrator
- `recap`: half-time and full-time recaps
- `trace`: agent handoffs, for the "under the hood" panel

Run locally with `uvicorn app.server:app --reload`.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from agents import Crew, Profile, get_client
from simulator import TEAMS, MatchConfig, simulate_match

STATIC = Path(__file__).parent / "static"
MODES = {"analyst", "casual", "kids", "player_focus"}
AGENT_CONCURRENCY = 3
PITCH_EVENTS = {"pass", "carry", "shot", "tackle", "interception", "ball_recovery", "kickoff", "corner", "throw_in", "goal_kick", "free_kick", "save", "goal"}

app = FastAPI(title="Inside the Game: Synthetic Match Insights Engine")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


def _model_label(client: object) -> str:
    """The deployment name for a real model, "offline" for templates."""
    return getattr(client, "deployment", None) or getattr(client, "name", "offline")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok", "model": _model_label(get_client())}


@app.get("/api/teams")
def teams() -> list[dict]:
    return [
        {
            "id": t.id,
            "name": t.name,
            "short_name": t.short_name,
            "colors": list(t.colors),
            "formation": t.formation,
            "players": [{"id": p.id, "name": p.name, "number": p.number, "position": p.position} for p in t.players],
        }
        for t in TEAMS.values()
    ]


def _sse(kind: str, data: object) -> str:
    return f"event: {kind}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _pitch_event(e: dict) -> dict:
    keep = ("event_id", "t", "minute", "second", "type", "team_id", "player_id", "x", "y", "end_x", "end_y", "outcome")
    return {k: e[k] for k in keep if k in e}


async def _stream(home: str, away: str, seed: int, speed: float, profile: Profile) -> AsyncIterator[str]:
    events = [e.to_dict() for e in simulate_match(TEAMS[home], TEAMS[away], MatchConfig(seed=seed, match_id=f"{home}-{away}-{seed}"))]
    crew = Crew(client=get_client(), profiles=[profile])
    board = crew.board
    jobs: asyncio.Queue = asyncio.Queue()
    cues: list[dict] = []
    sent = {"cue": 0, "line": 0, "recap": 0, "trace": 0}

    async def agents_worker() -> None:
        # Moments are independent, so a burst of them is worked on together;
        # a recap waits for every earlier moment because it reads their insights.
        slots = asyncio.Semaphore(AGENT_CONCURRENCY)
        running: set[asyncio.Task] = set()

        async def work(job: dict) -> None:
            async with slots:
                cues.extend(await asyncio.to_thread(crew.react, job))

        while (job := await jobs.get()) is not None:
            if "recap" in job:
                await asyncio.gather(*running)
            task = asyncio.create_task(work(job))
            running.add(task)
            task.add_done_callback(running.discard)
        await asyncio.gather(*running)

    def flush() -> Iterator[str]:
        for kind, items in (("cue", cues), ("line", board.commentary), ("recap", board.recaps), ("trace", board.trace)):
            n = len(items)
            for item in items[sent[kind]:n]:
                yield _sse(kind, item)
            sent[kind] = n

    worker = asyncio.create_task(agents_worker())
    try:
        yield _sse("meta", {"match": events[0]["metrics"], "profile": profile.to_dict(), "model": _model_label(crew.client)})
        last_state_t = -999.0
        prev_t = events[0]["t"]
        for e in events:
            gap = max(0.0, e["t"] - prev_t) / speed
            prev_t = e["t"]
            if gap:
                await asyncio.sleep(min(gap, 4.0))

            for job in crew.observe(e):
                jobs.put_nowait(job)
            if e["type"] in PITCH_EVENTS:
                yield _sse("event", _pitch_event(e))
            if e["t"] - last_state_t >= 20 or e["type"] in ("goal", "period_end", "match_end"):
                last_state_t = e["t"]
                yield _sse("state", crew.state.snapshot())
            for chunk in flush():
                yield chunk
        jobs.put_nowait(None)
        while not worker.done():  # let the agents finish the last moments and the recap
            await asyncio.sleep(0.25)
            for chunk in flush():
                yield chunk
        worker.result()
        for chunk in flush():
            yield chunk
        yield _sse("end", {"final": crew.state.snapshot()["score"]})
    finally:
        worker.cancel()


@app.get("/api/stream")
async def stream(
    home: str = "NBR",
    away: str = "ASH",
    seed: int = 7,
    speed: float = Query(20.0, ge=1, le=600),
    mode: str = "casual",
    lang: str = "en",
    team: str | None = None,
    player: str | None = None,
) -> StreamingResponse:
    if home not in TEAMS or away not in TEAMS or home == away:
        raise HTTPException(400, "pick two different clubs")
    if mode not in MODES:
        raise HTTPException(400, f"mode must be one of {sorted(MODES)}")
    profile = Profile(id=f"{mode}-{lang}", mode=mode, language=lang[:5], favorite_team=team or None, favorite_player=player or None)
    return StreamingResponse(
        _stream(home, away, seed, speed, profile),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
