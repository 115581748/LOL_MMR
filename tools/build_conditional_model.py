from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from riot_model.settings import load_settings


PHASE_METRICS = {
    "EARLY": [
        "early_gold_15", "early_xp_15", "early_cs_15",
        "early_kills", "early_deaths", "early_assists",
    ],
    "MID": [
        "mid_gold_gain", "mid_cs_gain", "mid_champion_damage",
        "mid_kills", "mid_deaths", "mid_assists", "mid_team_turrets", "mid_team_dragons",
    ],
    "LATE": [
        "late_champion_damage_per_min", "late_damage_taken_per_min", "late_kills", "late_deaths",
        "late_assists", "late_teamfight_participation_rate", "late_first_target_deaths",
    ],
}

POSITION_PHASE_METRICS = {
    "JUNGLE": {
        "EARLY": [
            "early_gold_diff_vs_enemy_jungle", "early_xp_diff_vs_enemy_jungle", "early_cs_diff_vs_enemy_jungle",
            "early_gank_takedowns", "early_gank_lanes", "early_first_gank_minute",
            "early_enemy_jungle_takedowns", "early_kill_participation_rate",
            "early_team_dragons", "early_team_void_grubs", "early_team_rift_heralds",
            "early_personal_epic_secures", "early_gank_takedown_diff_vs_enemy_jungle",
            "early_epic_monster_diff_vs_enemy_jungle",
        ],
        "MID": [
            "mid_gank_takedowns", "mid_gank_lanes", "mid_first_gank_minute",
            "mid_enemy_jungle_takedowns", "mid_kill_participation_rate",
            "mid_team_void_grubs", "mid_team_rift_heralds", "mid_personal_epic_secures",
            "mid_gank_takedown_diff_vs_enemy_jungle", "mid_epic_monster_diff_vs_enemy_jungle",
        ],
    },
}


def phase_metrics(phase: str, position: str | None = None) -> list[str]:
    return [
        *PHASE_METRICS[phase],
        *POSITION_PHASE_METRICS.get(str(position or "").upper(), {}).get(phase, []),
    ]

def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def cache_index(data_root: Path, bucket: str):
    indexed = {}
    for path in sorted(data_root.glob(f"**/{bucket}/*.json")):
        indexed.setdefault(path.stem, path)
    return indexed


def patch_of(version: str):
    parts = str(version or "unknown").split(".")
    return ".".join(parts[:2]) if len(parts) >= 2 else str(version or "unknown")


def rank_band(row: dict):
    tier = str(row.get("tier") or "").upper()
    division = str(row.get("division") or "").upper()
    if tier in {"MASTER", "GRANDMASTER", "CHALLENGER"}:
        return "MASTER_PLUS"
    if tier == "DIAMOND" and division == "I":
        return "DIAMOND_I"
    return "DIAMOND_IV_II"


def number(value):
    try:
        parsed = float(value)
        return parsed if math.isfinite(parsed) else None
    except (TypeError, ValueError):
        return None


def quantile(values, q):
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    low, high = math.floor(position), math.ceil(position)
    if low == high:
        return ordered[low]
    return ordered[low] * (high - position) + ordered[high] * (position - low)


def metric_stats(values, raw_count: int, parameters: dict):
    values = sorted(value for value in values if value is not None)
    if not values:
        return None
    lower = quantile(values, parameters["winsor_lower_quantile"])
    upper = quantile(values, parameters["winsor_upper_quantile"])
    clean = [min(upper, max(lower, value)) for value in values]
    median = statistics.median(clean)
    absolute_deviations = [abs(value - median) for value in clean]
    return {
        "n": len(values),
        "missingRate": round(1 - len(values) / raw_count, 4) if raw_count else 0,
        "mean": round(statistics.fmean(clean), 4),
        "median": round(median, 4),
        "mad": round(statistics.median(absolute_deviations), 4),
        "p10": round(quantile(clean, .10), 4),
        "p25": round(quantile(clean, .25), 4),
        "p75": round(quantile(clean, .75), 4),
        "p90": round(quantile(clean, .90), 4),
        "winsorLow": round(lower, 4),
        "winsorHigh": round(upper, 4),
    }


def pearson(pairs):
    if len(pairs) < 2:
        return None
    xs, ys = zip(*pairs)
    mean_x, mean_y = statistics.fmean(xs), statistics.fmean(ys)
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in pairs)
    denominator = math.sqrt(sum((x - mean_x) ** 2 for x in xs) * sum((y - mean_y) ** 2 for y in ys))
    return round(numerator / denominator, 4) if denominator else 0


def confidence(sample_size: int, parameters: dict):
    if sample_size >= parameters["high_confidence_samples"]:
        return "HIGH"
    if sample_size >= parameters["medium_confidence_samples"]:
        return "MEDIUM"
    return "LOW"


def group_specs(row: dict, phase: str):
    patch = row["patch"]
    champion = row["champion"]
    position = row["position"]
    for band in ("ALL", row["rankBand"]):
        yield ("EXACT", patch, champion, position, band, phase)
        yield ("CHAMPION_ALL_PATCH", "ALL", champion, position, band, phase)
        yield ("ROLE_PATCH", patch, "ALL", position, band, phase)
        yield ("ROLE_ALL", "ALL", "ALL", position, band, phase)


def group_key(parts):
    return "|".join(parts)


def stability(rows: list[dict], metrics: list[str], parameters: dict):
    ordered = sorted(rows, key=lambda row: row["gameStartMs"])
    midpoint = len(ordered) // 2
    if midpoint < parameters["minimum_group_samples"] // 2:
        return {"available": False}
    earlier, recent = ordered[:midpoint], ordered[midpoint:]
    comparisons = []
    for metric in metrics:
        all_values = [number(row.get(metric)) for row in ordered]
        early_values = [number(row.get(metric)) for row in earlier]
        recent_values = [number(row.get(metric)) for row in recent]
        all_values = [value for value in all_values if value is not None]
        early_values = [value for value in early_values if value is not None]
        recent_values = [value for value in recent_values if value is not None]
        if not all_values or not early_values or not recent_values:
            continue
        p25, p75 = quantile(all_values, .25), quantile(all_values, .75)
        scale = max(p75 - p25, abs(statistics.median(all_values)) * .05, 1e-9)
        earlier_median, recent_median = statistics.median(early_values), statistics.median(recent_values)
        normalized_shift = abs(recent_median - earlier_median) / scale
        comparisons.append({
            "metric": metric,
            "earlierMedian": round(earlier_median, 4),
            "recentMedian": round(recent_median, 4),
            "normalizedShift": round(normalized_shift, 4),
            "stable": normalized_shift <= parameters["stability_iqr_tolerance"],
        })
    return {
        "available": bool(comparisons),
        "earlierN": len(earlier),
        "recentN": len(recent),
        "stableMetricRate": round(sum(item["stable"] for item in comparisons) / len(comparisons), 4) if comparisons else None,
        "metrics": comparisons,
    }


def build_profile(parts, rows: list[dict], parameters: dict):
    scope, patch, champion, position, band, phase = parts
    metrics = phase_metrics(phase, position)
    distributions = {}
    for metric in metrics:
        values = [number(row.get(metric)) for row in rows]
        available = [value for value in values if value is not None]
        if len(available) >= parameters["minimum_group_samples"]:
            distributions[metric] = metric_stats(available, len(rows), parameters)
    correlation_metrics = [metric for metric in metrics if metric in distributions]
    correlation = []
    for metric_a in correlation_metrics:
        cells = []
        for metric_b in correlation_metrics:
            pairs = [
                (number(row.get(metric_a)), number(row.get(metric_b)))
                for row in rows
                if number(row.get(metric_a)) is not None and number(row.get(metric_b)) is not None
            ]
            cells.append(pearson(pairs))
        correlation.append(cells)
    return {
        "scope": scope,
        "patch": patch,
        "champion": champion,
        "position": position,
        "rankBand": band,
        "phase": phase,
        "sampleSize": len(rows),
        "confidence": confidence(len(rows), parameters),
        "metrics": distributions,
        "correlationMetrics": correlation_metrics,
        "correlation": correlation,
        "stability": stability(rows, correlation_metrics, parameters),
    }


def unique_player_matches(rows: list[dict]):
    unique = {}
    for row in rows:
        identity = (row.get("match_id"), row.get("puuid"))
        unique.setdefault(identity, row)
    return list(unique.values())


def player_case_pairs(path: Path):
    if not path.exists():
        return set()
    source = path.read_text(encoding="utf-8").strip()
    payload = json.loads(source[source.index("=") + 1:].rstrip(";"))
    pairs = set()
    for row in payload.get("matches", []):
        if row.get("champion") and row.get("position"):
            pairs.add((row["champion"], row["position"]))
        if row.get("opponentChampion") and row.get("opponentPosition"):
            pairs.add((row["opponentChampion"], row["opponentPosition"]))
    return pairs


def build(args):
    settings = load_settings(args.config)
    parameters = settings["conditional_model"]
    late_start_minute = int(parameters["late_phase_start_minute"])
    with Path(args.player_csv).open(encoding="utf-8", newline="") as handle:
        player_rows = list(csv.DictReader(handle))
    matched_matches = len({row["match_id"] for row in player_rows})

    grouped = defaultdict(list)
    covered_rows = 0
    patches, champions, positions, rank_bands = set(), set(), set(), set()
    for source in player_rows:
        row = dict(source)
        row["patch"] = patch_of(source.get("game_version"))
        row["rankBand"] = rank_band(source)
        row["gameStartMs"] = int(float(source.get("game_start_ms") or 0))
        late_fights = number(source.get("late_teamfights")) or 0
        late_participations = number(source.get("late_teamfight_participations")) or 0
        row["late_teamfight_participation_rate"] = late_participations / late_fights if late_fights else None
        covered_rows += 1
        patches.add(row["patch"]); champions.add(row["champion"]); positions.add(row["position"]); rank_bands.add(row["rankBand"])
        for phase in ("EARLY", "MID"):
            for parts in group_specs(row, phase):
                grouped[parts].append(row)
        if (number(row.get("duration_min")) or 0) >= late_start_minute:
            for parts in group_specs(row, "LATE"):
                grouped[parts].append(row)

    minimum = parameters["minimum_group_samples"]
    profiles = {
        group_key(parts): build_profile(parts, rows, parameters)
        for parts, rows in sorted(grouped.items())
        if len(rows) >= minimum
    }
    comparison_minimum = parameters["comparison_minimum_samples"]
    comparison_parameters = {**parameters, "minimum_group_samples": comparison_minimum}
    comparison_pairs = player_case_pairs(Path(args.player_case))
    comparison_profiles = {}
    for parts, rows in sorted(grouped.items()):
        if parts[0] != "CHAMPION_ALL_PATCH":
            continue
        if (parts[2], parts[3]) not in comparison_pairs:
            continue
        unique_rows = unique_player_matches(rows)
        if len(unique_rows) >= comparison_minimum:
            comparison_profiles[group_key(parts)] = build_profile(parts, unique_rows, comparison_parameters)
    payload = {
        "meta": {
            "generatedAtUtc": datetime.now(timezone.utc).isoformat(),
            "sourceRows": len(player_rows),
            "coveredRows": covered_rows,
            "matchedMatches": matched_matches,
            "profileCount": len(profiles),
            "comparisonProfileCount": len(comparison_profiles),
            "comparisonUniqueRows": len(unique_player_matches(player_rows)),
            "comparisonPlayerPairs": [list(pair) for pair in sorted(comparison_pairs)],
            "parameters": parameters,
            "jungleActionDefinition": {
                "effectiveGank": "jungler kill or assist on a non-jungle opponent in the phase",
                "gankAttempts": "not exported because Match-v5 Timeline has no reliable failed-gank event",
                "objectiveControl": "team DRAGON, HORDE and RIFTHERALD kill events; personal secure uses killerId",
                "opponentDelta": "player jungler value minus opposing jungler value in the same match",
            },
            "fallbackOrder": ["EXACT", "CHAMPION_ALL_PATCH", "ROLE_PATCH", "ROLE_ALL"],
            "unit": "one D4+ player-match; grouped records from the same match are not independent",
        },
        "dimensions": {
            "patches": sorted(patches, reverse=True),
            "champions": sorted(champions),
            "positions": sorted(positions),
            "rankBands": ["ALL", *sorted(rank_bands)],
            "phases": list(PHASE_METRICS),
        },
        "phaseMetrics": PHASE_METRICS,
        "positionPhaseMetrics": POSITION_PHASE_METRICS,
        "profiles": profiles,
        "comparisonProfiles": comparison_profiles,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write("window.CONDITIONAL_MODEL=" + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + ";\n")
    print(
        f"wrote {len(profiles)} phase profiles and {len(comparison_profiles)} fixed champion comparison profiles "
        f"from {covered_rows}/{len(player_rows)} rows and {matched_matches} matches to {output}"
    )


def main():
    parser = argparse.ArgumentParser(description="Build high-rank champion, position, patch and phase models")
    parser.add_argument("--config", default="config/model-parameters.json")
    parser.add_argument("--player-csv", default="data/processed/player_matches.csv")
    parser.add_argument("--data-root", default="data")
    parser.add_argument("--player-case", default="assets/player-case.js")
    parser.add_argument("--output", default="assets/conditional-model.js")
    build(parser.parse_args())


if __name__ == "__main__":
    main()
