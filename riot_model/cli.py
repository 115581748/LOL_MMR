from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from pathlib import Path
from collections import Counter

from .benchmark import build_benchmarks, read_csv, write_csv, write_manifest
from .client import RiotAPIError, RiotClient
from .dashboard import export_dashboard
from .features import extract_match_replay, extract_player_match
from .settings import load_settings


def diamond_plus_entries(client, max_pages=0, league_cache_max_age_minutes=360):
    """Enumerate the current Solo/Duo ladder from Diamond IV through Challenger."""
    by_id = {}
    cache_max_age_seconds = None if league_cache_max_age_minutes < 0 else league_cache_max_age_minutes * 60
    for division in ("IV", "III", "II", "I"):
        page = 1
        while not max_pages or page <= max_pages:
            batch = client.league_entries("DIAMOND", division, page, cache_max_age_seconds=cache_max_age_seconds)
            if not batch:
                break
            for entry in batch:
                key = entry.get("puuid") or entry.get("summonerId")
                if key: by_id[key] = entry
            page += 1
    for tier in ("master", "grandmaster", "challenger"):
        for entry in client.top_league(tier).get("entries", []):
            entry = {**entry, "tier": tier.upper(), "rank": "I"}
            key = entry.get("puuid") or entry.get("summonerId")
            if key: by_id[key] = entry
    return list(by_id.values())


def _checkpoint_rows(path):
    path = Path(path)
    if not path.exists(): return []
    unique = {}
    with path.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            row = json.loads(line)
            identity = (row.get("puuid"), row.get("match_id"))
            unique[identity] = row
    return list(unique.values())


def _checkpoint_index(path):
    """Return lightweight identity state without retaining full feature rows."""
    path = Path(path)
    completed = set()
    completed_counts = Counter()
    seen_matches = set()
    if not path.exists():
        return completed, completed_counts, seen_matches
    with path.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            row = json.loads(line)
            identity = (row.get("puuid"), row.get("match_id"))
            if identity in completed:
                continue
            completed.add(identity)
            completed_counts[identity[0]] += 1
            seen_matches.add(identity[1])
    return completed, completed_counts, seen_matches


def _materialize_checkpoint(checkpoint, output):
    """Stream the latest version of each player-match row into a CSV."""
    checkpoint = Path(checkpoint)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.materialize.next")
    latest_line = {}
    fieldnames = []
    seen_fields = set()
    players = set()
    matches = set()

    with checkpoint.open(encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            identity = (row.get("puuid"), row.get("match_id"))
            latest_line[identity] = line_number
            players.add(identity[0])
            matches.add(identity[1])
            for key in row:
                if key not in seen_fields:
                    fieldnames.append(key)
                    seen_fields.add(key)

    try:
        with (
            checkpoint.open(encoding="utf-8") as source,
            temporary.open("w", encoding="utf-8", newline="") as target,
        ):
            writer = csv.DictWriter(target, fieldnames=fieldnames)
            writer.writeheader()
            rows = 0
            for line_number, line in enumerate(source, 1):
                if not line.strip():
                    continue
                row = json.loads(line)
                identity = (row.get("puuid"), row.get("match_id"))
                if latest_line.get(identity) != line_number:
                    continue
                writer.writerow(row)
                rows += 1
        for attempt in range(30):
            try:
                temporary.replace(output)
                break
            except PermissionError:
                if attempt == 29:
                    raise
                time.sleep(1)
    except BaseException:
        try:
            temporary.unlink(missing_ok=True)
        except PermissionError:
            pass
        raise
    return {"players": len(players), "matches": len(matches), "rows": rows}


def collect(args):
    collection = args.settings["collection"]
    args.platform = args.platform or collection["platform"]
    args.population = args.population or collection["population"]
    args.matches_per_player = args.matches_per_player or collection["matches_per_player"]
    args.match_history_count = args.match_history_count or collection["match_history_count"]
    if args.league_cache_max_age_minutes is None:
        args.league_cache_max_age_minutes = collection["league_cache_max_age_minutes"]
    client = RiotClient(os.environ.get("RIOT_API_KEY", ""), args.platform, args.cache_dir)
    if args.population == "diamond-plus":
        entries = diamond_plus_entries(client, args.max_diamond_pages, args.league_cache_max_age_minutes)
    else:
        entries = client.top_league(args.tier).get("entries", [])
    entries = sorted(entries, key=lambda x: x.get("leaguePoints", 0), reverse=True)
    if args.players: entries = entries[:args.players]
    checkpoint = Path(args.checkpoint); checkpoint.parent.mkdir(parents=True, exist_ok=True)
    completed, completed_counts, seen_matches = _checkpoint_index(checkpoint)
    cycle_counts = Counter()
    failed_matches = set()
    rank_by_puuid = {entry["puuid"]: entry for entry in entries if entry.get("puuid")}
    for index, entry in enumerate(entries, 1):
        puuid = entry.get("puuid")
        if not puuid:
            puuid = client.summoner_by_id(entry["summonerId"])["puuid"]
            rank_by_puuid[puuid] = entry
        if args.incremental and cycle_counts[puuid] >= args.matches_per_player:
            continue
        if not args.incremental and completed_counts[puuid] >= args.matches_per_player:
            continue
        print(f"[{index}/{len(entries)}] collecting {entry.get('leaguePoints', 0)} LP player")
        history_count = args.match_history_count or args.matches_per_player
        try:
            match_ids = client.match_ids(puuid, history_count)
        except RiotAPIError as exc:
            print(f"skipping match history for player {index}: {exc}", file=sys.stderr)
            continue
        for match_id in match_ids:
            if args.incremental and cycle_counts[puuid] >= args.matches_per_player:
                break
            if (puuid, match_id) in completed:
                continue
            if match_id in failed_matches:
                continue
            seen_matches.add(match_id)
            try:
                match = client.match(match_id)
                timeline = client.timeline(match_id)
            except RiotAPIError as exc:
                failed_matches.add(match_id)
                print(f"skipping unavailable match {match_id}: {exc}", file=sys.stderr)
                continue
            replay_path = Path(args.replay_dir) / f"{match_id}.json"
            if not replay_path.exists():
                replay = extract_match_replay(match, timeline)
                if replay:
                    replay_path.parent.mkdir(parents=True, exist_ok=True)
                    replay_path.write_text(json.dumps(replay, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            # One Match-v5 response can contribute records for every D4+ player in
            # that match. This preserves the player-match unit while avoiding the
            # dominant duplicate-request cost in a full-ladder crawl.
            for participant in match.get("info", {}).get("participants", []):
                participant_puuid = participant.get("puuid")
                participant_rank = rank_by_puuid.get(participant_puuid)
                if not participant_rank:
                    continue
                if args.incremental and cycle_counts[participant_puuid] >= args.matches_per_player:
                    continue
                if not args.incremental and completed_counts[participant_puuid] >= args.matches_per_player:
                    continue
                if (participant_puuid, match_id) in completed:
                    continue
                row = extract_player_match(
                    match,
                    timeline,
                    participant_puuid,
                    participant_rank,
                    late_start_minute=args.settings["conditional_model"]["late_phase_start_minute"],
                )
                if row:
                    completed.add((participant_puuid, match_id)); completed_counts[participant_puuid] += 1; cycle_counts[participant_puuid] += 1
                    with checkpoint.open("a", encoding="utf-8") as f:
                        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    materialized = _materialize_checkpoint(checkpoint, args.output)
    write_manifest(Path(args.output).with_suffix(".manifest.json"), platform=args.platform,
                   players=len(entries), matches=len(seen_matches), rows=materialized["rows"], settings=args.settings)
    print(f"wrote {materialized['rows']} rows to {args.output}")


def model(args):
    rows = read_csv(args.input)
    model_settings = args.settings["model"]
    minimum_samples = args.minimum_samples or model_settings["minimum_samples"]
    iqr_multiplier = args.outlier_iqr_multiplier or model_settings["outlier_iqr_multiplier"]
    result = build_benchmarks(rows, minimum_samples, iqr_multiplier)
    write_csv(args.output, result)
    print(f"wrote {len(result)} champion-position metric parameters to {args.output}")


def finalize(args):
    args.platform = args.platform or args.settings["collection"]["platform"]
    materialized = _materialize_checkpoint(args.checkpoint, args.output)
    write_manifest(Path(args.output).with_suffix(".manifest.json"), platform=args.platform,
                   players=materialized["players"], matches=materialized["matches"], rows=materialized["rows"], settings=args.settings)
    print(f"materialized {materialized['rows']} checkpoint rows to {args.output}")


def dashboard(args):
    count = export_dashboard(args.input, args.output, args.core_only, args.config)
    print(f"wrote {count} dashboard parameters to {args.output}")


def main():
    parser = argparse.ArgumentParser(description="Build high-rank LoL champion/position behavioural benchmarks")
    sub = parser.add_subparsers(required=True)
    p = sub.add_parser("collect"); p.set_defaults(func=collect)
    p.add_argument("--config", default="config/model-parameters.json")
    p.add_argument("--platform"); p.add_argument("--population", choices=("diamond-plus", "apex"))
    p.add_argument("--tier", default="challenger", help="used only when --population apex")
    p.add_argument("--players", type=int, default=0, help="0 means the complete enumerated population")
    p.add_argument("--max-diamond-pages", type=int, default=0, help="0 means paginate until Riot returns an empty page")
    p.add_argument("--matches-per-player", type=int)
    p.add_argument("--match-history-count", type=int, help="recent match IDs to scan; omit to use config")
    p.add_argument("--incremental", action="store_true", help="append unseen recent matches even when a player already has the target count")
    p.add_argument("--league-cache-max-age-minutes", type=int, help="refresh Diamond roster pages older than this; -1 keeps them indefinitely")
    p.add_argument("--checkpoint", default="data/checkpoints/player_matches.jsonl")
    p.add_argument("--replay-dir", default="data/replays")
    p.add_argument("--cache-dir", default="data/cache"); p.add_argument("--output", default="data/processed/player_matches.csv")
    p = sub.add_parser("model"); p.set_defaults(func=model)
    p.add_argument("--config", default="config/model-parameters.json")
    p.add_argument("--input", default="data/processed/player_matches.csv"); p.add_argument("--output", default="data/models/champion_role_benchmarks.csv")
    p.add_argument("--minimum-samples", type=int)
    p.add_argument("--outlier-iqr-multiplier", type=float)
    p = sub.add_parser("finalize"); p.set_defaults(func=finalize)
    p.add_argument("--config", default="config/model-parameters.json")
    p.add_argument("--platform"); p.add_argument("--checkpoint", default="data/checkpoints/player_matches.jsonl")
    p.add_argument("--output", default="data/processed/player_matches.csv")
    p = sub.add_parser("dashboard"); p.set_defaults(func=dashboard)
    p.add_argument("--config", default="config/model-parameters.json")
    p.add_argument("--input", default="data/models/champion_role_benchmarks.csv")
    p.add_argument("--output", default="assets/model-data.js")
    p.add_argument("--core-only", action="store_true", help="export only player-facing metrics for a smaller web payload")
    args = parser.parse_args(); args.settings = load_settings(args.config); args.func(args)


if __name__ == "__main__": main()
