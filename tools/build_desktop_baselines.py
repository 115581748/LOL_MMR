from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from riot_model.settings import load_settings
from tools.build_conditional_model import confidence, metric_stats, number, phase_metrics


def build(args) -> dict:
    settings = load_settings(args.config)
    parameters = settings["conditional_model"]
    split_minute = int(parameters["late_phase_start_minute"])
    minimum = int(parameters["comparison_minimum_samples"])
    groups: dict[tuple[str, str, str], dict] = {}

    with args.player_csv.open(encoding="utf-8", newline="") as handle:
        for source in csv.DictReader(handle):
            champion = source.get("champion")
            position = source.get("position")
            if not champion or not position:
                continue
            for phase in ("EARLY", "MID", "LATE"):
                if phase == "LATE" and (number(source.get("duration_min")) or 0) < split_minute:
                    continue
                key = (champion, position, phase)
                group = groups.setdefault(key, {"sampleSize": 0, "metrics": defaultdict(list)})
                group["sampleSize"] += 1
                late_fights = number(source.get("late_teamfights")) or 0
                late_participations = number(source.get("late_teamfight_participations")) or 0
                for metric in phase_metrics(phase, position):
                    value = (
                        late_participations / late_fights
                        if metric == "late_teamfight_participation_rate" and late_fights
                        else number(source.get(metric))
                    )
                    if value is not None:
                        group["metrics"][metric].append(value)

    profiles = {}
    for (champion, position, phase), group in sorted(groups.items()):
        sample_size = group["sampleSize"]
        if sample_size < minimum:
            continue
        metrics = {
            metric: metric_stats(values, sample_size, parameters)
            for metric, values in group["metrics"].items()
            if values
        }
        profiles[f"{champion}|{position}|{phase}"] = {
            "champion": champion,
            "position": position,
            "phase": phase,
            "sampleSize": sample_size,
            "confidence": confidence(sample_size, parameters),
            "metrics": metrics,
        }

    payload = {
        "meta": {
            "generatedAtUtc": datetime.now(timezone.utc).isoformat(),
            "sourceRows": sum(1 for _ in args.player_csv.open(encoding="utf-8")) - 1,
            "profileCount": len(profiles),
            "minimumSamples": minimum,
            "latePhaseStartMinute": split_minute,
            "population": "OCE ranked solo players sampled at Diamond IV or above",
        },
        "profiles": profiles,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {len(profiles)} desktop champion-position-phase profiles to {args.output}")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Build compact D4+ baselines for the desktop application")
    parser.add_argument("--config", type=Path, default=Path("config/model-parameters.json"))
    parser.add_argument("--player-csv", type=Path, default=Path("data/processed/player_matches.csv"))
    parser.add_argument("--output", type=Path, default=Path("desktop/all-champion-baselines.json"))
    build(parser.parse_args())


if __name__ == "__main__":
    main()
