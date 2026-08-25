from __future__ import annotations

import csv
import json
from pathlib import Path

from .settings import load_settings


CORE_METRICS = {
    "early_gold_15", "early_xp_15", "early_cs_15", "early_kills", "early_deaths", "early_assists",
    "mid_gold_gain", "mid_cs_gain", "mid_champion_damage", "mid_kills", "mid_deaths", "mid_assists",
    "mid_team_turrets", "mid_team_dragons", "late_champion_damage_per_min", "late_damage_taken_per_min", "late_kills",
    "late_deaths", "late_assists", "late_teamfights", "late_teamfight_participations", "late_first_target_deaths",
    "cs_per_min", "damage_per_min", "vision_per_min", "challenge_killParticipation", "challenge_goldPerMinute",
    "challenge_damageTakenOnTeamPercentage", "challenge_teamDamagePercentage", "challenge_laneMinionsFirst10Minutes",
    "challenge_maxCsAdvantageOnLaneOpponent",
}


def export_dashboard(
    input_csv="data/models/champion_role_benchmarks.csv",
    output_js="assets/model-data.js",
    core_only=False,
    config_path="config/model-parameters.json",
):
    with Path(input_csv).open(encoding="utf-8", newline="") as source:
        rows = list(csv.DictReader(source))
    numeric = ("n_raw", "n_clean", "mean", "median", "std", "p25", "p75", "iqr_low", "iqr_high")
    compact = []
    for row in rows:
        if core_only and row["metric"] not in CORE_METRICS:
            continue
        item = {"c": row["champion"], "r": row["position"], "m": row["metric"]}
        for key in numeric:
            item[key] = float(row[key]) if "." in row[key] else int(row[key])
        compact.append(item)
    output = Path(output_js)
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest_path = Path("data/processed/player_matches.manifest.json")
    meta = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    settings = load_settings(config_path)
    meta["model_parameters"] = settings["model"]
    meta["dashboard_parameters"] = settings["dashboard"]
    payload = {"generatedFrom": str(input_csv).replace("\\", "/"), "meta": meta, "rows": compact}
    with output.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write("window.MODEL_DATA=" + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + ";\n")
    return len(compact)
