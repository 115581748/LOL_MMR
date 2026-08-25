from __future__ import annotations

import csv
import json
import math
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


ID_COLUMNS = {
    "match_id", "game_version", "game_start_ms", "puuid", "tier", "division", "league_points",
    "champion_id", "champion", "position", "opponent_champion_id", "opponent_champion", "opponent_position",
}


def read_csv(path):
    with Path(path).open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path, rows):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    if not rows: return
    fieldnames = list(rows[0])
    seen = set(fieldnames)
    for row in rows[1:]:
        for key in row:
            if key not in seen:
                fieldnames.append(key); seen.add(key)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames); writer.writeheader(); writer.writerows(rows)


def _quantile(values, q):
    values = sorted(values); pos = (len(values) - 1) * q; lo = math.floor(pos); hi = math.ceil(pos)
    return values[lo] if lo == hi else values[lo] * (hi - pos) + values[hi] * (pos - lo)


def build_benchmarks(rows, minimum_samples=5, iqr_multiplier=1.5):
    groups = defaultdict(list)
    for row in rows:
        if row.get("champion") and row.get("position"):
            groups[(row["champion"], row["position"])].append(row)
    result = []
    for (champion, position), samples in sorted(groups.items()):
        if len(samples) < minimum_samples: continue
        # Opponent fields are retained at match level for head-to-head display.
        # Opponent averages use that champion's own rows, avoiding a redundant
        # and semantically different "opponents faced by X" benchmark.
        metrics = [k for k in samples[0] if k not in ID_COLUMNS and not k.startswith("opponent_")]
        for metric in metrics:
            try: values = [float(x[metric]) for x in samples if x.get(metric) not in (None, "")]
            except (TypeError, ValueError): continue
            if len(values) < minimum_samples: continue
            q1, q3 = _quantile(values, .25), _quantile(values, .75); iqr = q3 - q1
            clean = [v for v in values if q1 - iqr_multiplier * iqr <= v <= q3 + iqr_multiplier * iqr]
            result.append({"champion": champion, "position": position, "metric": metric, "n_raw": len(values), "n_clean": len(clean),
                           "mean": round(statistics.fmean(clean), 4), "median": round(statistics.median(clean), 4),
                           "std": round(statistics.stdev(clean), 4) if len(clean) > 1 else 0,
                           "p25": round(_quantile(clean, .25), 4), "p75": round(_quantile(clean, .75), 4),
                           "iqr_low": round(q1 - iqr_multiplier * iqr, 4), "iqr_high": round(q3 + iqr_multiplier * iqr, 4)})
    return result


def write_manifest(path, *, platform, players, matches, rows, settings=None):
    settings = settings or {}
    model = settings.get("model", {})
    multiplier = model.get("outlier_iqr_multiplier", 1.5)
    payload = {
        "platform": platform,
        "players_sampled": players,
        "unique_matches": matches,
        "player_match_rows": rows,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "unit_of_analysis": "one player in one ranked solo match",
        "outlier_rule": f"per champion-position-metric Tukey {multiplier}*IQR",
        "model_parameters": model,
        "dashboard_parameters": settings.get("dashboard", {}),
    }
    Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
