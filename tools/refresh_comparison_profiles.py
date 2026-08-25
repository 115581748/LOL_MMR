from __future__ import annotations

import argparse
import csv
import json
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from riot_model.settings import load_settings
from tools.build_conditional_model import (
    PHASE_METRICS,
    build_profile,
    group_key,
    group_specs,
    number,
    patch_of,
    player_case_pairs,
    rank_band,
    unique_player_matches,
)


PREFIX = "window.CONDITIONAL_MODEL="


def load_model(path: Path) -> dict:
    source = path.read_text(encoding="utf-8").strip()
    if not source.startswith(PREFIX) or not source.endswith(";"):
        raise ValueError(f"Unexpected conditional model wrapper: {path}")
    return json.loads(source[len(PREFIX):-1])


def write_model(payload: dict, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_name(f".{output_path.name}.comparison.next")
    temporary.write_text(
        PREFIX + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + ";\n",
        encoding="utf-8",
    )
    for attempt in range(30):
        try:
            temporary.replace(output_path)
            break
        except PermissionError:
            if attempt == 29:
                raise
            time.sleep(1)


def refresh(model_path: Path, player_case_path: Path, output_path: Path) -> dict:
    payload = load_model(model_path)
    pairs = player_case_pairs(player_case_path)
    selected = {}
    for key, profile in payload.get("profiles", {}).items():
        parts = key.split("|")
        if len(parts) != 6 or parts[0] != "CHAMPION_ALL_PATCH":
            continue
        if (parts[2], parts[3]) in pairs:
            selected[key] = profile

    required = {
        f"CHAMPION_ALL_PATCH|ALL|{champion}|{position}|ALL|{phase}"
        for champion, position in pairs
        for phase in PHASE_METRICS
    }
    missing = sorted(required - selected.keys())
    if missing:
        raise RuntimeError(
            "Existing conditional profiles cannot cover the new player case; "
            f"run the full conditional model rebuild (missing {len(missing)} required profiles)."
        )

    payload["comparisonProfiles"] = selected
    meta = payload.setdefault("meta", {})
    meta["generatedAtUtc"] = datetime.now(timezone.utc).isoformat()
    meta["comparisonProfileCount"] = len(selected)
    meta["comparisonPlayerPairs"] = [list(pair) for pair in sorted(pairs)]

    write_model(payload, output_path)
    return {"pairs": len(pairs), "profiles": len(selected)}


def rebuild_from_csv(
    model_path: Path,
    player_case_path: Path,
    player_csv_path: Path,
    config_path: Path,
    output_path: Path,
) -> dict:
    payload = load_model(model_path)
    pairs = player_case_pairs(player_case_path)
    parameters = load_settings(config_path)["conditional_model"]
    split_minute = int(parameters["late_phase_start_minute"])
    comparison_parameters = {
        **parameters,
        "minimum_group_samples": int(parameters["comparison_minimum_samples"]),
    }
    grouped = defaultdict(list)
    with player_csv_path.open(encoding="utf-8", newline="") as handle:
        for source in csv.DictReader(handle):
            if (source.get("champion"), source.get("position")) not in pairs:
                continue
            row = dict(source)
            row["patch"] = patch_of(source.get("game_version"))
            row["rankBand"] = rank_band(source)
            row["gameStartMs"] = int(float(source.get("game_start_ms") or 0))
            late_fights = number(source.get("late_teamfights")) or 0
            late_participations = number(source.get("late_teamfight_participations")) or 0
            row["late_teamfight_participation_rate"] = late_participations / late_fights if late_fights else None
            for phase in ("EARLY", "MID", "LATE"):
                if phase == "LATE" and (number(row.get("duration_min")) or 0) < split_minute:
                    continue
                for parts in group_specs(row, phase):
                    if parts[0] == "CHAMPION_ALL_PATCH":
                        grouped[parts].append(row)

    selected = {}
    minimum = int(parameters["comparison_minimum_samples"])
    for parts, rows in sorted(grouped.items()):
        unique_rows = unique_player_matches(rows)
        if len(unique_rows) >= minimum:
            selected[group_key(parts)] = build_profile(parts, unique_rows, comparison_parameters)

    payload["comparisonProfiles"] = selected
    meta = payload.setdefault("meta", {})
    meta["generatedAtUtc"] = datetime.now(timezone.utc).isoformat()
    meta["comparisonProfileCount"] = len(selected)
    meta["comparisonPlayerPairs"] = [list(pair) for pair in sorted(pairs)]
    write_model(payload, output_path)
    return {"pairs": len(pairs), "profiles": len(selected)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh player-specific fixed comparison profiles")
    parser.add_argument("--model", type=Path, default=Path("assets/conditional-model.js"))
    parser.add_argument("--player-case", type=Path, default=Path("assets/player-case.js"))
    parser.add_argument("--output", type=Path, default=Path("assets/conditional-model.js"))
    parser.add_argument("--player-csv", type=Path)
    parser.add_argument("--config", type=Path, default=Path("config/model-parameters.json"))
    args = parser.parse_args()
    result = rebuild_from_csv(args.model, args.player_case, args.player_csv, args.config, args.output) if args.player_csv else refresh(args.model, args.player_case, args.output)
    print(
        f"refreshed {result['profiles']} fixed comparison profiles "
        f"for {result['pairs']} champion-position pairs in {args.output}"
    )


if __name__ == "__main__":
    main()
