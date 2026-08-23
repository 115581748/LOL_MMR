from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from riot_model.features import extract_match_replay


MATCH_DIR = ROOT / "data" / "cache" / "matches"
TIMELINE_DIR = ROOT / "data" / "cache" / "timelines"
OUTPUT = ROOT / "assets" / "demo-replay.js"


def main():
    common = sorted({path.stem for path in MATCH_DIR.glob("*.json")} & {path.stem for path in TIMELINE_DIR.glob("*.json")})
    if not common:
        raise SystemExit("No cached match/timeline pair found")
    for match_id in common:
        match = json.loads((MATCH_DIR / f"{match_id}.json").read_text(encoding="utf-8"))
        timeline = json.loads((TIMELINE_DIR / f"{match_id}.json").read_text(encoding="utf-8"))
        replay = extract_match_replay(match, timeline)
        if replay and len(replay["frames"]) >= 16:
            OUTPUT.write_text("window.DEMO_REPLAY = " + json.dumps(replay, ensure_ascii=False, separators=(",", ":")) + ";\n", encoding="utf-8")
            print(f"wrote {OUTPUT} from {match_id}: {len(replay['frames'])} minute frames")
            return
    raise SystemExit("No suitable cached replay found")


if __name__ == "__main__":
    main()
