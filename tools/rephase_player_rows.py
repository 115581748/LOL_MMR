from __future__ import annotations

import argparse
import csv
import json
import time
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from riot_model.features import extract_player_match
from riot_model.settings import load_settings
from tools.build_conditional_model import cache_index, read_json


def build(args):
    settings = load_settings(args.config)
    split_minute = int(settings["conditional_model"]["late_phase_start_minute"])
    source_path = Path(args.input)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_name(f".{output_path.name}.rephase.next")
    matches = cache_index(Path(args.data_root), "matches")
    timelines = cache_index(Path(args.data_root), "timelines")
    missing = set()
    source_count = 0
    output_count = 0

    @lru_cache(maxsize=64)
    def load_pair(match_id: str):
        match_path, timeline_path = matches.get(match_id), timelines.get(match_id)
        if not match_path or not timeline_path:
            return None, None
        return read_json(match_path), read_json(timeline_path)

    try:
        with (
            source_path.open(encoding="utf-8", newline="") as source_handle,
            temporary_path.open("w", encoding="utf-8", newline="") as output_handle,
        ):
            source_reader = csv.DictReader(source_handle)
            writer = None
            for row in source_reader:
                source_count += 1
                match_id = row.get("match_id") or ""
                match, timeline = load_pair(match_id)
                if not match or not timeline:
                    missing.add(match_id)
                    continue
                rank = {
                    "tier": row.get("tier"),
                    "rank": row.get("division"),
                    "leaguePoints": row.get("league_points"),
                }
                extracted = extract_player_match(
                    match,
                    timeline,
                    row.get("puuid"),
                    rank,
                    late_start_minute=split_minute,
                )
                if not extracted:
                    continue
                if writer is None:
                    fieldnames = list(source_reader.fieldnames or [])
                    seen_fields = set(fieldnames)
                    for field in extracted:
                        if field not in seen_fields:
                            fieldnames.append(field)
                            seen_fields.add(field)
                    writer = csv.DictWriter(output_handle, fieldnames=fieldnames)
                    writer.writeheader()
                writer.writerow(extracted)
                output_count += 1
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise

    if missing or output_count != source_count:
        temporary_path.unlink(missing_ok=True)
        raise RuntimeError(
            f"Could not rephase every source row: {output_count}/{source_count} rebuilt; "
            f"missing cache matches={len(missing)}"
        )
    for attempt in range(30):
        try:
            temporary_path.replace(output_path)
            break
        except PermissionError:
            if attempt == 29:
                raise
            time.sleep(1)

    manifest_path = Path(args.manifest)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    manifest["generated_at_utc"] = datetime.now(timezone.utc).isoformat()
    manifest["phase_definition"] = {
        "EARLY": "0-15 minutes",
        "MID": f"15-{split_minute} minutes",
        "LATE": f"{split_minute}+ minutes",
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"rephased {output_count} player-match rows at minute {split_minute} to {args.output}; "
        f"cache={load_pair.cache_info()}"
    )


def main():
    parser = argparse.ArgumentParser(description="Rebuild phase metrics from cached Riot timelines")
    parser.add_argument("--config", default="config/model-parameters.json")
    parser.add_argument("--input", default="data/processed/player_matches.csv")
    parser.add_argument("--output", default="data/processed/player_matches.csv")
    parser.add_argument("--manifest", default="data/processed/player_matches.manifest.json")
    parser.add_argument("--data-root", default="data")
    build(parser.parse_args())


if __name__ == "__main__":
    main()
