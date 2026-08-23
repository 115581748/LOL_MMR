from __future__ import annotations

import argparse
import json
from pathlib import Path

from riot_model.features import extract_match_replay
from tools.player_case_server import PLAYER_CASE_PREFIX, load_window_payload


def build(args) -> dict:
    player_case = load_window_payload(args.player_case, PLAYER_CASE_PREFIX)
    wanted = {
        int(match.get("gameStartMs") or 0): match.get("matchRef")
        for match in player_case.get("matches", [])
    }
    output = {}
    match_paths = args.match_file or args.cache_dir.joinpath("matches").glob("*.json")
    for match_path in match_paths:
        match = json.loads(match_path.read_text(encoding="utf-8"))
        game_start = int(match.get("info", {}).get("gameStartTimestamp") or 0)
        match_ref = wanted.get(game_start)
        if not match_ref:
            continue
        timeline_path = args.cache_dir / "timelines" / match_path.name
        if not timeline_path.exists():
            continue
        timeline = json.loads(timeline_path.read_text(encoding="utf-8"))
        replay = extract_match_replay(match, timeline)
        if replay:
            output[match_ref] = replay
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {len(output)}/{len(wanted)} bootstrap desktop replays to {args.output}")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Build anonymous minute-by-minute replays for the desktop bootstrap case")
    parser.add_argument("--player-case", type=Path, default=Path("assets/player-case.js"))
    parser.add_argument("--cache-dir", type=Path, default=Path("data/cache"))
    parser.add_argument("--match-file", type=Path, action="append")
    parser.add_argument("--output", type=Path, default=Path("desktop/bootstrap-replays.json"))
    build(parser.parse_args())


if __name__ == "__main__":
    main()
