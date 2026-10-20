"""Run the crew over a match file.

    python -m agents data/sample_match_NBR_ASH.jsonl -o out/board.json
    python -m agents data/sample_match_NBR_ASH.jsonl --live --speed 30

Uses the Foundry model when AZURE_OPENAI_* variables are set, offline
templates otherwise (force offline with INSIGHTS_OFFLINE=1).
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
import time
from pathlib import Path

from .crew import Crew, Profile
from .llm import get_client

DEFAULT_PROFILES = [
    Profile("analyst-en", "analyst", "en"),
    Profile("fan-es", "casual", "es"),
    Profile("kids-en", "kids", "en"),
]


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="agents", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file")
    ap.add_argument("-o", "--output", help="write the full blackboard as JSON")
    ap.add_argument("--live", action="store_true", help="print overlay cues as the match plays")
    ap.add_argument("--speed", type=float, default=30.0)
    args = ap.parse_args(argv)

    events = [json.loads(line) for line in Path(args.file).read_text(encoding="utf-8").splitlines() if line.strip()]
    client = get_client()
    crew = Crew(client=client, profiles=DEFAULT_PROFILES)
    print(f"model: {client.name}", file=sys.stderr)

    prev = events[0]["t"]
    for e in events:
        if args.live:
            time.sleep(min(max(0.0, e["t"] - prev) / args.speed, 3.0))
            prev = e["t"]
        for cue in crew.ingest(e):
            if args.live:
                print(f"[{e['minute']:>2}'] {cue['profile']:<11} {cue['body']}", flush=True)

    board = crew.board
    for r in board.recaps:
        print(f"\n{r['title']}\n{r['summary']}", file=sys.stderr)
    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(dataclasses.asdict(board), ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"wrote {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
