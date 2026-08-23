from __future__ import annotations

import argparse
import json
from pathlib import Path

from riot_model.features import extract_player_match
from riot_model.settings import load_settings
from tools.build_player_case import case_payload, number, write_payload
from tools.player_case_server import PLAYER_CASE_PREFIX, load_window_payload


def rebuild(args) -> dict:
    settings = load_settings(args.config)
    parameters = settings["conditional_model"]
    split_minute = int(parameters["late_phase_start_minute"])
    current = load_window_payload(args.current, PLAYER_CASE_PREFIX)
    current_matches = current.get("matches", [])
    wanted_starts = {int(match.get("gameStartMs") or 0): match for match in current_matches}
    rows = []
    match_paths = args.match_file or args.cache_dir.joinpath("matches").glob("*.json")
    for match_path in match_paths:
        match = json.loads(match_path.read_text(encoding="utf-8"))
        info = match.get("info", {})
        game_start = int(info.get("gameStartTimestamp") or 0)
        public = wanted_starts.get(game_start)
        if not public:
            continue
        participant = next((
            item for item in info.get("participants", [])
            if item.get("championName") == public.get("champion")
            and (item.get("teamPosition") or item.get("individualPosition")) == public.get("position")
        ), None)
        timeline_path = args.cache_dir / "timelines" / match_path.name
        if not participant or not timeline_path.exists():
            continue
        timeline = json.loads(timeline_path.read_text(encoding="utf-8"))
        row = extract_player_match(
            match,
            timeline,
            participant.get("puuid"),
            {"tier": "LOCAL_CASE", "rank": "", "leaguePoints": 0},
            late_start_minute=split_minute,
        )
        if not row:
            continue
        late_fights = number(row.get("late_teamfights")) or 0
        late_participations = number(row.get("late_teamfight_participations")) or 0
        row["late_teamfight_participation_rate"] = late_participations / late_fights if late_fights else None
        rows.append(row)

    rows.sort(key=lambda row: int(row.get("game_start_ms") or 0), reverse=True)
    payload = case_payload(
        rows,
        riot_id=current.get("meta", {}).get("riotId", "Unknown#Unknown"),
        platform=current.get("meta", {}).get("platform", "oc1"),
        requested_matches=len(current_matches),
        conditional_parameters=parameters,
    )
    write_payload(payload, args.output)
    return {"requested": len(current_matches), "rebuilt": len(rows)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Rebuild the current public player case from cached Riot match data")
    parser.add_argument("--config", type=Path, default=Path("config/model-parameters.json"))
    parser.add_argument("--current", type=Path, default=Path("assets/player-case.js"))
    parser.add_argument("--cache-dir", type=Path, default=Path("data/cache"))
    parser.add_argument("--match-file", type=Path, action="append", help="Optional preselected cached match JSON")
    parser.add_argument("--output", type=Path, default=Path("assets/player-case.js"))
    result = rebuild(parser.parse_args())
    print(f"rebuilt {result['rebuilt']}/{result['requested']} current player matches from local cache")


if __name__ == "__main__":
    main()
