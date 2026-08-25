from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from riot_model.client import RiotClient
from riot_model.features import extract_player_match
from riot_model.settings import load_settings
from tools.build_conditional_model import (
    PHASE_METRICS,
    metric_stats,
    number,
    patch_of,
    phase_metrics,
)


def public_match(row: dict, index: int):
    split_minute = int(number(row.get("phase_split_minute")) or 30)
    fields = {
        "matchRef": f"recent-{index + 1:02d}",
        "gameStartMs": int(float(row.get("game_start_ms") or 0)),
        "patch": patch_of(row.get("game_version")),
        "durationMin": number(row.get("duration_min")),
        "champion": row.get("champion"),
        "position": row.get("position"),
        "opponentChampion": row.get("opponent_champion"),
        "opponentPosition": row.get("opponent_position"),
        "win": bool(int(row.get("win") or 0)),
        "phaseSplitMinute": split_minute,
    }
    for phase in PHASE_METRICS:
        for metric in phase_metrics(phase, row.get("position")):
            fields[metric] = number(row.get(metric))
            fields[f"opponent_{metric}"] = number(row.get(f"opponent_{metric}"))
    if (fields["durationMin"] or 0) < split_minute:
        for metric in phase_metrics("LATE", row.get("position")):
            fields[metric] = None
            fields[f"opponent_{metric}"] = None
    return fields


def primary_profile(rows: list[dict]):
    position_counts = Counter(row.get("position") for row in rows if row.get("position"))
    primary_position = position_counts.most_common(1)[0][0] if position_counts else None
    champion_counts = Counter(
        row.get("champion") for row in rows
        if row.get("champion") and row.get("position") == primary_position
    )
    primary_champion = champion_counts.most_common(1)[0][0] if champion_counts else None
    return {
        "primaryPosition": primary_position,
        "primaryPositionMatches": position_counts.get(primary_position, 0),
        "primaryChampion": primary_champion,
        "primaryChampionPositionMatches": champion_counts.get(primary_champion, 0),
    }


def summaries(rows: list[dict], conditional_parameters: dict, profile: dict):
    split_minute = int(conditional_parameters["late_phase_start_minute"])
    output = {}
    primary_position = profile["primaryPosition"]
    primary_champion = profile["primaryChampion"]
    scopes = {
        "PRIMARY_POSITION": [row for row in rows if row.get("position") == primary_position],
        "PRIMARY_CHAMPION_POSITION": [
            row for row in rows
            if row.get("position") == primary_position and row.get("champion") == primary_champion
        ],
    }
    for scope, selected in scopes.items():
        phase_output = {}
        for phase in PHASE_METRICS:
            metrics = phase_metrics(phase, primary_position)
            phase_rows = selected if phase != "LATE" else [
                row for row in selected if (number(row.get("duration_min")) or 0) >= split_minute
            ]
            metric_summaries = {}
            for metric in metrics:
                values = [number(row.get(metric)) for row in phase_rows]
                available = [value for value in values if value is not None]
                if available:
                    metric_summaries[metric] = metric_stats(available, len(phase_rows), conditional_parameters)
            phase_output[phase] = {"sampleSize": len(phase_rows), "metrics": metric_summaries}
        output[scope] = phase_output
    return output


def case_payload(
    rows: list[dict],
    *,
    riot_id: str,
    platform: str,
    requested_matches: int,
    conditional_parameters: dict,
) -> dict:
    split_minute = int(conditional_parameters["late_phase_start_minute"])
    rows.sort(key=lambda row: int(float(row.get("game_start_ms") or 0)), reverse=True)
    profile = primary_profile(rows)
    return {
        "meta": {
            "generatedAtUtc": datetime.now(timezone.utc).isoformat(),
            "riotId": riot_id,
            "platform": platform,
            "requestedMatches": requested_matches,
            "rankedSoloMatches": len(rows),
            **profile,
            "latePhaseStartMinute": split_minute,
            "privacy": "Aggregated statistics and match-level behavioural metrics only; PUUID is not exported.",
        },
        "summaries": summaries(rows, conditional_parameters, profile),
        "matches": [public_match(row, index) for index, row in enumerate(rows)],
    }


def write_payload(payload: dict, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write("window.PLAYER_CASE=" + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + ";\n")


def build(args):
    settings = load_settings(args.config)
    conditional_parameters = settings["conditional_model"]
    split_minute = int(conditional_parameters["late_phase_start_minute"])
    client = RiotClient(os.environ.get("RIOT_API_KEY", ""), args.platform, args.cache_dir)
    account = client.account_by_riot_id(args.riot_id, args.tag_line)
    puuid = account["puuid"]
    rows = []
    requested_ids = client.match_ids(puuid, args.matches)
    for match_id in requested_ids:
        match = client.match(match_id)
        timeline = client.timeline(match_id)
        extracted = extract_player_match(
            match,
            timeline,
            puuid,
            {"tier": "LOCAL_CASE", "rank": "", "leaguePoints": 0},
            late_start_minute=split_minute,
        )
        if not extracted:
            continue
        late_fights = number(extracted.get("late_teamfights")) or 0
        late_participations = number(extracted.get("late_teamfight_participations")) or 0
        extracted["late_teamfight_participation_rate"] = late_participations / late_fights if late_fights else None
        rows.append(extracted)
    payload = case_payload(
        rows,
        riot_id=f"{account.get('gameName', args.riot_id)}#{account.get('tagLine', args.tag_line)}",
        platform=args.platform,
        requested_matches=len(requested_ids),
        conditional_parameters=conditional_parameters,
    )
    output = Path(args.output)
    write_payload(payload, output)
    profile = primary_profile(rows)
    print(
        f"wrote {len(rows)} recent ranked-solo matches for {payload['meta']['riotId']} "
        f"({profile['primaryPositionMatches']} {profile['primaryPosition']}, "
        f"{profile['primaryChampionPositionMatches']} {profile['primaryChampion']}) to {output}"
    )


def main():
    parser = argparse.ArgumentParser(description="Build a public local-player comparison case")
    parser.add_argument("--config", default="config/model-parameters.json")
    parser.add_argument("--platform", default="oc1")
    parser.add_argument("--riot-id", required=True)
    parser.add_argument("--tag-line", required=True)
    parser.add_argument("--matches", type=int, default=20)
    parser.add_argument("--cache-dir", default="data/cache")
    parser.add_argument("--output", default="assets/player-case.js")
    build(parser.parse_args())


if __name__ == "__main__":
    main()
