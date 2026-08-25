from __future__ import annotations

import argparse
import json
import urllib.request
from pathlib import Path


CDN_ROOT = "https://ddragon.leagueoflegends.com/cdn"


def download(url: str, output: Path) -> None:
    if output.exists() and output.stat().st_size:
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "LOLHighRankComparator/1.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = response.read()
    temporary = output.with_suffix(output.suffix + ".next")
    temporary.write_bytes(payload)
    temporary.replace(output)


def build(version: str, output_root: Path) -> None:
    version_root = output_root / version
    champion_json = version_root / "champion.json"
    download(f"{CDN_ROOT}/{version}/data/en_US/champion.json", champion_json)
    champions = json.loads(champion_json.read_text(encoding="utf-8")).get("data", {})
    for champion in champions.values():
        filename = champion.get("image", {}).get("full")
        if filename:
            download(f"{CDN_ROOT}/{version}/img/champion/{filename}", version_root / "champion" / filename)

    item_payload = json.loads(Path("assets/item-data.json").read_text(encoding="utf-8"))
    item_sprites = sorted({
        item.get("image", {}).get("sprite")
        for item in item_payload.get("data", {}).values()
        if item.get("image", {}).get("sprite")
    })
    for filename in item_sprites:
        download(f"{CDN_ROOT}/{version}/img/sprite/{filename}", version_root / "sprite" / filename)

    spell_payload = json.loads(Path("assets/summoner-spells.json").read_text(encoding="utf-8"))
    spell_sprites = sorted({
        spell.get("image", {}).get("sprite")
        for spell in spell_payload.get("data", {}).values()
        if spell.get("image", {}).get("sprite")
    })
    for filename in spell_sprites:
        download(f"{CDN_ROOT}/{version}/img/sprite/{filename}", version_root / "sprite" / filename)
    print(f"desktop icon pack {version}: {len(champions)} champions, {len(item_sprites)} item sprites, {len(spell_sprites)} spell sprites")


def main() -> None:
    parser = argparse.ArgumentParser(description="Download an official Riot Data Dragon icon pack for the desktop app")
    parser.add_argument("--version", default="16.15.1")
    parser.add_argument("--output-root", type=Path, default=Path("assets/ddragon"))
    args = parser.parse_args()
    build(args.version, args.output_root)


if __name__ == "__main__":
    main()
