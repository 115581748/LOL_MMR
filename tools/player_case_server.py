from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
import urllib.parse
import uuid
from datetime import datetime, timezone
from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


PLAYER_CASE_PREFIX = "window.PLAYER_CASE="
CONDITIONAL_MODEL_PREFIX = "window.CONDITIONAL_MODEL="


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_riot_id(value: str) -> tuple[str, str]:
    candidate = urllib.parse.unquote(str(value or "").strip())
    if not candidate:
        raise ValueError("请输入 Riot ID，例如 Geolonwe#OC")
    if "/summoners/" in candidate:
        candidate = urllib.parse.urlparse(candidate).path.rstrip("/").split("/")[-1]
        candidate = urllib.parse.unquote(candidate)
        if "#" not in candidate and "-" in candidate:
            candidate = candidate.rsplit("-", 1)[0] + "#" + candidate.rsplit("-", 1)[1]
    if "#" not in candidate:
        raise ValueError("Riot ID 必须包含 #TAG，例如 Geolonwe#OC")
    game_name, tag_line = (part.strip() for part in candidate.rsplit("#", 1))
    if not game_name or not tag_line:
        raise ValueError("玩家名和 TAG 都不能为空")
    if len(game_name) > 64 or len(tag_line) > 16 or any(char in "\r\n\0" for char in candidate):
        raise ValueError("Riot ID 格式无效")
    return game_name, tag_line


def load_window_payload(path: Path, prefix: str) -> dict:
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8").strip()
    if not text.startswith(prefix):
        raise ValueError(f"Unexpected asset prefix in {path}")
    return json.loads(text[len(prefix):].removesuffix(";"))


def stable_case_payload(payload: dict) -> dict:
    value = json.loads(json.dumps(payload, ensure_ascii=False))
    value.get("meta", {}).pop("generatedAtUtc", None)
    return value


def player_pairs(payload: dict) -> set[tuple[str, str]]:
    pairs = set()
    for match in payload.get("matches", []):
        if match.get("champion") and match.get("position"):
            pairs.add((str(match["champion"]), str(match["position"])))
        if match.get("opponentChampion") and match.get("opponentPosition"):
            pairs.add((str(match["opponentChampion"]), str(match["opponentPosition"])))
    return pairs


class PlayerCaseManager:
    def __init__(self, root: Path, config: Path, refresh_minutes: int):
        self.root = root.resolve()
        self.config = config.resolve()
        self.refresh_minutes = max(1, refresh_minutes)
        self.player_case_path = self.root / "assets" / "player-case.js"
        self.conditional_path = self.root / "assets" / "conditional-model.js"
        self.manifest_path = self.root / "assets" / "model-manifest.json"
        self.lock = threading.Lock()
        self.busy = False
        self.last_checked_at: str | None = None
        self.last_updated_at: str | None = None
        self.last_error: str | None = None
        self.last_result: dict | None = None

    def _settings(self) -> dict:
        return json.loads(self.config.read_text(encoding="utf-8"))

    def _api_key(self) -> str:
        key = os.environ.get("RIOT_API_KEY", "").strip()
        if key:
            return key
        secret_path = self.root / ".secrets" / "riot_api_key.txt"
        return secret_path.read_text(encoding="utf-8").strip() if secret_path.exists() else ""

    def _current_payload(self) -> dict:
        return load_window_payload(self.player_case_path, PLAYER_CASE_PREFIX)

    def _revision(self) -> str | None:
        if not self.manifest_path.exists():
            return None
        return json.loads(self.manifest_path.read_text(encoding="utf-8")).get("revision")

    def status(self) -> dict:
        current = self._current_payload()
        meta = current.get("meta", {})
        return {
            "available": True,
            "canRefresh": bool(self._api_key()),
            "busy": self.busy,
            "currentRiotId": meta.get("riotId"),
            "rankedSoloMatches": meta.get("rankedSoloMatches", 0),
            "primaryPosition": meta.get("primaryPosition"),
            "primaryChampion": meta.get("primaryChampion"),
            "autoRefreshMinutes": self.refresh_minutes,
            "lastCheckedAtUtc": self.last_checked_at,
            "lastUpdatedAtUtc": self.last_updated_at,
            "lastError": self.last_error,
            "revision": self._revision(),
        }

    def _run(self, arguments: list[str], timeout: int, env: dict | None = None) -> str:
        completed = subprocess.run(
            [sys.executable, *arguments],
            cwd=self.root,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
        if completed.returncode:
            detail = (completed.stderr or completed.stdout or "unknown error").strip().splitlines()[-1]
            raise RuntimeError(detail)
        return (completed.stdout or "").strip()

    def _write_player_config(self, game_name: str, tag_line: str) -> None:
        settings = self._settings()
        settings.setdefault("player_case", {})["riot_id"] = game_name
        settings["player_case"]["tag_line"] = tag_line
        temporary = self.config.with_name(self.config.name + ".next")
        temporary.write_text(json.dumps(settings, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, self.config)

    def refresh(self, riot_id: str | None = None) -> dict:
        if not self.lock.acquire(blocking=False):
            raise RuntimeError("已有玩家刷新任务正在运行")
        self.busy = True
        token = uuid.uuid4().hex[:10]
        candidate_case = self.root / "assets" / f".player-case.{token}.next.js"
        candidate_conditional = self.root / "assets" / f".conditional-model.{token}.next.js"
        candidate_manifest = self.root / "assets" / f".model-manifest.{token}.next.json"
        try:
            current = self._current_payload()
            current_riot_id = current.get("meta", {}).get("riotId")
            game_name, tag_line = parse_riot_id(riot_id or current_riot_id or "")
            api_key = self._api_key()
            if not api_key:
                raise RuntimeError("服务端没有可用的 RIOT_API_KEY")
            settings = self._settings()
            platform = settings.get("collection", {}).get("platform", "oc1")
            matches = int(settings.get("player_case", {}).get("matches", 20))
            command_env = {**os.environ, "RIOT_API_KEY": api_key}
            output = self._run([
                "-m", "tools.build_player_case",
                "--config", str(self.config),
                "--platform", platform,
                "--riot-id", game_name,
                "--tag-line", tag_line,
                "--matches", str(matches),
                "--cache-dir", "data/cache",
                "--output", str(candidate_case),
            ], timeout=240, env=command_env)
            candidate = load_window_payload(candidate_case, PLAYER_CASE_PREFIX)
            changed = stable_case_payload(candidate) != stable_case_payload(current)
            switched = candidate.get("meta", {}).get("riotId") != current_riot_id
            conditional_rebuilt = False
            if changed or switched:
                existing_conditional = load_window_payload(self.conditional_path, CONDITIONAL_MODEL_PREFIX)
                existing_pairs = {
                    tuple(pair) for pair in existing_conditional.get("meta", {}).get("comparisonPlayerPairs", [])
                }
                missing_pairs = player_pairs(candidate) - existing_pairs
                if missing_pairs:
                    self._run([
                        "-m", "tools.refresh_comparison_profiles",
                        "--model", str(self.conditional_path),
                        "--player-case", str(candidate_case),
                        "--player-csv", "data/processed/player_matches.csv",
                        "--config", str(self.config),
                        "--output", str(candidate_conditional),
                    ], timeout=600)
                    os.replace(candidate_conditional, self.conditional_path)
                    conditional_rebuilt = True
                os.replace(candidate_case, self.player_case_path)
                self._write_player_config(game_name, tag_line)
                self._run([
                    "-m", "tools.build_site_manifest",
                    "--config", str(self.config),
                    "--output", str(candidate_manifest),
                ], timeout=120)
                os.replace(candidate_manifest, self.manifest_path)
                self.last_updated_at = utc_now()
            self.last_checked_at = utc_now()
            self.last_error = None
            self.last_result = {
                "ok": True,
                "changed": changed or switched,
                "switched": switched,
                "conditionalRebuilt": conditional_rebuilt,
                "riotId": candidate.get("meta", {}).get("riotId"),
                "rankedSoloMatches": candidate.get("meta", {}).get("rankedSoloMatches", 0),
                "revision": self._revision(),
                "message": output.splitlines()[-1] if output else "玩家数据已检查",
            }
            return self.last_result
        except Exception as exc:
            self.last_checked_at = utc_now()
            self.last_error = str(exc)
            raise
        finally:
            for path in (candidate_case, candidate_conditional, candidate_manifest):
                path.unlink(missing_ok=True)
            self.busy = False
            self.lock.release()


class PlayerCaseRequestHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, manager: PlayerCaseManager, directory: str, **kwargs):
        self.manager = manager
        super().__init__(*args, directory=directory, **kwargs)

    def _send_json(self, status: int, payload: dict) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _same_origin(self) -> bool:
        origin = self.headers.get("Origin")
        if not origin:
            return True
        host = self.headers.get("Host", "")
        origin_host = urllib.parse.urlparse(origin).hostname
        request_host = urllib.parse.urlparse(f"//{host}").hostname
        return origin in {f"http://{host}", f"https://{host}"} and origin_host in {"127.0.0.1", "localhost", "::1"} and request_host in {"127.0.0.1", "localhost", "::1"}

    def _read_json(self) -> dict:
        if self.headers.get_content_type() != "application/json":
            raise ValueError("请求必须使用 application/json")
        length = int(self.headers.get("Content-Length", "0"))
        if length < 0 or length > 4096:
            raise ValueError("请求内容过大")
        return json.loads(self.rfile.read(length).decode("utf-8")) if length else {}

    def do_GET(self) -> None:
        path = urllib.parse.urlparse(self.path).path
        if path == "/api/player-case/status":
            self._send_json(HTTPStatus.OK, self.manager.status())
            return
        super().do_GET()

    def do_POST(self) -> None:
        path = urllib.parse.urlparse(self.path).path
        if path not in {"/api/player-case/refresh", "/api/player-case/switch"}:
            self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "Unknown API endpoint"})
            return
        if not self._same_origin():
            self._send_json(HTTPStatus.FORBIDDEN, {"ok": False, "error": "Cross-origin requests are not allowed"})
            return
        try:
            body = self._read_json()
            riot_id = body.get("riotId") if path.endswith("switch") else None
            if path.endswith("switch") and not riot_id:
                raise ValueError("请输入要切换的玩家名#TAG")
            result = self.manager.refresh(riot_id)
            self._send_json(HTTPStatus.OK, result)
        except ValueError as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)})
        except Exception as exc:
            self._send_json(HTTPStatus.CONFLICT, {"ok": False, "error": str(exc)})

    def log_message(self, format: str, *args) -> None:
        sys.stdout.write(f"[{self.log_date_time_string()}] {format % args}\n")


def auto_refresh(manager: PlayerCaseManager, stop_event: threading.Event) -> None:
    while not stop_event.wait(manager.refresh_minutes * 60):
        try:
            manager.refresh()
        except Exception as exc:
            print(f"automatic player refresh failed: {exc}", file=sys.stderr)


def refresh_once(manager: PlayerCaseManager) -> None:
    try:
        result = manager.refresh()
        print(f"startup player refresh: {result.get('message', 'completed')}")
    except Exception as exc:
        print(f"startup player refresh failed: {exc}", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve the dashboard with secure Riot player refresh endpoints")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--config", default="config/model-parameters.json")
    parser.add_argument("--refresh-minutes", type=int, default=0)
    parser.add_argument("--refresh-on-start", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    config = (root / args.config).resolve()
    settings = json.loads(config.read_text(encoding="utf-8"))
    refresh_minutes = args.refresh_minutes or int(settings.get("player_case", {}).get("auto_refresh_minutes", 10))
    manager = PlayerCaseManager(root, config, refresh_minutes)
    handler = partial(PlayerCaseRequestHandler, manager=manager, directory=str(root))
    server = ThreadingHTTPServer((args.host, args.port), handler)
    stop_event = threading.Event()
    worker = threading.Thread(target=auto_refresh, args=(manager, stop_event), daemon=True)
    worker.start()
    if args.refresh_on_start:
        threading.Thread(target=refresh_once, args=(manager,), daemon=True).start()
    print(f"Player case server: http://{args.host}:{args.port}/conditional-model.html")
    print(f"Current player: {manager.status().get('currentRiotId')}; auto refresh every {refresh_minutes} minutes")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop_event.set()
        server.server_close()


if __name__ == "__main__":
    main()
