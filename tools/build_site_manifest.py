from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from riot_model.settings import load_settings


def file_digest(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


def build(args):
    core = Path(args.core)
    extras = Path(args.extras)
    optional_assets = {
        "conditional": Path(args.conditional),
        "playerCase": Path(args.player_case),
    }
    site_assets = [Path(value) for value in args.site_assets]
    digest_paths = [
        core,
        extras,
        *(path for path in optional_assets.values() if path.exists()),
        *(path for path in site_assets if path.exists()),
    ]
    dataset_manifest = Path(args.dataset_manifest)
    payload = {
        "schemaVersion": 1,
        "revision": file_digest(digest_paths),
        "generatedAtUtc": datetime.now(timezone.utc).isoformat(),
        "assets": {
            "core": core.as_posix(),
            "extras": extras.as_posix(),
            **{key: path.as_posix() for key, path in optional_assets.items() if path.exists()},
        },
        "dataset": json.loads(dataset_manifest.read_text(encoding="utf-8")) if dataset_manifest.exists() else {},
        "parameters": load_settings(args.config),
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    print(f"wrote site revision {payload['revision']} to {output}")


def main():
    parser = argparse.ArgumentParser(description="Build the cache-safe static dashboard manifest")
    parser.add_argument("--config", default="config/model-parameters.json")
    parser.add_argument("--core", default="assets/model-data.js")
    parser.add_argument("--extras", default="assets/model-extras.js")
    parser.add_argument("--conditional", default="assets/conditional-model.js")
    parser.add_argument("--player-case", default="assets/player-case.js")
    parser.add_argument(
        "--site-assets",
        nargs="*",
        default=[
            "model-dashboard.js",
            "model-dashboard.css",
            "model-dashboard-extras.css",
            "conditional-model-app.js",
            "conditional-model.css",
            "conditional-model-overrides.css",
            "assets/model-loader.js",
            "assets/conditional-model-loader.js",
        ],
    )
    parser.add_argument("--dataset-manifest", default="data/processed/player_matches.manifest.json")
    parser.add_argument("--output", default="assets/model-manifest.json")
    build(parser.parse_args())


if __name__ == "__main__":
    main()
