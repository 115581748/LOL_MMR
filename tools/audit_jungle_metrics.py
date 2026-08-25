from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path


JUNGLE_FIELDS = (
    "early_gold_diff_vs_enemy_jungle",
    "early_xp_diff_vs_enemy_jungle",
    "early_cs_diff_vs_enemy_jungle",
    "early_gank_takedowns",
    "early_gank_lanes",
    "early_first_gank_minute",
    "early_team_dragons",
    "early_team_void_grubs",
    "early_team_rift_heralds",
    "early_personal_epic_secures",
    "early_gank_takedown_diff_vs_enemy_jungle",
    "early_epic_monster_diff_vs_enemy_jungle",
)


def audit(path: Path) -> dict:
    identities = set()
    duplicate_rows = 0
    row_count = 0
    jungle_rows = 0
    coverage = Counter()
    gank_diffs_by_match = defaultdict(list)
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            row_count += 1
            identity = (row.get("puuid"), row.get("match_id"))
            duplicate_rows += identity in identities
            identities.add(identity)
            if row.get("position") != "JUNGLE":
                continue
            jungle_rows += 1
            for field in JUNGLE_FIELDS:
                if row.get(field) not in (None, ""):
                    coverage[field] += 1
            value = row.get("early_gank_takedown_diff_vs_enemy_jungle")
            if value not in (None, ""):
                gank_diffs_by_match[row.get("match_id")].append(float(value))
    paired = [values for values in gank_diffs_by_match.values() if len(values) >= 2]
    return {
        "rows": row_count,
        "uniquePlayerMatches": len(identities),
        "duplicateRows": duplicate_rows,
        "jungleRows": jungle_rows,
        "coverage": {field: coverage[field] for field in JUNGLE_FIELDS},
        "opposingJunglePairsChecked": len(paired),
        "opposingGankDiffPairsAntisymmetric": sum(abs(sum(values[:2])) < 1e-9 for values in paired),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit jungle action metric coverage and opponent deltas")
    parser.add_argument("--input", default="data/processed/player_matches.csv")
    args = parser.parse_args()
    print(json.dumps(audit(Path(args.input)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
