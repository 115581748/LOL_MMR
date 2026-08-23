from __future__ import annotations

import argparse
import csv
import json
import time
from datetime import datetime, timezone
from pathlib import Path


RATE_FIELDS = ("late_champion_damage_per_min", "late_damage_taken_per_min")


def number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def late_rate_values(row: dict) -> dict:
    duration = number(row.get("duration_min"))
    split = number(row.get("phase_split_minute")) or 25
    late_minutes = max(0, duration - split) if duration is not None else 0
    damage = number(row.get("late_champion_damage"))
    taken = number(row.get("late_damage_taken"))
    if late_minutes <= 0:
        return {"late_duration_min": "", RATE_FIELDS[0]: "", RATE_FIELDS[1]: ""}
    return {
        "late_duration_min": round(late_minutes, 4),
        RATE_FIELDS[0]: round(damage / late_minutes, 4) if damage is not None else "",
        RATE_FIELDS[1]: round(taken / late_minutes, 4) if taken is not None else "",
    }


def derive(input_path: Path, output_path: Path, manifest_path: Path | None = None) -> dict:
    temporary = output_path.with_name(f".{output_path.name}.late-rates.next")
    rows = available = 0
    with input_path.open(encoding="utf-8", newline="") as source, temporary.open("w", encoding="utf-8", newline="") as target:
        reader = csv.DictReader(source)
        fieldnames = list(reader.fieldnames or [])
        for field in ("late_duration_min", *RATE_FIELDS):
            if field not in fieldnames:
                fieldnames.append(field)
        writer = csv.DictWriter(target, fieldnames=fieldnames)
        writer.writeheader()
        for row in reader:
            values = late_rate_values(row)
            row.update(values)
            writer.writerow(row)
            rows += 1
            available += values[RATE_FIELDS[0]] != ""
    for attempt in range(30):
        try:
            temporary.replace(output_path)
            break
        except PermissionError:
            if attempt == 29:
                raise
            time.sleep(1)

    if manifest_path and manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["generated_at_utc"] = datetime.now(timezone.utc).isoformat()
        manifest["late_efficiency_definition"] = {
            "start_minute": 25,
            "denominator": "actual game duration in minutes minus late-phase start minute",
            "raw_totals_retained": ["late_champion_damage", "late_damage_taken"],
            "primary_metrics": list(RATE_FIELDS),
        }
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"rows": rows, "available": available}


def main() -> None:
    parser = argparse.ArgumentParser(description="Derive 25+ minute damage and damage-taken rates")
    parser.add_argument("--input", type=Path, default=Path("data/processed/player_matches.csv"))
    parser.add_argument("--output", type=Path, default=Path("data/processed/player_matches.csv"))
    parser.add_argument("--manifest", type=Path, default=Path("data/processed/player_matches.manifest.json"))
    args = parser.parse_args()
    result = derive(args.input, args.output, args.manifest)
    print(
        f"derived late damage rates for {result['available']}/{result['rows']} rows "
        f"using actual minutes after 25"
    )


if __name__ == "__main__":
    main()
