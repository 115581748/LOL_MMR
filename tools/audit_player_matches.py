from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path


def row_identity(row: dict) -> tuple[str, str] | None:
    puuid = str(row.get("puuid") or "").strip()
    match_id = str(row.get("match_id") or "").strip()
    return (puuid, match_id) if puuid and match_id else None


def row_digest(row: dict) -> bytes:
    payload = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).digest()


def audit_jsonl(path: Path, clean_output: Path | None = None) -> dict:
    physical_lines = blank_lines = invalid_json_lines = missing_identity_lines = 0
    duplicate_rows = conflicting_duplicate_rows = 0
    last_line: dict[tuple[str, str], int] = {}
    last_digest: dict[tuple[str, str], bytes] = {}

    with path.open(encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            physical_lines += 1
            if not line.strip():
                blank_lines += 1
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                invalid_json_lines += 1
                continue
            identity = row_identity(row)
            if identity is None:
                missing_identity_lines += 1
                continue
            digest = row_digest(row)
            if identity in last_line:
                duplicate_rows += 1
                if last_digest[identity] != digest:
                    conflicting_duplicate_rows += 1
            last_line[identity] = line_number
            last_digest[identity] = digest

    if clean_output is not None:
        clean_output.parent.mkdir(parents=True, exist_ok=True)
        with path.open(encoding="utf-8") as source, clean_output.open("w", encoding="utf-8", newline="\n") as target:
            for line_number, line in enumerate(source, 1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                identity = row_identity(row)
                if identity is None or last_line.get(identity) != line_number:
                    continue
                target.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")

    return {
        "source": str(path),
        "physical_lines": physical_lines,
        "unique_player_matches": len(last_line),
        "duplicate_rows_removed": duplicate_rows,
        "conflicting_duplicate_rows": conflicting_duplicate_rows,
        "blank_lines_removed": blank_lines,
        "invalid_json_lines_removed": invalid_json_lines,
        "missing_identity_lines_removed": missing_identity_lines,
        "clean_output": str(clean_output) if clean_output else None,
    }


def audit_csv(path: Path) -> dict:
    rows = duplicate_rows = missing_identity_rows = 0
    identities: set[tuple[str, str]] = set()
    with path.open(encoding="utf-8-sig", newline="") as source:
        for row in csv.DictReader(source):
            rows += 1
            identity = row_identity(row)
            if identity is None:
                missing_identity_rows += 1
            elif identity in identities:
                duplicate_rows += 1
            else:
                identities.add(identity)
    return {
        "source": str(path),
        "rows": rows,
        "unique_player_matches": len(identities),
        "duplicate_rows": duplicate_rows,
        "missing_identity_rows": missing_identity_rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit and clean player-match identity duplicates")
    parser.add_argument("--jsonl", type=Path, required=True)
    parser.add_argument("--csv", type=Path)
    parser.add_argument("--clean-jsonl", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()

    report = {"checkpoint": audit_jsonl(args.jsonl, args.clean_jsonl)}
    if args.csv:
        report["processed_csv"] = audit_csv(args.csv)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
