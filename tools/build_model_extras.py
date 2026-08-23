from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path

from riot_model.benchmark import build_benchmarks
from riot_model.settings import load_settings


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def cache_index(data_root: Path, bucket: str):
    indexed = {}
    for path in sorted(data_root.glob(f"**/{bucket}/*.json")):
        indexed.setdefault(path.stem, path)
    return indexed


def all_events(timeline: dict):
    return [event for frame in timeline.get("info", {}).get("frames", []) for event in frame.get("events", [])]


def frame_at(timeline: dict, minute: int):
    frames = timeline.get("info", {}).get("frames", [])
    eligible = [frame for frame in frames if frame.get("timestamp", 0) <= minute * 60_000]
    return eligible[-1] if eligible else (frames[0] if frames else {})


def event_near_dragon(event: dict, dragon_pit: tuple[int, int], dragon_radius: int):
    position = event.get("position") or {}
    if position.get("x") is None or position.get("y") is None:
        return True
    return math.dist((position["x"], position["y"]), dragon_pit) <= dragon_radius


def teamfights(events, gap_ms: int, minimum_kills: int):
    kills = sorted((event for event in events if event.get("type") == "CHAMPION_KILL"), key=lambda event: event.get("timestamp", 0))
    groups = []
    for event in kills:
        if not groups or event.get("timestamp", 0) - groups[-1][-1].get("timestamp", 0) > gap_ms:
            groups.append([event])
        else:
            groups[-1].append(event)
    return [group for group in groups if len(group) >= minimum_kills]


def participant_in_event(event: dict, participant_id: int):
    return (
        event.get("killerId") == participant_id
        or event.get("victimId") == participant_id
        or participant_id in (event.get("assistingParticipantIds") or [])
    )


def dragon_features(events, participant_id: int, team_id: int, team_by_participant: dict[int, int], parameters: dict):
    dragon_window_ms = int(parameters["dragon_window_seconds"] * 1000)
    dragon_pit = (parameters["dragon_pit_x"], parameters["dragon_pit_y"])
    dragon_radius = parameters["dragon_radius"]
    dragons = sorted(
        (
            event
            for event in events
            if event.get("type") == "ELITE_MONSTER_KILL" and event.get("monsterType") == "DRAGON"
        ),
        key=lambda event: event.get("timestamp", 0),
    )
    champion_kills = [event for event in events if event.get("type") == "CHAMPION_KILL"]
    metrics = {
        "dragon_windows": len(dragons),
        "team_dragons_timeline": 0,
        "enemy_dragons_timeline": 0,
        "dragon_fight_windows": 0,
        "dragon_fight_participations": 0,
        "dragon_fight_kills": 0,
        "dragon_fight_deaths": 0,
        "dragon_fight_assists": 0,
        "dragon_fight_team_kills": 0,
        "dragon_fight_team_deaths": 0,
        "dragon_secures_while_participating": 0,
        "dragon_losses_while_participating": 0,
        "first_dragon_minute": dragons[0].get("timestamp", 0) / 60_000 if dragons else None,
    }
    dragon_types = Counter()
    dragon_outcomes = Counter()
    for dragon in dragons:
        timestamp = dragon.get("timestamp", 0)
        secured = dragon.get("killerTeamId") == team_id
        metrics["team_dragons_timeline" if secured else "enemy_dragons_timeline"] += 1
        if secured:
            dragon_types[dragon.get("monsterSubType") or "UNKNOWN_DRAGON"] += 1
        nearby = [
            event
            for event in champion_kills
            if abs(event.get("timestamp", 0) - timestamp) <= dragon_window_ms
            and event_near_dragon(event, dragon_pit, dragon_radius)
        ]
        contested = bool(nearby)
        involved = any(participant_in_event(event, participant_id) for event in nearby)
        if contested:
            metrics["dragon_fight_windows"] += 1
        if involved:
            metrics["dragon_fight_participations"] += 1
            metrics["dragon_secures_while_participating" if secured else "dragon_losses_while_participating"] += 1
        dragon_outcomes[("secured" if secured else "lost") + ("_contested" if contested else "_quiet")] += 1
        for event in nearby:
            killer_id = event.get("killerId")
            victim_id = event.get("victimId")
            if killer_id == participant_id:
                metrics["dragon_fight_kills"] += 1
            if victim_id == participant_id:
                metrics["dragon_fight_deaths"] += 1
            if participant_id in (event.get("assistingParticipantIds") or []):
                metrics["dragon_fight_assists"] += 1
            if team_by_participant.get(killer_id) == team_id:
                metrics["dragon_fight_team_kills"] += 1
            if team_by_participant.get(victim_id) == team_id:
                metrics["dragon_fight_team_deaths"] += 1
    participations = metrics["dragon_fight_participations"]
    team_kills = metrics["dragon_fight_team_kills"]
    metrics["dragon_secure_rate_when_present"] = (
        metrics["dragon_secures_while_participating"] / participations if participations else None
    )
    metrics["dragon_fight_kill_participation"] = (
        (metrics["dragon_fight_kills"] + metrics["dragon_fight_assists"]) / team_kills if team_kills else None
    )
    metrics["dragon_fight_survival_rate"] = (
        1 - metrics["dragon_fight_deaths"] / participations if participations else None
    )
    metrics["dragon_contest_kills_per_window"] = (
        (metrics["dragon_fight_team_kills"] + metrics["dragon_fight_team_deaths"]) / metrics["dragon_fight_windows"]
        if metrics["dragon_fight_windows"]
        else None
    )
    return metrics, dragon_types, dragon_outcomes


def teamfight_features(events, participant_id: int, parameters: dict):
    fights = teamfights(
        events,
        int(parameters["teamfight_gap_seconds"] * 1000),
        parameters["teamfight_min_kills"],
    )
    participated = [fight for fight in fights if any(participant_in_event(event, participant_id) for event in fight)]
    kills = sum(event.get("killerId") == participant_id for fight in participated for event in fight)
    deaths = sum(event.get("victimId") == participant_id for fight in participated for event in fight)
    assists = sum(participant_id in (event.get("assistingParticipantIds") or []) for fight in participated for event in fight)
    return {
        "teamfights_total": len(fights),
        "teamfight_participations_total": len(participated),
        "teamfight_participation_rate": len(participated) / len(fights) if fights else None,
        "teamfight_kills_total": kills,
        "teamfight_deaths_total": deaths,
        "teamfight_assists_total": assists,
        "teamfight_first_target_deaths_total": sum(fight[0].get("victimId") == participant_id for fight in fights),
    }


def item_catalog(path: Path):
    payload = read_json(path)
    return payload.get("data", {}), payload.get("version", "unknown")


def rune_catalog(path: Path):
    payload = read_json(path)
    styles, runes = {}, {}
    for style in payload:
        styles[str(style["id"])] = style["name"]
        for slot in style.get("slots", []):
            for rune in slot.get("runes", []):
                runes[str(rune["id"])] = rune["name"]
    return styles, runes


def spell_catalog(path: Path):
    payload = read_json(path)
    return {str(value["key"]): value["name"] for value in payload.get("data", {}).values()}


def item_sequences(participant: dict, events: list[dict], item_data: dict, starter_purchase_seconds: int):
    participant_id = participant.get("participantId")
    purchases = sorted(
        (
            (event.get("timestamp", 0), int(event.get("itemId", 0)))
            for event in events
            if event.get("participantId") == participant_id
            and event.get("type") == "ITEM_PURCHASED"
            and event.get("itemId")
        ),
        key=lambda pair: pair[0],
    )
    transforms = [
        (event.get("timestamp", 0), int(event.get("afterId", 0)))
        for event in events
        if event.get("participantId") == participant_id
        and event.get("type") == "ITEM_TRANSFORM"
        and event.get("afterId")
    ]
    acquisitions = purchases + transforms
    starters = tuple(item_id for timestamp, item_id in purchases if timestamp <= starter_purchase_seconds * 1000)
    final_items = tuple(
        int(participant.get(f"item{slot}", 0))
        for slot in range(6)
        if int(participant.get(f"item{slot}", 0) or 0) > 0
    )
    used_indexes = set()
    ordered = []
    for slot, item_id in enumerate(final_items):
        candidates = [
            (timestamp, index)
            for index, (timestamp, acquired_id) in enumerate(acquisitions)
            if acquired_id == item_id and index not in used_indexes
        ]
        if candidates:
            timestamp, index = min(candidates)
            used_indexes.add(index)
        else:
            timestamp = 10**15 + slot
        ordered.append((timestamp, item_id))
    build_order = tuple(item_id for _, item_id in sorted(ordered))
    final_build = tuple(sorted(final_items))
    return starters, build_order, final_build, final_items


def counter_values(counter: Counter, limit=8):
    total = sum(counter.values())
    return [
        {"value": value, "n": count, "share": round(count / total, 4) if total else 0}
        for value, count in counter.most_common(limit)
    ]


def counter_sequences(counter: Counter, limit=8):
    total = sum(counter.values())
    return [
        {"ids": list(value), "n": count, "share": round(count / total, 4) if total else 0}
        for value, count in counter.most_common(limit)
    ]


def quantile(values, q):
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    low, high = math.floor(position), math.ceil(position)
    return ordered[low] if low == high else ordered[low] * (high - position) + ordered[high] * (position - low)


def untrimmed_metric_benchmarks(rows, metric: str, minimum_samples: int):
    grouped = defaultdict(list)
    for row in rows:
        value = row.get(metric)
        if row.get("champion") and row.get("position") and value not in (None, ""):
            grouped[(row["champion"], row["position"])].append(float(value))
    output = []
    for (champion, position), values in sorted(grouped.items()):
        if len(values) < minimum_samples:
            continue
        p25, p75 = quantile(values, .25), quantile(values, .75)
        output.append({
            "champion": champion, "position": position, "metric": metric,
            "n_raw": len(values), "n_clean": len(values),
            "mean": round(statistics.fmean(values), 4), "median": round(statistics.median(values), 4),
            "std": round(statistics.stdev(values), 4) if len(values) > 1 else 0,
            "p25": round(p25, 4), "p75": round(p75, 4),
            "iqr_low": min(values), "iqr_high": max(values),
        })
    return output


def compact_benchmarks(rows):
    numeric = ("n_raw", "n_clean", "mean", "median", "std", "p25", "p75", "iqr_low", "iqr_high")
    output = []
    for row in rows:
        item = {"c": row["champion"], "r": row["position"], "m": row["metric"]}
        item.update({key: row[key] for key in numeric})
        output.append(item)
    return output


def build(args):
    settings = load_settings(args.config)
    parameters = settings["model"]
    minimum_samples = args.minimum_samples or parameters["minimum_samples"]
    player_csv = Path(args.player_csv)
    with player_csv.open(encoding="utf-8", newline="") as handle:
        player_rows = list(csv.DictReader(handle))
    matches = cache_index(Path(args.data_root), "matches")
    timelines = cache_index(Path(args.data_root), "timelines")

    @lru_cache(maxsize=64)
    def load_pair(match_id: str):
        match_path, timeline_path = matches.get(match_id), timelines.get(match_id)
        if not match_path or not timeline_path:
            return None, None
        return read_json(match_path), read_json(timeline_path)

    item_data, item_version = item_catalog(Path(args.item_data))
    rune_styles, runes = rune_catalog(Path(args.rune_data))
    spells = spell_catalog(Path(args.spell_data))

    counters = defaultdict(lambda: {
        "buildOrders": Counter(), "coreBuildOrders": Counter(), "finalBuilds": Counter(), "starters": Counter(),
        "summoners": Counter(), "runes": Counter(), "patches": Counter(), "ranks": Counter(),
        "results": Counter(), "dragonTypes": Counter(), "dragonOutcomes": Counter(),
        "itemSlots": [Counter() for _ in range(7)],
    })
    extra_rows = []
    used_items = set()
    matched_rows = 0
    matched_matches = set()
    for row in player_rows:
        match_id = row.get("match_id")
        match, timeline = load_pair(match_id)
        if not match or not timeline:
            continue
        participants = match.get("info", {}).get("participants", [])
        participant = next((value for value in participants if value.get("puuid") == row.get("puuid")), None)
        if not participant:
            continue
        matched_rows += 1
        matched_matches.add(match_id)
        participant_id = participant.get("participantId")
        team_id = participant.get("teamId")
        team_by_participant = {value.get("participantId"): value.get("teamId") for value in participants}
        events = all_events(timeline)
        dragons, dragon_types, dragon_outcomes = dragon_features(
            events, participant_id, team_id, team_by_participant, parameters
        )
        frame_15 = frame_at(timeline, 15)
        participant_frame_15 = frame_15.get("participantFrames", {}).get(str(participant_id), {})
        extra = {
            "match_id": match_id,
            "champion": row.get("champion"),
            "position": row.get("position"),
            "level_at_15": participant_frame_15.get("level"),
            **dragons,
            **teamfight_features(events, participant_id, parameters),
        }
        extra_rows.append(extra)

        key = f"{row.get('champion')}|{row.get('position')}"
        profile = counters[key]
        starters, build_order, final_build, final_items = item_sequences(
            participant, events, item_data, parameters["starter_purchase_seconds"]
        )
        if starters:
            profile["starters"][starters] += 1
            used_items.update(starters)
        if build_order:
            profile["buildOrders"][build_order] += 1
            core_build_order = tuple(
                item_id
                for item_id in build_order
                if (item_data.get(str(item_id), {}).get("gold") or {}).get("total", 0)
                >= parameters["core_item_min_gold"]
            )
            if core_build_order:
                profile["coreBuildOrders"][core_build_order] += 1
            profile["finalBuilds"][final_build] += 1
            used_items.update(build_order)
        for slot in range(7):
            item_id = int(participant.get(f"item{slot}", 0) or 0)
            if item_id:
                profile["itemSlots"][slot][str(item_id)] += 1
                used_items.add(item_id)
        summoners = tuple(sorted((str(participant.get("summoner1Id", 0)), str(participant.get("summoner2Id", 0)))))
        profile["summoners"][summoners] += 1
        perks = participant.get("perks", {}).get("styles", [])
        if perks:
            primary = perks[0]
            keystone = next((selection.get("perk") for slot in primary.get("selections", []) for selection in [slot] if selection.get("perk")), 0)
            secondary_style = perks[1].get("style", 0) if len(perks) > 1 else 0
            profile["runes"][(str(keystone), str(secondary_style))] += 1
        profile["patches"][row.get("game_version") or "unknown"] += 1
        profile["ranks"][f"{row.get('tier', '')} {row.get('division', '')}".strip()] += 1
        profile["results"]["胜利" if row.get("win") == "1" else "失败"] += 1
        profile["dragonTypes"].update(dragon_types)
        profile["dragonOutcomes"].update(dragon_outcomes)

    benchmark_rows = [
        row
        for row in build_benchmarks(
            extra_rows,
            minimum_samples=minimum_samples,
            iqr_multiplier=parameters["outlier_iqr_multiplier"],
        )
        if row["metric"] != "level_at_15"
    ]
    benchmark_rows.extend(untrimmed_metric_benchmarks(extra_rows, "level_at_15", minimum_samples))
    profiles = {}
    for key, profile in counters.items():
        top_k = parameters["categorical_top_k"]
        profiles[key] = {
            "buildOrders": counter_sequences(profile["buildOrders"], top_k),
            "coreBuildOrders": counter_sequences(profile["coreBuildOrders"], top_k),
            "finalBuilds": counter_sequences(profile["finalBuilds"], top_k),
            "starters": counter_sequences(profile["starters"], top_k),
            "summoners": counter_sequences(profile["summoners"], top_k),
            "runes": counter_sequences(profile["runes"], top_k),
            "patches": counter_values(profile["patches"], top_k),
            "ranks": counter_values(profile["ranks"], top_k),
            "results": counter_values(profile["results"], top_k),
            "dragonTypes": counter_values(profile["dragonTypes"], top_k),
            "dragonOutcomes": counter_values(profile["dragonOutcomes"], top_k),
            "itemSlots": [counter_values(slot, top_k) for slot in profile["itemSlots"]],
        }

    items = {}
    for item_id in sorted(used_items):
        source = item_data.get(str(item_id), {})
        items[str(item_id)] = {
            "name": source.get("name") or f"物品 {item_id}",
            "icon": (source.get("image") or {}).get("full") or f"{item_id}.png",
            "gold": (source.get("gold") or {}).get("total"),
            "tags": source.get("tags") or [],
        }
    payload = {
        "meta": {
            "matchedPlayerRows": matched_rows,
            "matchedMatches": len(matched_matches),
            "itemVersion": item_version,
            "dragonWindowSeconds": parameters["dragon_window_seconds"],
            "dragonRadius": parameters["dragon_radius"],
            "modelParameters": parameters,
            "dashboardParameters": settings["dashboard"],
            "extraNumericParameters": len(benchmark_rows),
            "profileCount": len(profiles),
        },
        "numericRows": compact_benchmarks(benchmark_rows),
        "profiles": profiles,
        "items": items,
        "spells": spells,
        "runeStyles": rune_styles,
        "runes": runes,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write("window.MODEL_EXTRAS=" + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + ";\n")
    print(
        f"wrote {len(benchmark_rows)} derived numeric parameters and {len(profiles)} categorical profiles "
        f"from {matched_rows} player rows / {len(matched_matches)} matches to {output}; "
        f"cache={load_pair.cache_info()}"
    )


def main():
    parser = argparse.ArgumentParser(description="Build local categorical and timeline-derived dashboard data")
    parser.add_argument("--config", default="config/model-parameters.json")
    parser.add_argument("--player-csv", default="data/processed/player_matches.csv")
    parser.add_argument("--data-root", default="data")
    parser.add_argument("--item-data", default="assets/item-data.json")
    parser.add_argument("--rune-data", default="assets/runes-reforged.json")
    parser.add_argument("--spell-data", default="assets/summoner-spells.json")
    parser.add_argument("--output", default="assets/model-extras.js")
    parser.add_argument("--minimum-samples", type=int)
    build(parser.parse_args())


if __name__ == "__main__":
    main()
