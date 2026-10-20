"""Command line entry point.

    python -m simulator generate --home NBR --away ASH --seed 7 -o data/match.jsonl
    python -m simulator replay data/match.jsonl --speed 20
    python -m simulator summary data/match.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

from .engine import MatchConfig, simulate_match
from .teams import TEAMS


def _generate(args: argparse.Namespace) -> None:
    events = simulate_match(
        TEAMS[args.home],
        TEAMS[args.away],
        MatchConfig(seed=args.seed, match_id=args.match_id or f"{args.home}-{args.away}-{args.seed}"),
    )
    out = Path(args.output) if args.output else None
    lines = (json.dumps(e.to_dict(), ensure_ascii=False) for e in events)
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"wrote {len(events)} events to {out}", file=sys.stderr)
    else:
        for line in lines:
            print(line)


def _load(path: str) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def _replay(args: argparse.Namespace) -> None:
    """Stream events to stdout paced by the match clock."""
    events = _load(args.file)
    prev_t = events[0]["t"] if events else 0.0
    for e in events:
        gap = max(0.0, e["t"] - prev_t) / args.speed
        if gap:
            time.sleep(min(gap, 5.0))
        prev_t = e["t"]
        print(json.dumps(e, ensure_ascii=False), flush=True)


def _summary(args: argparse.Namespace) -> None:
    events = _load(args.file)
    meta = events[0]["metrics"]
    home, away = meta["home"]["id"], meta["away"]["id"]
    types = Counter(e["type"] for e in events)
    final = events[-1]["metrics"]["final_score"]
    print(f"{meta['home']['name']} {final['home']} - {final['away']} {meta['away']['name']}")
    print(f"events: {len(events)}  " + ", ".join(f"{k}={v}" for k, v in types.most_common()))
    for team in (home, away):
        passes = [e for e in events if e["type"] == "pass" and e["team_id"] == team]
        done = sum(1 for e in passes if e["outcome"] == "complete")
        shots = [e for e in events if e["type"] == "shot" and e["team_id"] == team]
        xg = sum(e["metrics"]["xg"] for e in shots)
        acc = done / len(passes) if passes else 0
        print(f"{team}: passes {len(passes)} ({acc:.0%} complete), shots {len(shots)}, xG {xg:.2f}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="simulator", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("generate", help="simulate a match and write JSONL events")
    g.add_argument("--home", default="NBR", choices=sorted(TEAMS))
    g.add_argument("--away", default="ASH", choices=sorted(TEAMS))
    g.add_argument("--seed", type=int, default=7)
    g.add_argument("--match-id")
    g.add_argument("-o", "--output")
    g.set_defaults(func=_generate)

    r = sub.add_parser("replay", help="stream a JSONL match in (accelerated) real time")
    r.add_argument("file")
    r.add_argument("--speed", type=float, default=10.0, help="match seconds per wall-clock second")
    r.set_defaults(func=_replay)

    s = sub.add_parser("summary", help="print headline stats for a JSONL match")
    s.add_argument("file")
    s.set_defaults(func=_summary)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
