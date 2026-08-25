from __future__ import annotations

import json
import math
import os
import sys
import threading
import time
import urllib.parse
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk

if not getattr(sys, "frozen", False):
    source_root = Path(__file__).resolve().parents[1]
    if str(source_root) not in sys.path:
        sys.path.insert(0, str(source_root))

from riot_model.client import RiotClient
from riot_model.features import extract_match_replay, extract_player_match
from riot_model.settings import load_settings
from tools.build_conditional_model import PHASE_METRICS, number, phase_metrics
from tools.build_player_case import case_payload


APP_NAME = "LOLHighRankComparator"
APP_TITLE = "峡谷天平 · 高分段赛后对比"
DDRAGON_VERSION = "16.15.1"
PHASE_NAMES = {"EARLY": "前期 0–15", "MID": "中期 15–25", "LATE": "后期 25+"}
POSITION_NAMES = {"TOP": "上路", "JUNGLE": "打野", "MIDDLE": "中路", "BOTTOM": "下路", "UTILITY": "辅助"}
CONFIDENCE_NAMES = {"HIGH": "高", "MEDIUM": "中", "LOW": "低"}
DRAGON_NAMES = {
    "FIRE_DRAGON": "火龙", "EARTH_DRAGON": "土龙", "WATER_DRAGON": "水龙",
    "AIR_DRAGON": "风龙", "HEXTECH_DRAGON": "海克斯龙", "CHEMTECH_DRAGON": "炼金龙",
    "ELDER_DRAGON": "远古龙", "Infernal": "火龙魂", "Mountain": "土龙魂",
    "Ocean": "水龙魂", "Cloud": "风龙魂", "Hextech": "海克斯龙魂", "Chemtech": "炼金龙魂",
}
PALETTE = {
    "root": "#060b0f",
    "panel": "#0b141a",
    "panel_hover": "#10232a",
    "line": "#20343d",
    "gold": "#e9bd59",
    "gold_soft": "#f6d98d",
    "teal": "#67ded7",
    "blue": "#55c8ef",
    "red": "#ef7b70",
    "text": "#dbe8ed",
    "muted": "#78909a",
}
LANE_PATHS = {
    "TOP": [(1450, 1450), (1100, 3600), (1100, 12100), (3300, 13700), (13500, 13500)],
    "MIDDLE": [(1450, 1450), (7500, 7500), (13500, 13500)],
    "BOTTOM": [(1450, 1450), (3600, 1100), (12100, 1100), (13700, 3300), (13500, 13500)],
}
METRIC_NAMES = {
    "early_gold_15": "15 分钟经济", "early_xp_15": "15 分钟经验", "early_cs_15": "15 分钟 CS",
    "early_kills": "前期击杀", "early_deaths": "前期死亡", "early_assists": "前期助攻",
    "mid_gold_gain": "15–25 经济增长", "mid_cs_gain": "15–25 CS 增长", "mid_champion_damage": "15–25 英雄伤害",
    "mid_kills": "中期击杀", "mid_deaths": "中期死亡", "mid_assists": "中期助攻",
    "mid_team_turrets": "中期团队推塔", "mid_team_dragons": "中期团队小龙",
    "late_champion_damage_per_min": "25+ 每分钟英雄伤害", "late_damage_taken_per_min": "25+ 每分钟承伤",
    "late_kills": "后期击杀", "late_deaths": "后期死亡", "late_assists": "后期助攻",
    "late_teamfight_participation_rate": "后期团战参与率", "late_first_target_deaths": "后期首个阵亡",
    "early_gold_diff_vs_enemy_jungle": "15 分钟对位经济差", "early_xp_diff_vs_enemy_jungle": "15 分钟对位经验差",
    "early_cs_diff_vs_enemy_jungle": "15 分钟对位 CS 差", "early_gank_takedowns": "前 15 分钟有效 Gank",
    "early_gank_lanes": "前 15 分钟影响路线数", "early_first_gank_minute": "首次有效 Gank 分钟",
    "early_enemy_jungle_takedowns": "前期对敌方打野击杀参与", "early_kill_participation_rate": "前期团队击杀参与率",
    "early_team_dragons": "前期团队小龙", "early_team_void_grubs": "前期团队虚空巢虫",
    "early_team_rift_heralds": "前期团队峡谷先锋", "early_personal_epic_secures": "前期个人史诗野怪击杀",
    "early_gank_takedown_diff_vs_enemy_jungle": "前期有效 Gank 对位差",
    "early_epic_monster_diff_vs_enemy_jungle": "前期史诗野怪对位差",
    "mid_gank_takedowns": "中期有效 Gank", "mid_gank_lanes": "中期影响路线数",
    "mid_first_gank_minute": "中期首次有效 Gank 分钟", "mid_enemy_jungle_takedowns": "中期对敌方打野击杀参与",
    "mid_kill_participation_rate": "中期团队击杀参与率", "mid_team_void_grubs": "中期团队虚空巢虫",
    "mid_team_rift_heralds": "中期团队峡谷先锋", "mid_personal_epic_secures": "中期个人史诗野怪击杀",
    "mid_gank_takedown_diff_vs_enemy_jungle": "中期有效 Gank 对位差",
    "mid_epic_monster_diff_vs_enemy_jungle": "中期史诗野怪对位差",
}


def resource_path(relative: str) -> Path:
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    return root / relative


def blend_hex(start: str, end: str, ratio: float) -> str:
    """Blend two #RRGGBB colours for lightweight native UI animation."""
    ratio = min(1.0, max(0.0, float(ratio)))
    start_rgb = tuple(int(start[index:index + 2], 16) for index in (1, 3, 5))
    end_rgb = tuple(int(end[index:index + 2], 16) for index in (1, 3, 5))
    values = tuple(round(left + (right - left) * ratio) for left, right in zip(start_rgb, end_rgb))
    return "#" + "".join(f"{value:02x}" for value in values)


def recent_form_summary(matches: list[dict], limit: int = 18) -> dict:
    sample = list(matches[:max(0, int(limit))])
    wins = sum(bool(match.get("win")) for match in sample)
    streak = 0
    streak_win = bool(sample[0].get("win")) if sample else None
    for match in sample:
        if bool(match.get("win")) != streak_win:
            break
        streak += 1
    return {
        "games": len(sample),
        "wins": wins,
        "losses": len(sample) - wins,
        "winRate": wins / len(sample) if sample else 0.0,
        "streak": streak,
        "streakWin": streak_win,
    }


def app_data_dir() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    path = base / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def parse_riot_id(value: str) -> tuple[str, str]:
    candidate = urllib.parse.unquote(str(value or "").strip())
    if "/summoners/" in candidate:
        candidate = urllib.parse.urlparse(candidate).path.rstrip("/").split("/")[-1]
        candidate = urllib.parse.unquote(candidate)
        if "#" not in candidate and "-" in candidate:
            left, right = candidate.rsplit("-", 1)
            candidate = f"{left}#{right}"
    if "#" not in candidate:
        raise ValueError("Riot ID 必须包含 #TAG，例如 Geolonwe#OC")
    game_name, tag_line = (part.strip() for part in candidate.rsplit("#", 1))
    if not game_name or not tag_line:
        raise ValueError("玩家名和 TAG 不能为空")
    return game_name, tag_line


def load_bootstrap_case(path: Path) -> dict:
    source = path.read_text(encoding="utf-8").strip()
    if source.startswith("window.PLAYER_CASE="):
        source = source[len("window.PLAYER_CASE="):].removesuffix(";")
    return json.loads(source)


def approximate_percentile(value, stats) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not stats:
        return None
    points = [(stats["p10"], 10), (stats["p25"], 25), (stats["median"], 50), (stats["p75"], 75), (stats["p90"], 90)]
    if numeric < points[0][0]:
        return max(0, 10 - 10 * (points[0][0] - numeric) / (abs(points[0][0]) or 1))
    if numeric >= points[-1][0]:
        return min(100, 90 + 10 * (numeric - points[-1][0]) / (abs(points[-1][0]) + 1))
    for index in range(1, len(points)):
        if numeric <= points[index][0]:
            low_value, low_pct = points[index - 1]
            high_value, high_pct = points[index]
            ratio = (numeric - low_value) / (high_value - low_value or 1)
            return low_pct + ratio * (high_pct - low_pct)
    return None


def format_metric(metric: str, value) -> str:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return "—"
    if not math.isfinite(numeric):
        return "—"
    if "rate" in metric:
        return f"{numeric * 100:.1f}%"
    if abs(numeric) >= 1000:
        return f"{numeric:,.0f}"
    if abs(numeric - round(numeric)) < 1e-9:
        return f"{int(numeric)}"
    return f"{numeric:.2f}".rstrip("0").rstrip(".")


def format_gap(metric: str, value) -> str:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return "—"
    sign = "+" if numeric > 0 else ""
    if "rate" in metric:
        return f"{sign}{numeric * 100:.1f}pp"
    return f"{sign}{format_metric(metric, numeric)}"


def comparison_rows(match: dict, phase: str, baselines: dict) -> list[tuple[str, ...]]:
    position = match.get("position")
    player_profile = baselines.get(f"{match.get('champion')}|{position}|{phase}", {})
    opponent_profile = baselines.get(f"{match.get('opponentChampion')}|{match.get('opponentPosition')}|{phase}", {})
    rows = []
    for metric in phase_metrics(phase, position):
        player_value = number(match.get(metric))
        opponent_value = number(match.get(f"opponent_{metric}"))
        player_stats = player_profile.get("metrics", {}).get(metric)
        opponent_stats = opponent_profile.get("metrics", {}).get(metric)
        player_base = number(player_stats.get("median")) if player_stats else None
        opponent_base = number(opponent_stats.get("median")) if opponent_stats else None
        player_pct = approximate_percentile(player_value, player_stats)
        opponent_pct = approximate_percentile(opponent_value, opponent_stats)
        rows.append((
            METRIC_NAMES.get(metric, metric),
            format_metric(metric, player_value),
            format_metric(metric, opponent_value),
            f"{format_metric(metric, player_base)}  n={player_profile.get('sampleSize', 0)}" if player_stats else "—",
            f"{format_metric(metric, opponent_base)}  n={opponent_profile.get('sampleSize', 0)}" if opponent_stats else "—",
            format_gap(metric, player_value - opponent_value) if player_value is not None and opponent_value is not None else "—",
            format_gap(metric, player_value - player_base) if player_value is not None and player_base is not None else "—",
            format_gap(metric, opponent_value - opponent_base) if opponent_value is not None and opponent_base is not None else "—",
            f"P{round(player_pct)}" if player_pct is not None else "—",
            f"P{round(opponent_pct)}" if opponent_pct is not None else "—",
        ))
    return rows


def map_coordinates(x, y, width: int, height: int) -> tuple[float, float] | None:
    """Convert Riot's bottom-left map coordinates to Tk's top-left canvas."""
    try:
        map_x = min(15000.0, max(0.0, float(x)))
        map_y = min(15000.0, max(0.0, float(y)))
    except (TypeError, ValueError):
        return None
    return map_x / 15000.0 * width, height - map_y / 15000.0 * height


def point_along_path(path: list[tuple[float, float]], distance: float) -> tuple[float, float]:
    remaining = max(0.0, float(distance))
    for start, end in zip(path, path[1:]):
        segment = math.dist(start, end)
        if remaining <= segment:
            ratio = remaining / segment if segment else 0.0
            return start[0] + (end[0] - start[0]) * ratio, start[1] + (end[1] - start[1]) * ratio
        remaining -= segment
    return path[-1]


def estimated_minion_waves(second: int) -> list[dict]:
    """Estimate the newest wave from public SR spawn rules; Riot does not expose minion positions."""
    current = max(0, int(second))
    first_spawn = 65
    if current < first_spawn:
        return []
    spawn_second = first_spawn + ((current - first_spawn) // 30) * 30
    age = current - spawn_second
    output = []
    for lane, path in LANE_PATHS.items():
        total_distance = sum(math.dist(start, end) for start, end in zip(path, path[1:]))
        travel = min(325.0 * age, total_distance / 2)
        output.append({"teamId": 100, "lane": lane, "x": point_along_path(path, travel)[0], "y": point_along_path(path, travel)[1], "spawnSecond": spawn_second, "estimated": True})
        reversed_path = list(reversed(path))
        red_position = point_along_path(reversed_path, travel)
        output.append({"teamId": 200, "lane": lane, "x": red_position[0], "y": red_position[1], "spawnSecond": spawn_second, "estimated": True})
    return output


def replay_event_lines(frame: dict, players: list[dict]) -> list[str]:
    champions = {player.get("participantId"): player.get("champion", "未知") for player in players}

    def champion(participant_id) -> str:
        return champions.get(participant_id, f"玩家 {participant_id}")

    lines = []
    for event in frame.get("events", []):
        event_type = event.get("type")
        if event_type == "CHAMPION_KILL":
            assists = [champion(pid) for pid in event.get("assistingParticipantIds", [])]
            suffix = f"（助攻：{'、'.join(assists)}）" if assists else ""
            lines.append(f"击杀：{champion(event.get('killerId'))} → {champion(event.get('victimId'))}{suffix}")
        elif event_type == "DERIVED_TEAMFIGHT":
            blue_kills = int(number(event.get("killsByTeam", {}).get(100)) or 0)
            red_kills = int(number(event.get("killsByTeam", {}).get(200)) or 0)
            start = format_clock(int(number(event.get("startTimestamp")) or 0) / 1000)
            end = format_clock(int(number(event.get("endTimestamp")) or 0) / 1000)
            participants = len(event.get("participantIds", []))
            lines.append(f"团战（规则识别）：{start}–{end} · 蓝 {blue_kills}:{red_kills} 红 · {participants} 人参与")
        elif event_type == "ELITE_MONSTER_KILL":
            monster_key = event.get("monsterSubType") or event.get("monsterType") or "史诗野怪"
            monster = DRAGON_NAMES.get(monster_key, monster_key)
            lines.append(f"资源：{champion(event.get('killerId'))} 击杀 {monster}")
        elif event_type == "DRAGON_SOUL_GIVEN" and event.get("teamId") in {100, 200}:
            team_name = "蓝方" if event.get("teamId") == 100 else "红方"
            soul = DRAGON_NAMES.get(event.get("name"), event.get("name") or "龙魂")
            lines.append(f"龙魂：{team_name} 获得 {soul}")
        elif event_type == "BUILDING_KILL":
            building = event.get("towerType") or event.get("buildingType") or "防御建筑"
            lane = event.get("laneType") or ""
            lines.append(f"推塔：{champion(event.get('killerId'))} · {lane} {building}".strip())
        elif event_type == "WARD_PLACED":
            lines.append(f"视野：{champion(event.get('creatorId'))} 放置 {event.get('wardType') or '守卫'}")
        elif event_type == "WARD_KILL":
            lines.append(f"排眼：{champion(event.get('killerId'))} 清除 {event.get('wardType') or '守卫'}")
    return lines


def format_clock(seconds) -> str:
    try:
        total = max(0, int(float(seconds)))
    except (TypeError, ValueError):
        total = 0
    return f"{total // 60:02d}:{total % 60:02d}"


def timeline_second_at_x(x: float, width: float, total_seconds: int, slider_length: int = 22) -> int:
    usable = max(1.0, float(width) - slider_length)
    ratio = (float(x) - slider_length / 2) / usable
    return round(min(1.0, max(0.0, ratio)) * max(0, int(total_seconds)))


def replay_events(replay: dict) -> list[dict]:
    return sorted(
        (event for frame in replay.get("frames", []) for event in frame.get("events", [])),
        key=lambda event: int(number(event.get("timestamp")) or 0),
    )


def detected_teamfight_events(replay: dict, max_gap_ms: int = 15_000, min_kills: int = 3) -> list[dict]:
    """Convert clustered Riot kill events into evidence-labelled teamfight events.

    Riot does not emit TEAMFIGHT directly. This preserves the model's existing
    rule: at least three champion kills, with no more than 15 seconds between
    consecutive kills. The exact kills remain the evidence; the grouping is a
    deterministic derived event and is labelled as such.
    """
    public_players = {
        int(number(player.get("participantId")) or 0): player
        for player in replay.get("players", [])
    }
    team_by_participant = {
        participant_id: int(number(player.get("teamId")) or 0)
        for participant_id, player in public_players.items()
    }
    kills = [event for event in replay_events(replay) if event.get("type") == "CHAMPION_KILL"]
    groups: list[list[dict]] = []
    for event in kills:
        timestamp = int(number(event.get("timestamp")) or 0)
        previous_timestamp = int(number(groups[-1][-1].get("timestamp")) or 0) if groups else None
        if previous_timestamp is None or timestamp - previous_timestamp > max(1_000, int(max_gap_ms)):
            groups.append([event])
        else:
            groups[-1].append(event)

    output = []
    for group in groups:
        if len(group) < max(2, int(min_kills)):
            continue
        participants = set()
        kills_by_team = {100: 0, 200: 0}
        deaths_by_team = {100: 0, 200: 0}
        positions = []
        for event in group:
            killer_id = int(number(event.get("killerId")) or 0)
            victim_id = int(number(event.get("victimId")) or 0)
            participants.update(pid for pid in [killer_id, victim_id] if pid)
            participants.update(int(number(pid) or 0) for pid in event.get("assistingParticipantIds", []) if int(number(pid) or 0))
            killer_team = team_by_participant.get(killer_id, 0)
            victim_team = team_by_participant.get(victim_id, 0)
            if killer_team in kills_by_team:
                kills_by_team[killer_team] += 1
            if victim_team in deaths_by_team:
                deaths_by_team[victim_team] += 1
            position = event.get("position") or {}
            x = number(position.get("x"))
            y = number(position.get("y"))
            if x is not None and y is not None:
                positions.append((float(x), float(y)))

        start_ms = int(number(group[0].get("timestamp")) or 0)
        end_ms = int(number(group[-1].get("timestamp")) or 0)
        winner_team = 0
        if kills_by_team[100] != kills_by_team[200]:
            winner_team = 100 if kills_by_team[100] > kills_by_team[200] else 200
        confidence = min(0.93, 0.78 + max(0, len(group) - 3) * 0.04 + max(0, len(participants) - 4) * 0.015)
        derived = {
            "type": "DERIVED_TEAMFIGHT",
            "eventId": f"teamfight-{start_ms}-{end_ms}",
            "timestamp": end_ms,
            "startTimestamp": start_ms,
            "endTimestamp": end_ms,
            "durationSeconds": round((end_ms - start_ms) / 1000, 1),
            "killCount": len(group),
            "participantIds": sorted(participants),
            "killsByTeam": kills_by_team,
            "deathsByTeam": deaths_by_team,
            "winningTeamId": winner_team,
            "evidenceTimestamps": [int(number(event.get("timestamp")) or 0) for event in group],
            "derived": True,
            "confidence": round(confidence, 2),
            "source": "规则识别：连续击杀事件聚类",
        }
        if positions:
            derived["position"] = {
                "x": round(sum(position[0] for position in positions) / len(positions)),
                "y": round(sum(position[1] for position in positions) / len(positions)),
            }
        output.append(derived)
    return output


def replay_phase(second: int) -> str:
    """Return the benchmark phase active at a replay timestamp."""
    current = max(0, int(second))
    if current < 15 * 60:
        return "EARLY"
    if current < 25 * 60:
        return "MID"
    return "LATE"


def replay_frame_at(replay: dict, second: int) -> dict:
    frames = replay.get("frames", [])
    if not frames:
        return {}
    return frames[min(max(0, int(second)) // 60, len(frames) - 1)]


def estimated_respawn_seconds(level: int, game_second: int) -> int:
    """Return a UI-only Summoner's Rift respawn estimate.

    Riot Timeline records the death event precisely, but it does not provide a
    matching respawn event in ordinary match timelines. Keep this estimate out
    of model features and label it instead of presenting it as observed fact.
    """
    base_by_level = (10, 10, 12, 12, 14, 16, 20, 25, 28, 30, 32, 35, 37, 40, 42, 45, 48, 52)
    safe_level = min(18, max(1, int(number(level) or 1)))
    base_seconds = base_by_level[safe_level - 1]
    # Late-game timers grow with game time. This bounded interpolation is an
    # intentionally conservative display estimate, not a server timestamp.
    late_progress = min(1.0, max(0.0, (max(0, int(game_second)) - 15 * 60) / (40 * 60)))
    return max(1, round(base_seconds * (1.0 + 0.5 * late_progress)))


def death_states_at(replay: dict, second: int) -> dict[int, dict]:
    """Return participants estimated to be dead at ``second``.

    Death timestamp and location are exact Riot CHAMPION_KILL evidence. The
    respawn boundary is explicitly estimated because Timeline exposes no exact
    respawn event. If a future payload contains CHAMPION_RESPAWN, it wins.
    """
    current_second = max(0, int(second))
    current_ms = current_second * 1000
    states: dict[int, dict] = {}
    for event in replay_events(replay):
        timestamp_ms = int(number(event.get("timestamp")) or 0)
        if timestamp_ms > current_ms:
            break
        event_type = event.get("type")
        if event_type == "CHAMPION_RESPAWN":
            participant_id = int(number(event.get("participantId")) or 0)
            if participant_id:
                states.pop(participant_id, None)
            continue
        if event_type != "CHAMPION_KILL":
            continue
        victim_id = int(number(event.get("victimId")) or 0)
        if not victim_id:
            continue
        death_second = timestamp_ms // 1000
        death_frame = replay_frame_at(replay, death_second)
        victim_frame = next((
            player for player in death_frame.get("players", [])
            if int(number(player.get("participantId")) or 0) == victim_id
        ), {})
        level = min(18, max(1, int(number(victim_frame.get("level")) or 1)))
        respawn_seconds = estimated_respawn_seconds(level, death_second)
        respawn_ms = timestamp_ms + respawn_seconds * 1000
        position = event.get("position") or {}
        if position.get("x") is None or position.get("y") is None:
            position = {"x": victim_frame.get("x"), "y": victim_frame.get("y")}
        states[victim_id] = {
            "participantId": victim_id,
            "deathTimestamp": timestamp_ms,
            "estimatedRespawnTimestamp": respawn_ms,
            "remainingSeconds": max(0, math.ceil((respawn_ms - current_ms) / 1000)),
            "level": level,
            "position": position,
            "deathObserved": True,
            "respawnEstimated": True,
            "source": "Riot CHAMPION_KILL 事件（死亡）+ 规则估计（复活）",
        }

    return {
        participant_id: state
        for participant_id, state in states.items()
        if current_ms < int(state["estimatedRespawnTimestamp"])
    }


def focus_participant_ids(replay: dict, match: dict) -> tuple[int | None, int | None]:
    """Locate the reviewed player and their positional opponent without account IDs."""
    players = replay.get("players", [])
    champion = str(match.get("champion") or "").lower()
    position = match.get("position")
    own_candidates = [
        player for player in players
        if str(player.get("champion") or "").lower() == champion
        and (not position or player.get("position") == position)
    ]
    if not own_candidates:
        own_candidates = [player for player in players if str(player.get("champion") or "").lower() == champion]
    focus = own_candidates[0] if own_candidates else None
    if not focus:
        return None, None
    focus_id = int(number(focus.get("participantId")) or 0) or None
    focus_team = int(number(focus.get("teamId")) or 0)
    opponent_champion = str(match.get("opponentChampion") or "").lower()
    opponent_position = match.get("opponentPosition") or position
    opponents = [
        player for player in players
        if int(number(player.get("teamId")) or 0) != focus_team
        and str(player.get("champion") or "").lower() == opponent_champion
        and (not opponent_position or player.get("position") == opponent_position)
    ]
    if not opponents:
        opponents = [
            player for player in players
            if int(number(player.get("teamId")) or 0) != focus_team
            and (not opponent_position or player.get("position") == opponent_position)
        ]
    opponent_id = int(number(opponents[0].get("participantId")) or 0) or None if opponents else None
    return focus_id, opponent_id


def epic_event_name(event: dict) -> str:
    monster = event.get("monsterSubType") or event.get("monsterType") or "史诗野怪"
    if monster == "BARON_NASHOR":
        return "纳什男爵"
    if monster == "RIFTHERALD":
        return "峡谷先锋"
    if monster == "HORDE":
        return "虚空巢虫"
    return DRAGON_NAMES.get(monster, monster)


def objective_event_position(event: dict) -> dict | None:
    position = event.get("position") or {}
    if position.get("x") is not None and position.get("y") is not None:
        return {"x": position["x"], "y": position["y"]}
    monster = event.get("monsterSubType") or event.get("monsterType")
    if event.get("monsterType") == "DRAGON" or monster == "ELDER_DRAGON":
        return {"x": 9850, "y": 4400}
    if monster in {"BARON_NASHOR", "RIFTHERALD", "HORDE"}:
        return {"x": 5000, "y": 10400}
    return None


def replay_situation_snapshot(replay: dict, match: dict, second: int, objective_horizon: int = 90) -> dict:
    """Build an honest, evidence-labelled situation summary for the map panel."""
    current_second = max(0, int(second))
    current_ms = current_second * 1000
    frame = replay_frame_at(replay, current_second)
    frame_players = {
        int(number(player.get("participantId")) or 0): player
        for player in frame.get("players", [])
    }
    public_players = {
        int(number(player.get("participantId")) or 0): player
        for player in replay.get("players", [])
    }
    focus_id, opponent_id = focus_participant_ids(replay, match)
    focus_public = public_players.get(focus_id or 0, {})
    focus_team = int(number(focus_public.get("teamId")) or 0)
    focus_frame = frame_players.get(focus_id or 0, {})
    opponent_frame = frame_players.get(opponent_id or 0, {})

    events = replay_events(replay)
    next_epic = next((
        event for event in events
        if event.get("type") == "ELITE_MONSTER_KILL"
        and current_ms <= int(number(event.get("timestamp")) or 0) <= current_ms + objective_horizon * 1000
    ), None)
    epic_position = objective_event_position(next_epic) if next_epic else None
    nearby = {100: 0, 200: 0}
    if epic_position:
        for participant_id, player_frame in frame_players.items():
            player_public = public_players.get(participant_id, {})
            team_id = int(number(player_public.get("teamId")) or 0)
            x = number(player_frame.get("x"))
            y = number(player_frame.get("y"))
            if team_id in nearby and x is not None and y is not None:
                if math.dist((x, y), (float(epic_position["x"]), float(epic_position["y"]))) <= 2500:
                    nearby[team_id] += 1

    recent_window_ms = max(0, current_ms - 90_000)
    teamfight_events = detected_teamfight_events(replay)
    recent_events = sorted([
        event for event in [*events, *teamfight_events]
        if recent_window_ms <= int(number(event.get("timestamp")) or 0) <= current_ms
    ], key=lambda event: int(number(event.get("timestamp")) or 0))
    wards_placed = sum(event.get("type") == "WARD_PLACED" for event in recent_events)
    wards_killed = sum(event.get("type") == "WARD_KILL" for event in recent_events)

    def total_cs(player_frame: dict) -> int:
        return int(number(player_frame.get("minions")) or 0) + int(number(player_frame.get("jungleMinions")) or 0)

    current_diffs = {
        "gold": int(number(focus_frame.get("totalGold")) or 0) - int(number(opponent_frame.get("totalGold")) or 0),
        "cs": total_cs(focus_frame) - total_cs(opponent_frame),
        "level": int(number(focus_frame.get("level")) or 0) - int(number(opponent_frame.get("level")) or 0),
    }
    return {
        "phase": replay_phase(current_second),
        "focusId": focus_id,
        "opponentId": opponent_id,
        "focusTeam": focus_team,
        "frame": frame,
        "nextEpic": next_epic,
        "nextEpicName": epic_event_name(next_epic) if next_epic else None,
        "nextEpicPosition": epic_position,
        "secondsUntilEpic": max(0, int(number(next_epic.get("timestamp")) or 0) // 1000 - current_second) if next_epic else None,
        "nearby": nearby,
        "wardsPlaced": wards_placed,
        "wardsKilled": wards_killed,
        "recentEvents": recent_events,
        "currentDiffs": current_diffs,
    }


def confidence_grade(value: float) -> str:
    if value >= 0.75:
        return "高"
    if value >= 0.5:
        return "中"
    return "低"


def objective_loss_events(replay: dict, match: dict) -> list[dict]:
    focus_id, _ = focus_participant_ids(replay, match)
    focus_player = next((
        player for player in replay.get("players", [])
        if int(number(player.get("participantId")) or 0) == focus_id
    ), None)
    focus_team = int(number((focus_player or {}).get("teamId")) or 0)
    if focus_team not in {100, 200}:
        return []
    return [
        event for event in replay_events(replay)
        if event.get("type") == "ELITE_MONSTER_KILL"
        and (event.get("monsterType") == "DRAGON" or event.get("monsterType") == "RIFTHERALD")
        and int(number(event.get("killerTeamId")) or 0) == 300 - focus_team
    ]


def nearest_objective_loss(replay: dict, match: dict, second: int) -> dict | None:
    losses = objective_loss_events(replay, match)
    if not losses:
        return None
    current_ms = max(0, int(second)) * 1000
    return min(
        losses,
        key=lambda event: (
            abs(int(number(event.get("timestamp")) or 0) - current_ms),
            int(number(event.get("timestamp")) or 0) > current_ms,
        ),
    )


def objective_loss_analysis(replay: dict, match: dict, objective_event: dict, window_seconds: int = 90) -> dict:
    """Build an evidence graph for a lost dragon or Rift Herald.

    Observed facts and minute-snapshot estimates remain separate. Hypotheses
    only reference fact IDs and never claim certainty from sequence alone.
    """
    event_ms = int(number(objective_event.get("timestamp")) or 0)
    event_second = event_ms // 1000
    window_start_ms = max(0, event_ms - max(30, int(window_seconds)) * 1000)
    focus_id, opponent_id = focus_participant_ids(replay, match)
    public_players = {
        int(number(player.get("participantId")) or 0): player
        for player in replay.get("players", [])
    }
    team_by_participant = {
        participant_id: int(number(player.get("teamId")) or 0)
        for participant_id, player in public_players.items()
    }
    focus_team = team_by_participant.get(focus_id or 0, 0)
    enemy_team = 300 - focus_team if focus_team in {100, 200} else 0
    frame = replay_frame_at(replay, event_second)
    frame_players = {
        int(number(player.get("participantId")) or 0): player
        for player in frame.get("players", [])
    }
    position = objective_event_position(objective_event)
    window_events = [
        event for event in replay_events(replay)
        if window_start_ms <= int(number(event.get("timestamp")) or 0) <= event_ms
    ]
    window_teamfights = [
        event for event in detected_teamfight_events(replay)
        if window_start_ms <= int(number(event.get("endTimestamp")) or 0) <= event_ms
    ]

    facts = []

    def add_fact(fact_type: str, label: str, confidence: float, **extra) -> str:
        fact_id = f"F{len(facts) + 1}"
        facts.append({
            "id": fact_id, "type": fact_type, "label": label,
            "confidence": round(float(confidence), 2), **extra,
        })
        return fact_id

    objective_name = epic_event_name(objective_event)
    result_fact = add_fact(
        "OBJECTIVE_LOST", f"{format_clock(event_second)} 对方取得{objective_name}", 1.0,
        timestamp=event_ms, position=position, source="Riot事件",
    )

    nearby = {100: 0, 200: 0}
    distances = {}
    if position:
        target = (float(position["x"]), float(position["y"]))
        for participant_id, player_frame in frame_players.items():
            x = number(player_frame.get("x"))
            y = number(player_frame.get("y"))
            if x is None or y is None:
                continue
            distance = math.dist((x, y), target)
            distances[participant_id] = distance
            team_id = team_by_participant.get(participant_id, 0)
            if team_id in nearby and distance <= 2500:
                nearby[team_id] += 1
    nearby_fact = add_fact(
        "OBJECTIVE_AREA_COUNT",
        f"目标区位置估计：己方 {nearby.get(focus_team, 0)} 人，对方 {nearby.get(enemy_team, 0)} 人",
        0.65, sampleTimestamp=int(number(frame.get("timestamp")) or 0), nearby=nearby,
        source="分钟位置快照",
    )

    focus_distance = distances.get(focus_id or 0)
    distance_fact = None
    if focus_distance is not None:
        distance_fact = add_fact(
            "FOCUS_DISTANCE",
            f"你距目标约 {focus_distance / 1000:.1f}k 地图单位",
            0.65, participantId=focus_id, distance=round(focus_distance), source="分钟位置快照",
        )

    deaths = {100: [], 200: []}
    for event in window_events:
        if event.get("type") != "CHAMPION_KILL":
            continue
        victim_id = int(number(event.get("victimId")) or 0)
        victim_team = team_by_participant.get(victim_id, 0)
        if victim_team in deaths:
            deaths[victim_team].append(event)
    own_deaths = deaths.get(focus_team, [])
    enemy_deaths = deaths.get(enemy_team, [])
    death_fact = add_fact(
        "RECENT_DEATHS",
        f"目标前 {window_seconds} 秒：己方 {len(own_deaths)} 次阵亡，对方 {len(enemy_deaths)} 次阵亡",
        1.0, ownDeathCount=len(own_deaths), enemyDeathCount=len(enemy_deaths),
        eventIds=[int(number(event.get("timestamp")) or 0) for event in own_deaths], source="Riot事件",
    )

    teamfight_fact = None
    if window_teamfights:
        own_fight_deaths = sum(
            int(number(event.get("deathsByTeam", {}).get(focus_team)) or 0)
            for event in window_teamfights
        )
        enemy_fight_deaths = sum(
            int(number(event.get("deathsByTeam", {}).get(enemy_team)) or 0)
            for event in window_teamfights
        )
        focus_participations = sum(focus_id in event.get("participantIds", []) for event in window_teamfights)
        teamfight_fact = add_fact(
            "DERIVED_TEAMFIGHTS",
            f"目标前 {window_seconds} 秒：识别到 {len(window_teamfights)} 次团战，己方阵亡 {own_fight_deaths}、对方 {enemy_fight_deaths}",
            max(float(number(event.get("confidence")) or 0) for event in window_teamfights),
            count=len(window_teamfights), ownDeaths=own_fight_deaths, enemyDeaths=enemy_fight_deaths,
            focusParticipations=focus_participations,
            eventIds=[event.get("eventId") for event in window_teamfights],
            source="规则识别（基于精确击杀事件）",
        )

    vision_actions = {100: {"placed": 0, "killed": 0}, 200: {"placed": 0, "killed": 0}}
    for event in window_events:
        if event.get("type") == "WARD_PLACED":
            actor_id = int(number(event.get("creatorId")) or 0)
            team_id = team_by_participant.get(actor_id, 0)
            if team_id in vision_actions:
                vision_actions[team_id]["placed"] += 1
        elif event.get("type") == "WARD_KILL":
            actor_id = int(number(event.get("killerId")) or 0)
            team_id = team_by_participant.get(actor_id, 0)
            if team_id in vision_actions:
                vision_actions[team_id]["killed"] += 1
    own_vision = sum(vision_actions.get(focus_team, {}).values())
    enemy_vision = sum(vision_actions.get(enemy_team, {}).values())
    vision_fact = add_fact(
        "VISION_ACTIONS",
        f"已观察视野动作：己方 {own_vision} 次，对方 {enemy_vision} 次",
        1.0, actions=vision_actions, source="插眼/排眼事件",
    )

    focus_purchases = [
        event for event in window_events
        if event.get("type") == "ITEM_PURCHASED"
        and int(number(event.get("participantId")) or 0) == focus_id
    ]
    purchase_fact = None
    if focus_purchases:
        last_purchase_second = int(number(focus_purchases[-1].get("timestamp")) or 0) // 1000
        purchase_fact = add_fact(
            "FOCUS_SHOPPING",
            f"你在目标前 {event_second - last_purchase_second} 秒发生购买",
            1.0, participantId=focus_id, timestamps=[event.get("timestamp") for event in focus_purchases],
            source="购买事件",
        )

    team_gold = {100: 0, 200: 0}
    for participant_id, player_frame in frame_players.items():
        team_id = team_by_participant.get(participant_id, 0)
        if team_id in team_gold:
            team_gold[team_id] += int(number(player_frame.get("totalGold")) or 0)
    gold_gap = team_gold.get(focus_team, 0) - team_gold.get(enemy_team, 0)
    gold_fact = add_fact(
        "TEAM_GOLD_GAP", f"目标时己方团队经济差 {gold_gap:+,}", 0.65,
        focusGold=team_gold.get(focus_team, 0), enemyGold=team_gold.get(enemy_team, 0),
        source="分钟状态快照",
    )

    trade_events = []
    for event in replay_events(replay):
        timestamp = int(number(event.get("timestamp")) or 0)
        if not (event_ms < timestamp <= event_ms + 60_000):
            continue
        if event.get("type") == "BUILDING_KILL":
            destroyed_team = int(number(event.get("teamId")) or 0)
            if destroyed_team == enemy_team:
                trade_events.append(event)
        elif event.get("type") == "ELITE_MONSTER_KILL" and int(number(event.get("killerTeamId")) or 0) == focus_team:
            trade_events.append(event)
    trade_fact = None
    if trade_events:
        trade_fact = add_fact(
            "CROSS_MAP_TRADE", f"丢失目标后 60 秒内己方取得 {len(trade_events)} 项地图资源",
            1.0, timestamps=[event.get("timestamp") for event in trade_events], source="Riot事件",
        )

    hypotheses = []

    def add_hypothesis(code: str, title: str, confidence: float, evidence_ids: list[str], explanation: str, kind: str = "CAUSE") -> None:
        hypotheses.append({
            "id": f"H{len(hypotheses) + 1}", "code": code, "title": title,
            "confidence": round(min(0.95, max(0.0, confidence)), 2),
            "grade": confidence_grade(confidence), "kind": kind,
            "relation": "MAY_CONTRIBUTE_TO" if kind == "CAUSE" else "MAY_EXPLAIN",
            "evidenceIds": evidence_ids, "resultFactId": result_fact,
            "explanation": explanation,
        })

    lost_teamfights = [
        event for event in window_teamfights
        if int(number(event.get("deathsByTeam", {}).get(focus_team)) or 0)
        > int(number(event.get("deathsByTeam", {}).get(enemy_team)) or 0)
    ]
    if lost_teamfights and teamfight_fact:
        latest_lost_fight = lost_teamfights[-1]
        own_fight_deaths = int(number(latest_lost_fight.get("deathsByTeam", {}).get(focus_team)) or 0)
        enemy_fight_deaths = int(number(latest_lost_fight.get("deathsByTeam", {}).get(enemy_team)) or 0)
        close_to_objective = event_ms - int(number(latest_lost_fight.get("endTimestamp")) or 0) <= 45_000
        add_hypothesis(
            "LOST_TEAMFIGHT_BEFORE_OBJECTIVE", "丢目标前发生团战失利",
            min(0.93, 0.79 + (own_fight_deaths - enemy_fight_deaths) * 0.04 + (0.05 if close_to_objective else 0)),
            [teamfight_fact, death_fact],
            "连续击杀事件被规则聚类为团战，且己方在该团战中阵亡更多；这是可解释的派生事件，不是 Riot 直接提供的团战标签。",
        )

    death_diff = len(own_deaths) - len(enemy_deaths)
    if death_diff > 0:
        last_own_death_ms = max(int(number(event.get("timestamp")) or 0) for event in own_deaths)
        close_death = event_ms - last_own_death_ms <= 45_000
        add_hypothesis(
            "RECENT_TEAM_DEATHS", "目标前己方阵亡更多",
            min(0.88, 0.66 + death_diff * 0.07 + (0.06 if close_death else 0)), [death_fact],
            "精确事件显示己方在准备窗口内损失了更多成员，可能直接削弱争夺人数。",
        )

    nearby_diff = nearby.get(enemy_team, 0) - nearby.get(focus_team, 0)
    if nearby_diff > 0:
        add_hypothesis(
            "AREA_NUMBERS_DISADVANTAGE", "目标区域人数处于劣势",
            min(0.76, 0.55 + nearby_diff * 0.07), [nearby_fact],
            "目标事件所在分钟的位置样本显示，对方在目标区域附近人数更多。",
        )

    focus_role = match.get("position")
    if focus_distance is not None and focus_distance > 3500 and distance_fact:
        add_hypothesis(
            "FOCUS_FAR_FROM_OBJECTIVE", "你在目标事件时距离较远",
            0.66 if focus_role == "JUNGLE" else 0.52, [distance_fact, nearby_fact],
            "位置快照显示你远离目标区域；该证据只能定位到分钟级。",
        )

    if purchase_fact:
        last_purchase_ms = max(int(number(event.get("timestamp")) or 0) for event in focus_purchases)
        purchase_age_seconds = max(0, (event_ms - last_purchase_ms) // 1000)
        had_recent_death = any(int(number(event.get("victimId")) or 0) == focus_id for event in own_deaths)
        if purchase_age_seconds <= 60:
            add_hypothesis(
                "SHOPPING_OVERLAP", "目标准备期与你的购物时间重叠",
                0.38 if had_recent_death else 0.55, [purchase_fact],
                "购买事件可以确认你进入了商店，但不能确认这是主动回城还是死亡后的购买。",
            )

    if enemy_vision - own_vision >= 2:
        add_hypothesis(
            "VISION_ACTION_GAP", "己方目标前视野动作较少", 0.43, [vision_fact],
            "只比较 API 记录到的插眼和排眼动作，不能等同于完整视野覆盖。",
        )

    if gold_gap <= -1500:
        add_hypothesis(
            "TEAM_GOLD_DISADVANTAGE", "团队经济劣势限制争夺", min(0.62, 0.45 + abs(gold_gap) / 20_000), [gold_fact],
            "目标分钟的团队经济快照显示己方装备资源处于劣势。",
        )

    if trade_fact:
        add_hypothesis(
            "CROSS_MAP_TRADE", "可能是跨地图资源交换", 0.72, [trade_fact],
            "己方在目标丢失后很快取得其他地图资源，因此这次放弃不一定完全无收益。", kind="ALTERNATIVE",
        )

    causal = [hypothesis for hypothesis in hypotheses if hypothesis["kind"] == "CAUSE"]
    primary = max(causal, key=lambda hypothesis: hypothesis["confidence"], default=None)
    if not primary:
        add_hypothesis(
            "INSUFFICIENT_EVIDENCE", "现有数据不足以判断主要原因", 0.8,
            [nearby_fact, death_fact, vision_fact, gold_fact],
            "没有检测到强度足够的上游证据；不强行生成因果结论。", kind="LIMITATION",
        )

    edges = []
    for hypothesis in hypotheses:
        for fact_id in hypothesis["evidenceIds"]:
            edges.append({"from": fact_id, "to": hypothesis["id"], "type": "SUPPORTS"})
        edges.append({
            "from": hypothesis["id"], "to": hypothesis["resultFactId"],
            "type": hypothesis["relation"], "confidence": hypothesis["confidence"],
        })

    return {
        "schemaVersion": 1,
        "detectorVersion": "objective-loss-v2",
        "episodeId": f"objective-loss-{event_ms}",
        "objectiveName": objective_name,
        "eventSecond": event_second,
        "windowStartSecond": window_start_ms // 1000,
        "focusTeam": focus_team,
        "enemyTeam": enemy_team,
        "focusId": focus_id,
        "opponentId": opponent_id,
        "position": position,
        "frame": frame,
        "facts": facts,
        "hypotheses": hypotheses,
        "edges": edges,
        "primaryHypothesisId": primary.get("id") if primary else None,
    }


def objective_snapshot(replay: dict, second: int) -> dict:
    """Return objective totals and map markers through an exact event timestamp."""
    cutoff_ms = max(0, int(second)) * 1000
    teams = {
        100: {"towers": 0, "inhibitors": 0, "dragons": [], "elders": 0, "barons": 0, "heralds": 0, "grubs": 0, "soul": None},
        200: {"towers": 0, "inhibitors": 0, "dragons": [], "elders": 0, "barons": 0, "heralds": 0, "grubs": 0, "soul": None},
    }
    markers = []
    soul_type = None
    for event in replay_events(replay):
        timestamp = int(number(event.get("timestamp")) or 0)
        if timestamp > cutoff_ms:
            break
        event_type = event.get("type")
        if event_type == "BUILDING_KILL":
            destroyed_team = int(number(event.get("teamId")) or 0)
            scoring_team = 300 - destroyed_team if destroyed_team in {100, 200} else 0
            building = event.get("buildingType")
            if scoring_team in teams:
                if building == "TOWER_BUILDING":
                    teams[scoring_team]["towers"] += 1
                elif building == "INHIBITOR_BUILDING":
                    teams[scoring_team]["inhibitors"] += 1
            markers.append({**event, "kind": "inhibitor" if building == "INHIBITOR_BUILDING" else "tower", "scoringTeam": scoring_team})
        elif event_type == "ELITE_MONSTER_KILL":
            scoring_team = int(number(event.get("killerTeamId")) or 0)
            if scoring_team not in teams:
                continue
            monster = event.get("monsterType")
            subtype = event.get("monsterSubType")
            if monster == "DRAGON":
                if subtype == "ELDER_DRAGON":
                    teams[scoring_team]["elders"] += 1
                else:
                    teams[scoring_team]["dragons"].append(DRAGON_NAMES.get(subtype, subtype or "龙"))
            elif monster == "BARON_NASHOR":
                teams[scoring_team]["barons"] += 1
            elif monster == "RIFTHERALD":
                teams[scoring_team]["heralds"] += 1
            elif monster == "HORDE":
                teams[scoring_team]["grubs"] += 1
            markers.append({**event, "kind": "monster", "scoringTeam": scoring_team})
        elif event_type == "DRAGON_SOUL_GIVEN":
            team_id = int(number(event.get("teamId")) or 0)
            soul = DRAGON_NAMES.get(event.get("name"), event.get("name") or "龙魂")
            if team_id in teams:
                teams[team_id]["soul"] = soul
                markers.append({**event, "kind": "soul", "scoringTeam": team_id, "position": {"x": 9850, "y": 4400}})
            elif team_id == 0:
                soul_type = soul
    return {"teams": teams, "markers": markers, "soulType": soul_type}


def tab_snapshot(replay: dict, second: int) -> dict[int, dict]:
    """Rebuild current K/D/A and inventory from exact timestamped events."""
    cutoff_ms = max(0, int(second)) * 1000
    state = {
        int(player.get("participantId")): {"kills": 0, "deaths": 0, "assists": 0, "items": []}
        for player in replay.get("players", []) if player.get("participantId")
    }

    def remove_item(participant_state: dict, item_id) -> None:
        item_id = int(number(item_id) or 0)
        if item_id in participant_state["items"]:
            participant_state["items"].remove(item_id)

    for event in replay_events(replay):
        if int(number(event.get("timestamp")) or 0) > cutoff_ms:
            break
        event_type = event.get("type")
        if event_type == "CHAMPION_KILL":
            killer_id = int(number(event.get("killerId")) or 0)
            victim_id = int(number(event.get("victimId")) or 0)
            if killer_id in state:
                state[killer_id]["kills"] += 1
            if victim_id in state:
                state[victim_id]["deaths"] += 1
            for participant_id in event.get("assistingParticipantIds", []):
                participant_id = int(number(participant_id) or 0)
                if participant_id in state:
                    state[participant_id]["assists"] += 1
        elif event_type in {"ITEM_PURCHASED", "ITEM_SOLD", "ITEM_DESTROYED", "ITEM_UNDO"}:
            participant_id = int(number(event.get("participantId")) or 0)
            participant_state = state.get(participant_id)
            if not participant_state:
                continue
            if event_type == "ITEM_PURCHASED":
                item_id = int(number(event.get("itemId")) or 0)
                if item_id:
                    participant_state["items"].append(item_id)
            elif event_type in {"ITEM_SOLD", "ITEM_DESTROYED"}:
                remove_item(participant_state, event.get("itemId"))
            else:
                remove_item(participant_state, event.get("beforeId"))
                after_id = int(number(event.get("afterId")) or 0)
                if after_id:
                    participant_state["items"].append(after_id)
    return state


class ComparatorApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1500x900")
        self.minsize(1120, 680)
        self.configure(bg=PALETTE["root"])
        self.data_dir = app_data_dir()
        self.key_path = self.data_dir / "riot_api_key.txt"
        self.case_path = self.data_dir / "player_case.json"
        self.settings = load_settings(resource_path("config/model-parameters.json"))
        self.baseline_payload = json.loads(resource_path("desktop/all-champion-baselines.json").read_text(encoding="utf-8"))
        self.baselines = self.baseline_payload.get("profiles", {})
        item_payload = json.loads(resource_path("assets/item-data.json").read_text(encoding="utf-8"))
        self.item_entries = {int(item_id): item for item_id, item in item_payload.get("data", {}).items()}
        self.item_names = {
            int(item_id): item.get("name") or str(item_id)
            for item_id, item in item_payload.get("data", {}).items()
        }
        spell_payload = json.loads(resource_path("assets/summoner-spells.json").read_text(encoding="utf-8"))
        self.spell_entries = {
            int(spell.get("key")): spell for spell in spell_payload.get("data", {}).values()
            if str(spell.get("key") or "").isdigit()
        }
        champion_manifest = resource_path(f"assets/ddragon/{DDRAGON_VERSION}/champion.json")
        champion_payload = json.loads(champion_manifest.read_text(encoding="utf-8")) if champion_manifest.exists() else {"data": {}}
        self.champion_files = {
            str(champion.get("id") or "").lower(): champion.get("image", {}).get("full")
            for champion in champion_payload.get("data", {}).values()
        }
        self.icon_cache = {}
        self.sprite_cache = {}
        self.tooltip_window = None
        self.dashboard_cards = []
        self.header_canvas = None
        self.header_control_window = None
        self.form_canvas = None
        self.form_hitboxes = []
        self.status_canvas = None
        self.animation_phase = 0.0
        self.animation_started = time.monotonic()
        self.animation_job = None
        self.selection_flash = 0.0
        replay_path = resource_path("desktop/bootstrap-replays.json")
        self.bootstrap_replays = json.loads(replay_path.read_text(encoding="utf-8")) if replay_path.exists() else {}
        self.case = self._load_case()
        self.refreshing = False
        self.replay_data = None
        self.replay_playing = False
        self.replay_job = None
        self.replay_second = tk.IntVar(value=0)
        self.map_layer_mode = tk.StringVar(value="SITUATION")
        self.selected_phase = tk.StringVar(value="EARLY")
        self.riot_id = tk.StringVar(value=self.case.get("meta", {}).get("riotId", "Geolonwe#OC"))
        self.api_key = tk.StringVar()
        self.auto_refresh = tk.BooleanVar(value=True)
        self.status_text = tk.StringVar(value="程序已就绪")
        self._configure_style()
        self._build_ui()
        self._populate_matches()
        self.protocol("WM_DELETE_WINDOW", self._shutdown)
        self.animation_job = self.after(45, self._animate_ui)
        self.after(5000, self._auto_tick)

    def _load_case(self) -> dict:
        if self.case_path.exists():
            try:
                return json.loads(self.case_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                pass
        return load_bootstrap_case(resource_path("assets/player-case.js"))

    def _configure_style(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TFrame", background=PALETTE["root"])
        style.configure("Panel.TFrame", background=PALETTE["panel"])
        style.configure("Header.TFrame", background="#0b171d")
        style.configure("Header.TLabel", background="#0b171d", foreground="#b8c9cf", font=("Microsoft YaHei UI", 9))
        style.configure("TLabel", background=PALETTE["root"], foreground=PALETTE["text"], font=("Microsoft YaHei UI", 10))
        style.configure("Title.TLabel", foreground="#e9bd59", font=("Microsoft YaHei UI", 21, "bold"))
        style.configure("Muted.TLabel", foreground=PALETTE["muted"], font=("Microsoft YaHei UI", 9))
        style.configure("Card.TLabel", background=PALETTE["panel"], foreground=PALETTE["gold"], font=("Microsoft YaHei UI", 15, "bold"))
        style.configure("TButton", background="#17242c", foreground="#dbe8ed", borderwidth=0, padding=(14, 9), font=("Microsoft YaHei UI", 10, "bold"))
        style.map("TButton", background=[("active", "#203740")], foreground=[("active", "#6de1dc")])
        style.configure("Accent.TButton", background="#c69438", foreground="#071015")
        style.map("Accent.TButton", background=[("active", "#e9bd59")])
        style.configure("Timeline.TButton", background="#17242c", foreground="#dbe8ed", padding=(9, 6), font=("Microsoft YaHei UI", 9, "bold"))
        style.map("Timeline.TButton", background=[("active", "#203740")], foreground=[("active", "#6de1dc")])
        style.configure("MapLayer.TRadiobutton", background="#0c1319", foreground="#78909a", padding=(10, 6), font=("Microsoft YaHei UI", 9, "bold"))
        style.map("MapLayer.TRadiobutton", foreground=[("selected", "#f4ca68")], background=[("selected", "#172830")])
        style.configure("TRadiobutton", background="#0c1319", foreground="#a9bbc2", padding=(10, 7), font=("Microsoft YaHei UI", 10, "bold"))
        style.map("TRadiobutton", foreground=[("selected", "#6de1dc")], background=[("selected", "#13252b")])
        style.configure("Treeview", background="#0b1217", fieldbackground="#0b1217", foreground="#d7e4e9", borderwidth=0, rowheight=31, font=("Microsoft YaHei UI", 9))
        style.map("Treeview", background=[("selected", "#18313a")], foreground=[("selected", "#f6d27b")])
        style.configure("Treeview.Heading", background="#111d23", foreground="#91a8b1", relief="flat", font=("Microsoft YaHei UI", 9, "bold"), padding=(6, 9))
        style.map("Treeview.Heading", background=[("active", "#182a32")])
        style.configure("Score.Treeview", background="#0b1217", fieldbackground="#0b1217", foreground="#d7e4e9", borderwidth=0, rowheight=18, font=("Microsoft YaHei UI", 8))
        style.map("Score.Treeview", background=[("selected", "#18313a")], foreground=[("selected", "#f6d27b")])
        style.configure("Score.Treeview.Heading", background="#111d23", foreground="#91a8b1", relief="flat", font=("Microsoft YaHei UI", 8, "bold"), padding=(3, 2))
        style.configure("TEntry", fieldbackground="#111b21", foreground="#e4edf0", insertcolor="#6de1dc", borderwidth=1, padding=8)
        style.configure("TCheckbutton", background="#070b0f", foreground="#9db0b8", font=("Microsoft YaHei UI", 9))
        style.configure("TNotebook", background="#0c1319", borderwidth=0)
        style.configure("TNotebook.Tab", background="#111d23", foreground="#93a8b0", padding=(16, 8), font=("Microsoft YaHei UI", 10, "bold"))
        style.map("TNotebook.Tab", background=[("selected", "#18313a")], foreground=[("selected", "#e9bd59")])

    def _build_ui(self) -> None:
        self.header_canvas = tk.Canvas(self, height=112, bg=PALETTE["root"], highlightthickness=0, bd=0)
        self.header_canvas.pack(fill="x")
        self.header_canvas.bind("<Configure>", self._on_header_resize)
        self._draw_header_gradient()
        self.header_canvas.create_text(24, 32, text="峡谷天平", fill=PALETTE["gold"], font=("Microsoft YaHei UI", 22, "bold"), anchor="w", tags=("header_content",))
        self.header_canvas.create_text(25, 63, text="HIGH-RANK MATCH LAB", fill=PALETTE["teal"], font=("Consolas", 9, "bold"), anchor="w", tags=("header_content",))
        self.header_canvas.create_text(25, 84, text="OCE D4+ 基准 · 每一局都有上下文", fill="#8ca1a9", font=("Microsoft YaHei UI", 9), anchor="w", tags=("header_content",))

        controls = ttk.Frame(self.header_canvas, style="Header.TFrame", padding=(14, 9))
        ttk.Label(controls, text="Riot ID", style="Header.TLabel").grid(row=0, column=0, sticky="w", padx=(0, 6))
        ttk.Entry(controls, textvariable=self.riot_id, width=25).grid(row=1, column=0, padx=(0, 10))
        ttk.Label(controls, text="API Key（仅保存在本机）", style="Header.TLabel").grid(row=0, column=1, sticky="w", padx=(0, 6))
        ttk.Entry(controls, textvariable=self.api_key, show="●", width=31).grid(row=1, column=1, padx=(0, 10))
        ttk.Button(controls, text="仅保存 Key", command=self._save_key).grid(row=1, column=2, padx=(0, 8))
        ttk.Button(controls, text="应用输入并刷新", style="Accent.TButton", command=self.refresh_player).grid(row=1, column=3)
        self.header_control_window = self.header_canvas.create_window(1476, 16, window=controls, anchor="ne", tags=("header_content",))

        cards = ttk.Frame(self, padding=(22, 0, 22, 7))
        cards.pack(fill="x")
        meta = self.case.get("meta", {})
        card_values = [
            ("样本宇宙", "D4+ 玩家单局", int(self.baseline_payload.get("meta", {}).get("sourceRows", 0)), "samples"),
            ("条件模型", "英雄 × 位置 × 阶段", int(self.baseline_payload.get("meta", {}).get("profileCount", 0)), "profiles"),
            ("当前档案", "最近单双排", int(meta.get("rankedSoloMatches", 0)), "matches"),
            ("自动检查", "后台轮询", 60, "pulse"),
        ]
        for index, (label, subtitle, value, kind) in enumerate(card_values):
            card = tk.Canvas(cards, height=82, bg=PALETTE["root"], highlightthickness=0, bd=0, cursor="hand2")
            card.grid(row=0, column=index, sticky="ew", padx=(0 if index == 0 else 6, 0))
            cards.columnconfigure(index, weight=1)
            card_state = {"canvas": card, "label": label, "subtitle": subtitle, "target": value, "kind": kind, "hover": 0.0, "hoverTarget": 0.0}
            self.dashboard_cards.append(card_state)
            card.bind("<Enter>", lambda _event, item=card_state: item.update(hoverTarget=1.0))
            card.bind("<Leave>", lambda _event, item=card_state: item.update(hoverTarget=0.0))
            card.bind("<Configure>", lambda _event, item=card_state: self._draw_dashboard_card(item))

        self.form_canvas = tk.Canvas(self, height=48, bg=PALETTE["root"], highlightthickness=0, bd=0, cursor="hand2")
        self.form_canvas.pack(fill="x", padx=22, pady=(0, 9))
        self.form_canvas.bind("<Configure>", lambda _event: self._render_form_strip())
        self.form_canvas.bind("<Button-1>", self._form_strip_click)

        body = ttk.Panedwindow(self, orient="horizontal")
        body.pack(fill="both", expand=True, padx=22, pady=(0, 7))
        left = ttk.Frame(body, style="Panel.TFrame", padding=10)
        right = ttk.Frame(body, style="Panel.TFrame", padding=10)
        body.add(left, weight=1)
        body.add(right, weight=4)

        ttk.Label(left, text="最近单双排", background="#0c1319", foreground="#e9bd59", font=("Microsoft YaHei UI", 12, "bold")).pack(anchor="w", pady=(0, 8))
        self.match_tree = ttk.Treeview(left, columns=("result", "matchup", "duration"), show="headings", selectmode="browse")
        self.match_tree.heading("result", text="结果")
        self.match_tree.heading("matchup", text="你 vs 对位")
        self.match_tree.heading("duration", text="时长")
        self.match_tree.column("result", width=48, anchor="center", stretch=False)
        self.match_tree.column("matchup", width=210, anchor="w")
        self.match_tree.column("duration", width=60, anchor="center", stretch=False)
        left_scroll = ttk.Scrollbar(left, orient="vertical", command=self.match_tree.yview)
        self.match_tree.configure(yscrollcommand=left_scroll.set)
        self.match_tree.pack(side="left", fill="both", expand=True)
        left_scroll.pack(side="right", fill="y")
        self.match_tree.bind("<<TreeviewSelect>>", self._on_match_selected)

        top_line = ttk.Frame(right, style="Panel.TFrame")
        top_line.pack(fill="x", pady=(0, 8))
        self.match_title = ttk.Label(top_line, text="请选择比赛", background="#0c1319", foreground="#e9bd59", font=("Microsoft YaHei UI", 13, "bold"))
        self.match_title.pack(side="left")
        phase_box = ttk.Frame(top_line, style="Panel.TFrame")
        phase_box.pack(side="right")
        for phase in ("EARLY", "MID", "LATE"):
            ttk.Radiobutton(phase_box, text=PHASE_NAMES[phase], value=phase, variable=self.selected_phase, command=self._render_comparison).pack(side="left")

        self.explanation = ttk.Label(
            right,
            text="正负号只表示数值方向，不自动判断好坏。双方基准分别按各自英雄＋位置匹配。",
            style="Muted.TLabel",
            background="#0c1319",
        )
        self.explanation.pack(anchor="w", pady=(0, 8))

        self.notebook = ttk.Notebook(right)
        self.notebook.pack(fill="both", expand=True)
        compare_tab = ttk.Frame(self.notebook, style="Panel.TFrame")
        replay_tab = ttk.Frame(self.notebook, style="Panel.TFrame")
        self.notebook.add(compare_tab, text="数据对比")
        self.notebook.add(replay_tab, text="整场小地图")

        columns = ("metric", "player", "opponent", "player_base", "opponent_base", "head_gap", "player_gap", "opponent_gap", "player_pct", "opponent_pct")
        self.comparison_tree = ttk.Treeview(compare_tab, columns=columns, show="headings")
        headings = {
            "metric": "指标", "player": "你本局", "opponent": "对手本局", "player_base": "你英雄基准",
            "opponent_base": "对手英雄基准", "head_gap": "你−对手", "player_gap": "你−基准",
            "opponent_gap": "对手−基准", "player_pct": "你分位", "opponent_pct": "对手分位",
        }
        headings["player_base"] = "你英雄基准（n=局数）"
        headings["opponent_base"] = "对手英雄基准（n=局数）"
        widths = {"metric": 190, "player": 82, "opponent": 82, "player_base": 125, "opponent_base": 125, "head_gap": 90, "player_gap": 90, "opponent_gap": 100, "player_pct": 65, "opponent_pct": 70}
        for column in columns:
            self.comparison_tree.heading(column, text=headings[column])
            self.comparison_tree.column(column, width=widths[column], anchor="w" if column == "metric" else "center", stretch=column in {"metric", "player_base", "opponent_base"})
        self.comparison_tree.tag_configure("stripe", background="#0d171d")
        self.comparison_tree.tag_configure("phase_note", foreground=PALETTE["gold"])
        right_vscroll = ttk.Scrollbar(compare_tab, orient="vertical", command=self.comparison_tree.yview)
        right_hscroll = ttk.Scrollbar(compare_tab, orient="horizontal", command=self.comparison_tree.xview)
        self.comparison_tree.configure(yscrollcommand=right_vscroll.set, xscrollcommand=right_hscroll.set)
        compare_tab.columnconfigure(0, weight=1)
        compare_tab.rowconfigure(0, weight=1)
        self.comparison_tree.grid(row=0, column=0, sticky="nsew")
        right_vscroll.grid(row=0, column=1, sticky="ns")
        right_hscroll.grid(row=1, column=0, sticky="ew")

        timeline = ttk.Frame(replay_tab, style="Panel.TFrame", padding=(10, 7, 10, 5))
        timeline.pack(fill="x")
        timeline.columnconfigure(1, weight=1)
        ttk.Label(
            timeline, text="复盘时间线（拖动滑块即可跳转）", background="#0c1319",
            foreground="#e9bd59", font=("Microsoft YaHei UI", 10, "bold"),
        ).grid(row=0, column=0, sticky="w", pady=(0, 2))
        self.timeline_value_text = tk.StringVar(value="00:00 / --:--")
        ttk.Label(
            timeline, textvariable=self.timeline_value_text, background="#0c1319",
            foreground="#6de1dc", font=("Consolas", 11, "bold"),
        ).grid(row=0, column=1, sticky="e", pady=(0, 2))

        jump_buttons = ttk.Frame(timeline, style="Panel.TFrame")
        jump_buttons.grid(row=1, column=0, sticky="w", padx=(0, 10))
        ttk.Button(jump_buttons, text="|◀", width=4, style="Timeline.TButton", command=lambda: self._jump_replay_edge(False)).pack(side="left", padx=(0, 4))
        ttk.Button(jump_buttons, text="−60s", width=5, style="Timeline.TButton", command=lambda: self._jump_replay(-60)).pack(side="left", padx=(0, 4))
        ttk.Button(jump_buttons, text="−10s", width=5, style="Timeline.TButton", command=lambda: self._jump_replay(-10)).pack(side="left", padx=(0, 4))
        self.replay_button = ttk.Button(jump_buttons, text="播放", width=6, style="Timeline.TButton", command=self._toggle_replay)
        self.replay_button.pack(side="left", padx=(0, 4))
        ttk.Button(jump_buttons, text="+10s", width=5, style="Timeline.TButton", command=lambda: self._jump_replay(10)).pack(side="left", padx=(0, 4))
        ttk.Button(jump_buttons, text="+60s", width=5, style="Timeline.TButton", command=lambda: self._jump_replay(60)).pack(side="left", padx=(0, 4))
        ttk.Button(jump_buttons, text="▶|", width=4, style="Timeline.TButton", command=lambda: self._jump_replay_edge(True)).pack(side="left")

        self.replay_scale = tk.Scale(
            timeline, orient="horizontal", variable=self.replay_second, command=self._seek_replay,
            from_=0, to=1, resolution=1, showvalue=False,
            bg="#0c1319", fg="#8fa6af", troughcolor="#203740", activebackground="#e9bd59",
            highlightthickness=0, bd=0, sliderlength=22, width=13, font=("Microsoft YaHei UI", 8),
        )
        self.replay_scale.grid(row=1, column=1, sticky="ew")
        self.replay_scale.bind("<ButtonPress-1>", self._timeline_pointer)
        self.replay_scale.bind("<B1-Motion>", self._timeline_pointer)
        timeline_ticks = ttk.Frame(timeline, style="Panel.TFrame")
        timeline_ticks.grid(row=2, column=1, sticky="ew", padx=(7, 7))
        self.timeline_tick_texts = [tk.StringVar(value="--:--") for _ in range(5)]
        for index, tick_text in enumerate(self.timeline_tick_texts):
            timeline_ticks.columnconfigure(index, weight=1)
            ttk.Label(
                timeline_ticks, textvariable=tick_text, style="Muted.TLabel", background="#0c1319",
            ).grid(row=0, column=index, sticky="w" if index == 0 else "e" if index == 4 else "")

        replay_body = ttk.Frame(replay_tab, style="Panel.TFrame", padding=(8, 3, 8, 4))
        replay_body.pack(fill="x")
        replay_body.columnconfigure(1, weight=1)
        self.map_source_photo = tk.PhotoImage(file=str(resource_path("assets/map11.png")))
        self.map_photo = self.map_source_photo.zoom(3, 3).subsample(5, 5)
        self.map_width = self.map_photo.width()
        self.map_height = self.map_photo.height()
        self.map_canvas = tk.Canvas(
            replay_body, width=self.map_width, height=self.map_height, bg="#05090c",
            highlightthickness=1, highlightbackground="#29404a",
        )
        self.map_canvas.grid(row=0, column=0, sticky="nw", padx=(0, 14))
        self.map_canvas.create_image(0, 0, image=self.map_photo, anchor="nw", tags=("map",))

        replay_side = ttk.Frame(replay_body, style="Panel.TFrame")
        replay_side.grid(row=0, column=1, sticky="nsew")
        replay_side.columnconfigure(0, weight=1)
        replay_side.rowconfigure(4, weight=1)
        self.replay_time_text = tk.StringVar(value="请选择一场比赛")
        ttk.Label(
            replay_side, textvariable=self.replay_time_text, background="#0c1319",
            foreground="#e9bd59", font=("Microsoft YaHei UI", 12, "bold"),
        ).grid(row=0, column=0, sticky="w", pady=(0, 4))
        ttk.Label(
            replay_side, text="人物坐标约每 60 秒采样；事件按毫秒记录；推断信息会明确标注",
            style="Muted.TLabel", background="#0c1319",
        ).grid(row=1, column=0, sticky="w", pady=(0, 6))

        layer_controls = ttk.Frame(replay_side, style="Panel.TFrame")
        layer_controls.grid(row=2, column=0, sticky="ew", pady=(0, 5))
        ttk.Label(
            layer_controls, text="地图信息层", background="#0c1319", foreground="#e9bd59",
            font=("Microsoft YaHei UI", 10, "bold"),
        ).pack(side="left", padx=(0, 9))
        for value, label in (("SITUATION", "局面"), ("EVENTS", "事件"), ("COMPARE", "对比"), ("CAUSES", "原因")):
            ttk.Radiobutton(
                layer_controls, text=label, value=value, variable=self.map_layer_mode,
                command=self._change_map_layer, style="MapLayer.TRadiobutton",
            ).pack(side="left", padx=(0, 4))

        self.replay_layer_caption = tk.StringVar(value="局面 · 当前目标窗口与区域人数")
        ttk.Label(
            replay_side, textvariable=self.replay_layer_caption, style="Muted.TLabel", background="#0c1319",
        ).grid(row=3, column=0, sticky="w", pady=(0, 4))
        self.replay_insight_canvas = tk.Canvas(
            replay_side, height=220, bg="#081015", highlightthickness=1,
            highlightbackground="#20343d", bd=0,
        )
        self.replay_insight_canvas.grid(row=4, column=0, sticky="nsew")

        scoreboard = ttk.Frame(replay_tab, style="Panel.TFrame", padding=(8, 2, 8, 5))
        scoreboard.pack(fill="both", expand=True)
        scoreboard.columnconfigure(0, weight=1)
        scoreboard.columnconfigure(1, weight=1)
        ttk.Label(
            scoreboard, text="TAB 对局面板 · 当前时刻", background="#0c1319", foreground="#e9bd59",
            font=("Microsoft YaHei UI", 10, "bold"),
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 3))
        self.scoreboard_canvases = {}
        for column_index, (team_id, team_name, color) in enumerate(((100, "蓝方", "#63dcff"), (200, "红方", "#ff8577"))):
            panel = ttk.Frame(scoreboard, style="Panel.TFrame")
            panel.grid(row=1, column=column_index, sticky="nsew", padx=(0, 5) if column_index == 0 else (5, 0))
            canvas = tk.Canvas(panel, height=104, bg="#091116", highlightthickness=1, highlightbackground=color, bd=0)
            canvas.pack(fill="both", expand=True)
            self.scoreboard_canvases[team_id] = canvas

        footer = ttk.Frame(self, padding=(22, 4, 22, 9))
        footer.pack(fill="x")
        ttk.Checkbutton(footer, text="每 1 分钟自动检查新比赛", variable=self.auto_refresh).pack(side="left")
        ttk.Label(footer, text=" · 对局进行中无法读取实时坐标", style="Muted.TLabel").pack(side="left")
        self.status_canvas = tk.Canvas(footer, width=420, height=26, bg=PALETTE["root"], highlightthickness=0, bd=0)
        self.status_canvas.pack(side="right")

    @staticmethod
    def _rounded_rectangle(canvas: tk.Canvas, x1: float, y1: float, x2: float, y2: float, radius: float, **kwargs):
        radius = min(radius, (x2 - x1) / 2, (y2 - y1) / 2)
        points = [
            x1 + radius, y1, x2 - radius, y1, x2, y1, x2, y1 + radius,
            x2, y2 - radius, x2, y2, x2 - radius, y2, x1 + radius, y2,
            x1, y2, x1, y2 - radius, x1, y1 + radius, x1, y1,
        ]
        return canvas.create_polygon(points, smooth=True, splinesteps=18, **kwargs)

    def _draw_header_gradient(self) -> None:
        canvas = self.header_canvas
        if not canvas:
            return
        width = max(1100, canvas.winfo_width())
        canvas.delete("header_gradient")
        for y in range(0, 112, 4):
            color = blend_hex("#061017", "#10262b", y / 112)
            canvas.create_rectangle(0, y, width, y + 4, fill=color, outline="", tags=("header_gradient",))
        canvas.create_line(0, 110, width, 110, fill="#29434a", width=1, tags=("header_gradient",))
        canvas.tag_lower("header_gradient")

    def _on_header_resize(self, event) -> None:
        self._draw_header_gradient()
        if self.header_control_window:
            self.header_canvas.coords(self.header_control_window, max(1090, event.width) - 22, 14)
        self.header_canvas.tag_raise("header_content")

    def _draw_header_ambient(self) -> None:
        canvas = self.header_canvas
        if not canvas:
            return
        width = max(1100, canvas.winfo_width())
        canvas.delete("ambient")
        center_x = width * 0.34 + math.sin(self.animation_phase * 0.55) * 90
        center_y = 48 + math.cos(self.animation_phase * 0.7) * 8
        for index, radius in enumerate((170, 135, 100, 68)):
            strength = (4 - index) / 4 * 0.22
            color = blend_hex("#0b1b21", "#1d6d70", strength)
            canvas.create_oval(center_x - radius, center_y - radius * 0.45, center_x + radius, center_y + radius * 0.45, fill=color, outline="", tags=("ambient",))
        gold_x = width * 0.73 + math.cos(self.animation_phase * 0.35) * 70
        canvas.create_line(gold_x - 110, 109, gold_x + 110, 109, fill=blend_hex("#29434a", PALETTE["gold"], 0.48 + 0.22 * math.sin(self.animation_phase)), width=2, tags=("ambient",))
        canvas.tag_raise("ambient", "header_gradient")
        canvas.tag_raise("header_content")

    def _draw_dashboard_card(self, card: dict) -> None:
        canvas = card["canvas"]
        width = max(220, canvas.winfo_width())
        hover = card["hover"]
        canvas.delete("all")
        background = blend_hex(PALETTE["panel"], PALETTE["panel_hover"], hover)
        border = blend_hex(PALETTE["line"], PALETTE["teal"], hover * 0.65)
        self._rounded_rectangle(canvas, 1, 2, width - 1, 79, 13, fill=background, outline=border, width=1)
        canvas.create_rectangle(1, 15, 4, 66, fill=blend_hex(PALETTE["gold"], PALETTE["teal"], hover), outline="")

        icon_x, icon_y = 25, 41
        kind = card["kind"]
        icon_color = blend_hex(PALETTE["gold"], PALETTE["teal"], hover)
        if kind == "samples":
            for index, height in enumerate((13, 23, 32)):
                canvas.create_rectangle(icon_x - 12 + index * 8, icon_y + 17 - height, icon_x - 7 + index * 8, icon_y + 17, fill=icon_color, outline="")
        elif kind == "profiles":
            points = []
            for index in range(6):
                angle = math.pi / 3 * index - math.pi / 2
                points.extend((icon_x + math.cos(angle) * 16, icon_y + math.sin(angle) * 16))
            canvas.create_polygon(points, fill="#15252b", outline=icon_color, width=2)
            canvas.create_oval(icon_x - 4, icon_y - 4, icon_x + 4, icon_y + 4, fill=icon_color, outline="")
        elif kind == "matches":
            for offset in (-7, 0, 7):
                canvas.create_oval(icon_x + offset - 6, icon_y - 6, icon_x + offset + 6, icon_y + 6, fill="#15252b", outline=icon_color, width=2)
        else:
            pulse = (math.sin(self.animation_phase * 1.7) + 1) / 2
            canvas.create_oval(icon_x - 8 - pulse * 5, icon_y - 8 - pulse * 5, icon_x + 8 + pulse * 5, icon_y + 8 + pulse * 5, outline=blend_hex("#24434a", PALETTE["teal"], 0.35 + pulse * 0.45), width=2)
            canvas.create_oval(icon_x - 5, icon_y - 5, icon_x + 5, icon_y + 5, fill=PALETTE["teal"] if self.auto_refresh.get() else PALETTE["muted"], outline="")

        progress = min(1.0, max(0.0, (time.monotonic() - self.animation_started) / 0.8))
        eased = 1 - (1 - progress) ** 3
        value = "每 1 分钟" if kind == "pulse" else f"{round(card['target'] * eased):,}"
        canvas.create_text(51, 20, text=card["label"], fill="#93a8b0", font=("Microsoft YaHei UI", 9, "bold"), anchor="w")
        canvas.create_text(51, 49, text=value, fill=blend_hex(PALETTE["gold"], PALETTE["gold_soft"], hover), font=("Microsoft YaHei UI", 16, "bold"), anchor="w")
        canvas.create_text(width - 14, 57, text=card["subtitle"], fill="#708891", font=("Microsoft YaHei UI", 8), anchor="e")

    def _render_form_strip(self) -> None:
        if not self.form_canvas or not hasattr(self, "match_tree"):
            return
        canvas = self.form_canvas
        width = max(800, canvas.winfo_width())
        canvas.delete("form_base")
        self.form_hitboxes = []
        self.form_positions = {}
        self._rounded_rectangle(canvas, 1, 1, width - 1, 46, 12, fill="#091319", outline="#1b3038", width=1, tags=("form_base",))
        matches = list(self.case.get("matches", [])[:18])
        summary = recent_form_summary(matches)
        canvas.create_text(16, 15, text="近期手感", fill=PALETTE["gold"], font=("Microsoft YaHei UI", 9, "bold"), anchor="w", tags=("form_base",))
        streak = ""
        if summary["streak"]:
            streak = f" · {'连胜' if summary['streakWin'] else '连败'} {summary['streak']}"
        canvas.create_text(16, 32, text=f"{summary['games']} 场 · 胜率 {summary['winRate'] * 100:.0f}%{streak}", fill="#7f959e", font=("Microsoft YaHei UI", 8), anchor="w", tags=("form_base",))
        if not matches:
            canvas.create_text(width / 2, 24, text="刷新玩家后生成近期战绩轨迹", fill=PALETTE["muted"], font=("Microsoft YaHei UI", 9), tags=("form_base",))
            return
        spacing = min(34, max(25, (width - 390) / max(1, len(matches) - 1)))
        total_width = spacing * (len(matches) - 1)
        start_x = max(165, (width - total_width) / 2)
        canvas.create_line(start_x, 24, start_x + total_width, 24, fill="#263a42", width=2, tags=("form_base",))
        chronological = list(reversed(list(enumerate(matches))))
        for display_index, (original_index, match) in enumerate(chronological):
            x = start_x + display_index * spacing
            color = PALETTE["teal"] if match.get("win") else PALETTE["red"]
            icon = self._champion_icon(match.get("champion"), 20)
            tag = f"form_match_{original_index}"
            if icon:
                canvas.create_image(x, 24, image=icon, tags=("form_base", tag))
            else:
                canvas.create_oval(x - 9, 15, x + 9, 33, fill="#122128", outline="", tags=("form_base", tag))
            canvas.create_oval(x - 11, 13, x + 11, 35, outline=color, width=2, tags=("form_base", tag))
            self._bind_tooltip(canvas, tag, f"{'胜' if match.get('win') else '负'} · {match.get('champion')} vs {match.get('opponentChampion') or '未知'} · {match.get('durationMin')} 分钟")
            self.form_hitboxes.append((x - 14, x + 14, original_index))
            self.form_positions[original_index] = x
        canvas.create_text(width - 16, 16, text=f"{summary['wins']} W", fill=PALETTE["teal"], font=("Consolas", 10, "bold"), anchor="e", tags=("form_base",))
        canvas.create_text(width - 16, 32, text=f"{summary['losses']} L", fill=PALETTE["red"], font=("Consolas", 9, "bold"), anchor="e", tags=("form_base",))

    def _animate_form_marker(self) -> None:
        if not self.form_canvas:
            return
        canvas = self.form_canvas
        canvas.delete("form_pulse")
        selected = self.match_tree.selection() if hasattr(self, "match_tree") else ()
        if not selected:
            return
        try:
            selected_index = int(selected[0])
        except ValueError:
            return
        x = getattr(self, "form_positions", {}).get(selected_index)
        if x is None:
            return
        pulse = (math.sin(self.animation_phase * 2.0) + 1) / 2
        radius = 13 + pulse * 3
        canvas.create_oval(x - radius, 24 - radius, x + radius, 24 + radius, outline=blend_hex("#5d512d", PALETTE["gold_soft"], pulse), width=2, tags=("form_pulse",))

    def _form_strip_click(self, event) -> None:
        for left, right, index in self.form_hitboxes:
            if left <= event.x <= right:
                iid = str(index)
                if self.match_tree.exists(iid):
                    self.match_tree.selection_set(iid)
                    self.match_tree.focus(iid)
                    self.match_tree.see(iid)
                return

    def _draw_status_pill(self) -> None:
        if not self.status_canvas:
            return
        canvas = self.status_canvas
        canvas.delete("all")
        status = self.status_text.get()
        if self.refreshing:
            color = PALETTE["gold"]
        elif any(token in status for token in ("失败", "失效", "等待")):
            color = PALETTE["red"]
        else:
            color = PALETTE["teal"]
        pulse = (math.sin(self.animation_phase * 1.8) + 1) / 2
        canvas.create_oval(8 - pulse * 3, 13 - pulse * 3, 16 + pulse * 3, 21 + pulse * 3, outline=blend_hex(PALETTE["root"], color, 0.35 + pulse * 0.45), width=2)
        canvas.create_oval(10, 15, 14, 19, fill=color, outline="")
        canvas.create_text(24, 17, text=status, fill="#80969f", font=("Microsoft YaHei UI", 8), anchor="w")

    def _animate_ui(self) -> None:
        try:
            self.animation_phase += 0.075
            self._draw_header_ambient()
            for card in self.dashboard_cards:
                target = card["hoverTarget"]
                card["hover"] += (target - card["hover"]) * 0.18
                self._draw_dashboard_card(card)
            self._animate_form_marker()
            self._draw_status_pill()
            if self.selection_flash > 0 and hasattr(self, "match_title"):
                self.selection_flash = max(0.0, self.selection_flash - 0.055)
                self.match_title.configure(foreground=blend_hex(PALETTE["gold"], "#fff4c7", self.selection_flash))
            self.animation_job = self.after(45, self._animate_ui)
        except tk.TclError:
            self.animation_job = None

    def _update_dynamic_cards(self) -> None:
        match_count = int(self.case.get("meta", {}).get("rankedSoloMatches", len(self.case.get("matches", []))) or 0)
        for card in self.dashboard_cards:
            if card["kind"] == "matches":
                card["target"] = match_count
        self.animation_started = time.monotonic()
        self._render_form_strip()

    def _shutdown(self) -> None:
        self._stop_replay()
        if self.animation_job is not None:
            try:
                self.after_cancel(self.animation_job)
            except tk.TclError:
                pass
            self.animation_job = None
        self.destroy()

    def _fit_photo(self, photo: tk.PhotoImage, target: int) -> tk.PhotoImage:
        factor = max(1, round(max(photo.width(), photo.height()) / max(1, target)))
        return photo.subsample(factor, factor)

    def _champion_icon(self, champion: str, target: int = 18) -> tk.PhotoImage | None:
        cache_key = ("champion", champion, target)
        if cache_key in self.icon_cache:
            return self.icon_cache[cache_key]
        filename = self.champion_files.get(str(champion or "").lower()) or f"{champion}.png"
        candidates = [
            resource_path(f"assets/ddragon/{DDRAGON_VERSION}/champion/{filename}"),
            resource_path(f"assets/champions/{filename}"),
        ]
        path = next((candidate for candidate in candidates if candidate.exists()), None)
        if not path:
            self.icon_cache[cache_key] = None
            return None
        icon = self._fit_photo(tk.PhotoImage(file=str(path)), target)
        self.icon_cache[cache_key] = icon
        return icon

    def _sprite_icon(self, category: str, entry: dict | None, target: int) -> tk.PhotoImage | None:
        image = (entry or {}).get("image", {})
        sprite = image.get("sprite")
        if not sprite:
            return None
        cache_key = (category, image.get("full"), target)
        if cache_key in self.icon_cache:
            return self.icon_cache[cache_key]
        sprite_path = resource_path(f"assets/ddragon/{DDRAGON_VERSION}/sprite/{sprite}")
        if not sprite_path.exists():
            self.icon_cache[cache_key] = None
            return None
        if sprite not in self.sprite_cache:
            self.sprite_cache[sprite] = tk.PhotoImage(file=str(sprite_path))
        source = self.sprite_cache[sprite]
        width = int(image.get("w") or 48)
        height = int(image.get("h") or 48)
        cropped = tk.PhotoImage(width=width, height=height)
        cropped.tk.call(
            str(cropped), "copy", str(source), "-from",
            int(image.get("x") or 0), int(image.get("y") or 0),
            int(image.get("x") or 0) + width, int(image.get("y") or 0) + height,
            "-to", 0, 0,
        )
        icon = self._fit_photo(cropped, target)
        self.icon_cache[cache_key] = icon
        return icon

    def _item_icon(self, item_id: int, target: int = 16) -> tk.PhotoImage | None:
        return self._sprite_icon("item", self.item_entries.get(int(item_id)), target)

    def _spell_icon(self, spell_id, target: int = 9) -> tk.PhotoImage | None:
        return self._sprite_icon("spell", self.spell_entries.get(int(number(spell_id) or 0)), target)

    def _show_tooltip(self, event, text: str) -> None:
        self._hide_tooltip()
        if not text:
            return
        tip = tk.Toplevel(self)
        tip.wm_overrideredirect(True)
        tip.wm_geometry(f"+{event.x_root + 12}+{event.y_root + 12}")
        tk.Label(
            tip, text=text, bg="#111d23", fg="#e4edf0", relief="solid", borderwidth=1,
            font=("Microsoft YaHei UI", 9), padx=7, pady=4,
        ).pack()
        self.tooltip_window = tip

    def _hide_tooltip(self, _event=None) -> None:
        if self.tooltip_window is not None:
            self.tooltip_window.destroy()
            self.tooltip_window = None

    def _bind_tooltip(self, canvas: tk.Canvas, item_or_tag, text: str) -> None:
        canvas.tag_bind(item_or_tag, "<Enter>", lambda event, value=text: self._show_tooltip(event, value))
        canvas.tag_bind(item_or_tag, "<Leave>", self._hide_tooltip)

    def _draw_objective_icon(self, canvas: tk.Canvas, x: float, y: float, kind: str, color: str, size: int = 8, tooltip: str = "") -> None:
        tag = f"objective_{id(canvas)}_{len(canvas.find_all())}_{kind}"
        if kind == "tower":
            canvas.create_polygon(x - size, y - size, x + size, y - size, x + size * 0.6, y - size * 0.4, x - size * 0.6, y - size * 0.4, fill=color, outline="#dce9ed", tags=(tag, "replay_marker"))
            canvas.create_rectangle(x - size * 0.55, y - size * 0.4, x + size * 0.55, y + size, fill="#0a1217", outline=color, width=2, tags=(tag, "replay_marker"))
        elif kind == "inhibitor":
            canvas.create_polygon(x, y - size, x + size, y, x, y + size, x - size, y, fill="#0a1217", outline=color, width=2, tags=(tag, "replay_marker"))
            canvas.create_oval(x - size * 0.35, y - size * 0.35, x + size * 0.35, y + size * 0.35, fill=color, outline="", tags=(tag, "replay_marker"))
        elif kind == "dragon":
            canvas.create_polygon(x - size, y, x - size * 0.2, y - size * 0.75, x, y - size * 0.15, x + size * 0.2, y - size * 0.75, x + size, y, x, y + size, fill=color, outline="#f5d37f", tags=(tag, "replay_marker"))
        elif kind == "soul":
            canvas.create_oval(x - size, y - size, x + size, y + size, outline=color, width=3, tags=(tag, "replay_marker"))
            canvas.create_oval(x - size * 0.35, y - size * 0.35, x + size * 0.35, y + size * 0.35, fill=color, outline="", tags=(tag, "replay_marker"))
        elif kind == "baron":
            canvas.create_oval(x - size, y - size * 0.65, x + size, y + size * 0.65, fill="#271b35", outline=color, width=2, tags=(tag, "replay_marker"))
            canvas.create_oval(x - 2, y - 2, x + 2, y + 2, fill="#f5d37f", outline="", tags=(tag, "replay_marker"))
        elif kind == "herald":
            canvas.create_polygon(x, y - size, x + size, y - size * 0.2, x + size * 0.55, y + size, x - size * 0.55, y + size, x - size, y - size * 0.2, fill="#34244b", outline=color, width=2, tags=(tag, "replay_marker"))
        else:
            for offset_x, offset_y in ((-size * 0.55, 0), (0, -size * 0.35), (size * 0.55, 0)):
                canvas.create_oval(x + offset_x - 3, y + offset_y - 3, x + offset_x + 3, y + offset_y + 3, fill=color, outline="#dce9ed", tags=(tag, "replay_marker"))
        if tooltip:
            self._bind_tooltip(canvas, tag, tooltip)

    def _draw_minion_wave(self, canvas: tk.Canvas, x: float, y: float, team_id: int, lane: str, spawn_second: int) -> None:
        color = "#45c9ff" if team_id == 100 else "#ff675d"
        tag = f"wave_{team_id}_{lane}_{spawn_second}"
        for offset_x, offset_y in ((-4, 2), (0, -3), (4, 2)):
            canvas.create_oval(x + offset_x - 2, y + offset_y - 2, x + offset_x + 2, y + offset_y + 2, fill=color, outline="#e6f2f5", tags=(tag, "replay_marker"))
        lane_name = {"TOP": "上路", "MIDDLE": "中路", "BOTTOM": "下路"}.get(lane, lane)
        self._bind_tooltip(canvas, tag, f"{lane_name}推算兵线 · {format_clock(spawn_second)} 出生\nRiot API 不提供小兵实时坐标")

    def _draw_cs_icon(self, canvas: tk.Canvas, x: float, y: float, color: str) -> None:
        tag = f"cs_{id(canvas)}_{len(canvas.find_all())}"
        canvas.create_polygon(x - 6, y + 5, x - 5, y - 3, x, y - 7, x + 5, y - 3, x + 6, y + 5, fill="#17242c", outline=color, tags=(tag,))
        canvas.create_oval(x - 2, y - 1, x + 2, y + 3, fill=color, outline="", tags=(tag,))
        self._bind_tooltip(canvas, tag, "当前总补刀（线上小兵＋野怪）")

    def _render_objective_panel(self, objectives: dict) -> None:
        canvas = self.objective_canvas
        canvas.delete("all")
        for row_index, team_id in enumerate((100, 200)):
            team = objectives["teams"][team_id]
            color = "#45c9ff" if team_id == 100 else "#ff675d"
            y = 20 + row_index * 34
            canvas.create_rectangle(2, y - 11, 9, y + 11, fill=color, outline="")
            entries = [
                ("tower", team["towers"], "已摧毁防御塔"),
                ("inhibitor", team["inhibitors"], "已摧毁召唤水晶"),
                ("dragon", len(team["dragons"]), "小龙：" + (" / ".join(team["dragons"]) or "无")),
                ("soul", 1 if team["soul"] else 0, team["soul"] or f"龙魂属性：{objectives['soulType'] or '未确定'}"),
                ("baron", team["barons"], "纳什男爵"),
                ("herald", team["heralds"], "峡谷先锋"),
                ("grubs", team["grubs"], "虚空巢虫"),
            ]
            for index, (kind, count, tooltip) in enumerate(entries):
                x = 27 + index * 70
                self._draw_objective_icon(canvas, x, y, kind, color, size=8, tooltip=tooltip)
                canvas.create_text(x + 16, y, text=str(count), fill="#dce9ed", font=("Consolas", 10, "bold"), anchor="w")

    def _render_scoreboard(self, team_rows: dict[int, list[dict]]) -> None:
        for team_id, canvas in self.scoreboard_canvases.items():
            canvas.delete("all")
            color = "#45c9ff" if team_id == 100 else "#ff675d"
            for row_index, row in enumerate(team_rows.get(team_id, [])):
                y = 11 + row_index * 19
                is_dead = bool(row.get("dead"))
                canvas.create_rectangle(0, y - 9, max(520, canvas.winfo_width()), y + 9, fill="#0c161c" if row_index % 2 == 0 else "#091116", outline="")
                champion_icon = self._champion_icon(row["champion"], 18)
                if champion_icon:
                    champion_tag = f"score_champion_{team_id}_{row_index}"
                    canvas.create_image(13, y, image=champion_icon, tags=(champion_tag,))
                    if is_dead:
                        canvas.create_rectangle(4, y - 9, 22, y + 9, fill="#071015", stipple="gray50", outline="#9aa4a9", tags=(champion_tag,))
                        canvas.create_line(6, y - 7, 20, y + 7, fill="#e2e7e9", width=2, tags=(champion_tag,))
                        canvas.create_line(20, y - 7, 6, y + 7, fill="#e2e7e9", width=2, tags=(champion_tag,))
                    tooltip = f"{row['champion']} · {POSITION_NAMES.get(row['position'], row['position'])}"
                    if is_dead:
                        tooltip += f"\n已阵亡 · 预计 {row.get('respawnRemaining', 0)} 秒后复活"
                    self._bind_tooltip(canvas, champion_tag, tooltip)
                for spell_index, spell_id in enumerate((row.get("summoner1Id"), row.get("summoner2Id"))):
                    spell_icon = self._spell_icon(spell_id, 9)
                    if spell_icon:
                        spell_entry = self.spell_entries.get(int(number(spell_id) or 0), {})
                        image_id = canvas.create_image(29, y - 5 + spell_index * 10, image=spell_icon)
                        self._bind_tooltip(canvas, image_id, spell_entry.get("name") or str(spell_id))
                canvas.create_oval(40, y - 7, 54, y + 7, fill="#17242c", outline=color)
                canvas.create_text(47, y, text=str(row["level"]), fill="#e6f2f5", font=("Consolas", 8, "bold"))
                canvas.create_text(67, y, text=row["kda"], fill="#88969c" if is_dead else "#dce9ed", font=("Consolas", 9, "bold"), anchor="w")
                if is_dead:
                    canvas.create_text(119, y, text=f"☠~{row.get('respawnRemaining', 0)}s", fill="#d7a7a0", font=("Consolas", 8, "bold"), anchor="w")
                self._draw_cs_icon(canvas, 145, y, color)
                canvas.create_text(157, y, text=str(row["cs"]), fill="#dce9ed", font=("Consolas", 9, "bold"), anchor="w")
                canvas.create_oval(196, y - 5, 206, y + 5, fill="#d7a93c", outline="#f5d37f")
                canvas.create_text(212, y, text=f"{row['gold']:,}", fill="#f5d37f", font=("Consolas", 9, "bold"), anchor="w")
                item_x = 270
                for slot in range(7):
                    canvas.create_rectangle(item_x + slot * 20 - 8, y - 8, item_x + slot * 20 + 8, y + 8, fill="#101a20", outline="#263941")
                for item_index, item_id in enumerate(row["items"][:7]):
                    item_icon = self._item_icon(item_id, 16)
                    if item_icon:
                        image_id = canvas.create_image(item_x + item_index * 20, y, image=item_icon)
                        self._bind_tooltip(canvas, image_id, self.item_names.get(item_id, str(item_id)))

    def _render_recent_events(self, events: list[dict], public_players: dict[int, dict]) -> None:
        canvas = self.event_canvas
        canvas.delete("all")
        if not events:
            canvas.create_line(15, 46, 95, 46, fill="#263941", width=2)
            canvas.create_oval(102, 41, 112, 51, outline="#526973", width=2)
            return

        def champion_icon(participant_id, x, y):
            player = public_players.get(int(number(participant_id) or 0), {})
            icon = self._champion_icon(player.get("champion"), 16)
            if icon:
                image_id = canvas.create_image(x, y, image=icon)
                self._bind_tooltip(canvas, image_id, player.get("champion") or "未知英雄")
            else:
                canvas.create_oval(x - 5, y - 5, x + 5, y + 5, fill="#526973", outline="#dce9ed")

        for row_index, event in enumerate(events[-4:]):
            y = 13 + row_index * 21
            canvas.create_text(7, y, text=format_clock(int(number(event.get("timestamp")) or 0) / 1000), fill="#78909a", font=("Consolas", 8), anchor="w")
            event_type = event.get("type")
            if event_type == "CHAMPION_KILL":
                champion_icon(event.get("killerId"), 60, y)
                canvas.create_line(72, y, 88, y, fill="#e98273", width=2, arrow="last")
                champion_icon(event.get("victimId"), 101, y)
                for assist_index, participant_id in enumerate(event.get("assistingParticipantIds", [])[:4]):
                    champion_icon(participant_id, 127 + assist_index * 18, y)
            elif event_type == "ELITE_MONSTER_KILL":
                champion_icon(event.get("killerId"), 60, y)
                canvas.create_line(72, y, 88, y, fill="#e9bd59", width=2, arrow="last")
                monster = event.get("monsterSubType") or event.get("monsterType")
                kind = "dragon" if event.get("monsterType") == "DRAGON" else "baron" if monster == "BARON_NASHOR" else "herald" if monster == "RIFTHERALD" else "grubs"
                self._draw_objective_icon(canvas, 102, y, kind, "#e9bd59", size=7, tooltip=DRAGON_NAMES.get(monster, monster or "史诗野怪"))
            elif event_type == "BUILDING_KILL":
                champion_icon(event.get("killerId"), 60, y)
                canvas.create_line(72, y, 88, y, fill="#e9bd59", width=2, arrow="last")
                kind = "inhibitor" if event.get("buildingType") == "INHIBITOR_BUILDING" else "tower"
                self._draw_objective_icon(canvas, 102, y, kind, "#e9bd59", size=7, tooltip="召唤水晶" if kind == "inhibitor" else "防御塔")
            elif event_type == "DRAGON_SOUL_GIVEN":
                team_id = int(number(event.get("teamId")) or 0)
                color = "#45c9ff" if team_id == 100 else "#ff675d"
                canvas.create_rectangle(52, y - 7, 67, y + 7, fill=color, outline="#dce9ed")
                canvas.create_line(72, y, 88, y, fill="#e9bd59", width=2, arrow="last")
                self._draw_objective_icon(canvas, 102, y, "soul", color, size=7, tooltip=DRAGON_NAMES.get(event.get("name"), event.get("name") or "龙魂"))
            elif event_type == "DERIVED_TEAMFIGHT":
                canvas.create_oval(52, y - 8, 68, y + 8, fill="#2b1b38", outline="#c292ff", width=2)
                canvas.create_text(60, y, text="战", fill="#eadcff", font=("Microsoft YaHei UI", 8, "bold"))
                blue_kills = int(number(event.get("killsByTeam", {}).get(100)) or 0)
                red_kills = int(number(event.get("killsByTeam", {}).get(200)) or 0)
                canvas.create_text(84, y, text=f"{blue_kills}:{red_kills}", fill="#c292ff", font=("Consolas", 8, "bold"), anchor="w")

    def _change_map_layer(self) -> None:
        if self.replay_data and self.replay_data.get("frames"):
            if self.map_layer_mode.get() == "CAUSES":
                objective_event = nearest_objective_loss(
                    self.replay_data, self._selected_match() or {}, self.replay_second.get(),
                )
                if objective_event:
                    self._stop_replay()
                    self._render_replay(int(number(objective_event.get("timestamp")) or 0) // 1000)
                    return
            self._render_replay(self.replay_second.get())

    def _focus_movement_points(self, focus_id: int | None, current_second: int) -> list[tuple[float, float]]:
        if not self.replay_data or not focus_id:
            return []
        frames = self.replay_data.get("frames", [])
        current_index = min(max(0, int(current_second)) // 60, len(frames) - 1)
        points = []
        for frame in frames[max(0, current_index - 3):current_index + 1]:
            player_frame = next((
                player for player in frame.get("players", [])
                if int(number(player.get("participantId")) or 0) == focus_id
            ), None)
            if not player_frame:
                continue
            location = map_coordinates(player_frame.get("x"), player_frame.get("y"), self.map_width, self.map_height)
            if location and (not points or math.dist(points[-1], location) > 2):
                points.append(location)
        return points

    def _draw_map_layer_context(self, situation: dict, current_second: int) -> None:
        mode = self.map_layer_mode.get()
        canvas = self.map_canvas
        if mode == "SITUATION":
            position = situation.get("nextEpicPosition")
            seconds_until = situation.get("secondsUntilEpic")
            if position and seconds_until is not None:
                location = map_coordinates(position.get("x"), position.get("y"), self.map_width, self.map_height)
                if location:
                    x, y = location
                    radius = 39
                    canvas.create_oval(
                        x - radius, y - radius, x + radius, y + radius,
                        fill="#2a2416", outline="#e9bd59", width=2, dash=(5, 4), tags=("replay_marker",),
                    )
                    progress = 1.0 - min(90, max(0, seconds_until)) / 90
                    canvas.create_arc(
                        x - radius - 4, y - radius - 4, x + radius + 4, y + radius + 4,
                        start=90, extent=-359 * progress, style="arc", outline="#6de1dc", width=3,
                        tags=("replay_marker",),
                    )
                    canvas.create_text(
                        x, y + radius + 11, text=f"复盘事件 −{format_clock(seconds_until)}",
                        fill="#f4ca68", font=("Microsoft YaHei UI", 8, "bold"), tags=("replay_marker",),
                    )
            points = self._focus_movement_points(situation.get("focusId"), current_second)
            if len(points) >= 2:
                flattened = [coordinate for point in points for coordinate in point]
                canvas.create_line(
                    *flattened, fill="#68ddd5", width=3, dash=(7, 4), arrow="last",
                    smooth=True, tags=("replay_marker",),
                )
                for x, y in points[:-1]:
                    canvas.create_oval(x - 3, y - 3, x + 3, y + 3, fill="#68ddd5", outline="", tags=("replay_marker",))
        elif mode == "EVENTS":
            visible_events = [
                event for event in situation.get("recentEvents", [])
                if event.get("type") in {"CHAMPION_KILL", "DERIVED_TEAMFIGHT", "ELITE_MONSTER_KILL", "BUILDING_KILL", "WARD_PLACED", "WARD_KILL"}
            ][-6:]
            for index, event in enumerate(visible_events, 1):
                position = event.get("position") or objective_event_position(event)
                if not position:
                    continue
                location = map_coordinates(position.get("x"), position.get("y"), self.map_width, self.map_height)
                if not location:
                    continue
                x, y = location
                event_type = event.get("type")
                color = "#c292ff" if event_type == "DERIVED_TEAMFIGHT" else "#e98273" if event_type == "CHAMPION_KILL" else "#e9bd59" if event_type in {"ELITE_MONSTER_KILL", "BUILDING_KILL"} else "#68ddd5"
                radius = 16 if event_type == "DERIVED_TEAMFIGHT" else 12
                canvas.create_oval(x - radius, y - radius, x + radius, y + radius, fill="#081015", outline=color, width=3 if event_type == "DERIVED_TEAMFIGHT" else 2, tags=("replay_marker",))
                canvas.create_text(x, y, text="战" if event_type == "DERIVED_TEAMFIGHT" else str(index), fill=color, font=("Microsoft YaHei UI", 8, "bold"), tags=("replay_marker",))
        elif mode == "COMPARE":
            frame_players = {
                int(number(player.get("participantId")) or 0): player
                for player in situation.get("frame", {}).get("players", [])
            }
            focus_frame = frame_players.get(situation.get("focusId") or 0, {})
            opponent_frame = frame_players.get(situation.get("opponentId") or 0, {})
            focus_location = map_coordinates(focus_frame.get("x"), focus_frame.get("y"), self.map_width, self.map_height)
            opponent_location = map_coordinates(opponent_frame.get("x"), opponent_frame.get("y"), self.map_width, self.map_height)
            if focus_location and opponent_location:
                canvas.create_line(
                    focus_location[0], focus_location[1], opponent_location[0], opponent_location[1],
                    fill="#c292ff", width=2, dash=(6, 5), tags=("replay_marker",),
                )
                midpoint = ((focus_location[0] + opponent_location[0]) / 2, (focus_location[1] + opponent_location[1]) / 2)
                gold_diff = situation.get("currentDiffs", {}).get("gold", 0)
                canvas.create_text(
                    midpoint[0], midpoint[1] - 10, text=f"对位经济 {gold_diff:+,}",
                    fill="#e9d8ff", font=("Microsoft YaHei UI", 8, "bold"), tags=("replay_marker",),
                )
        elif mode == "CAUSES":
            analysis = situation.get("objectiveLossAnalysis") or {}
            position = analysis.get("position")
            location = map_coordinates(
                (position or {}).get("x"), (position or {}).get("y"), self.map_width, self.map_height,
            )
            frame_players = {
                int(number(player.get("participantId")) or 0): player
                for player in analysis.get("frame", {}).get("players", [])
            }
            focus_frame = frame_players.get(analysis.get("focusId") or 0, {})
            focus_location = map_coordinates(
                focus_frame.get("x"), focus_frame.get("y"), self.map_width, self.map_height,
            )
            if location:
                x, y = location
                canvas.create_oval(
                    x - 44, y - 44, x + 44, y + 44, fill="#2b1518", outline="#ff7169",
                    width=3, dash=(6, 4), tags=("replay_marker",),
                )
                canvas.create_text(
                    x, y + 57, text=f"结果 · 丢失{analysis.get('objectiveName', '目标')}",
                    fill="#ff9189", font=("Microsoft YaHei UI", 8, "bold"), tags=("replay_marker",),
                )
            if location and focus_location:
                canvas.create_line(
                    focus_location[0], focus_location[1], location[0], location[1],
                    fill="#c292ff", width=2, dash=(7, 5), arrow="last", tags=("replay_marker",),
                )
                midpoint = ((focus_location[0] + location[0]) / 2, (focus_location[1] + location[1]) / 2)
                canvas.create_text(
                    midpoint[0], midpoint[1] - 9, text="候选关联（非确定因果）",
                    fill="#e1c9ff", font=("Microsoft YaHei UI", 8, "bold"), tags=("replay_marker",),
                )

    def _insight_row(self, y: int, label: str, value: str, color: str = "#dce9ed", note: str | None = None) -> int:
        canvas = self.replay_insight_canvas
        width = max(410, canvas.winfo_width())
        canvas.create_line(10, y + 20, width - 10, y + 20, fill="#172830")
        canvas.create_text(12, y + 8, text=label, fill="#8198a1", font=("Microsoft YaHei UI", 9), anchor="w")
        canvas.create_text(width - 12, y + 8, text=value, fill=color, font=("Microsoft YaHei UI", 9, "bold"), anchor="e")
        if note:
            canvas.create_text(12, y + 25, text=note, fill="#627983", font=("Microsoft YaHei UI", 8), anchor="w")
            return y + 41
        return y + 27

    def _event_display_text(self, event: dict, public_players: dict[int, dict]) -> str:
        lines = replay_event_lines({"events": [event]}, list(public_players.values()))
        if lines:
            return lines[0]
        participant_id = int(number(event.get("participantId")) or 0)
        champion = public_players.get(participant_id, {}).get("champion") or "玩家"
        if event.get("type") == "ITEM_PURCHASED":
            item_id = int(number(event.get("itemId")) or 0)
            return f"购买：{champion} · {self.item_names.get(item_id, item_id)}"
        if event.get("type") == "ITEM_SOLD":
            item_id = int(number(event.get("itemId")) or 0)
            return f"出售：{champion} · {self.item_names.get(item_id, item_id)}"
        return event.get("type") or "未知事件"

    def _render_replay_insights(self, situation: dict, objectives: dict, public_players: dict[int, dict]) -> None:
        canvas = self.replay_insight_canvas
        canvas.delete("all")
        mode = self.map_layer_mode.get()
        match = self._selected_match() or {}
        if mode == "SITUATION":
            self.replay_layer_caption.set("局面 · 当前目标窗口、区域人数与移动趋势")
            canvas.create_text(12, 13, text="当前局面", fill="#e9bd59", font=("Microsoft YaHei UI", 10, "bold"), anchor="w")
            y = 29
            if situation.get("nextEpic"):
                y = self._insight_row(
                    y, "下一史诗事件（复盘）",
                    f"{situation['nextEpicName']} · {format_clock(situation['secondsUntilEpic'])}", "#e98273",
                )
                focus_team = situation.get("focusTeam")
                enemy_team = 300 - focus_team if focus_team in {100, 200} else 0
                y = self._insight_row(
                    y, "目标区域人数（位置估计）",
                    f"己方 {situation['nearby'].get(focus_team, 0)} · 对方 {situation['nearby'].get(enemy_team, 0)}", "#f4ca68",
                )
            else:
                y = self._insight_row(y, "目标窗口", "未来 90 秒无史诗事件", "#68ddd5")
            points = self._focus_movement_points(situation.get("focusId"), self.replay_second.get())
            movement = math.dist(points[-2], points[-1]) if len(points) >= 2 else 0
            y = self._insight_row(y, "你的移动趋势", "明显位移" if movement >= 18 else "位置变化较小", "#68ddd5")
            y = self._insight_row(y, "最近 90 秒视野动作", f"{situation['wardsPlaced']} 插眼 · {situation['wardsKilled']} 排眼", "#68ddd5")
            own_team = objectives["teams"].get(situation.get("focusTeam"), {})
            enemy_team = objectives["teams"].get(300 - situation.get("focusTeam", 0), {})
            self._insight_row(
                y, "地图资源", f"己方 {own_team.get('towers', 0)}塔/{len(own_team.get('dragons', []))}龙 · 对方 {enemy_team.get('towers', 0)}塔/{len(enemy_team.get('dragons', []))}龙", "#dce9ed",
            )
        elif mode == "EVENTS":
            self.replay_layer_caption.set("事件 · Riot 原始事件 + 紫色规则识别团战")
            canvas.create_text(12, 13, text="最近事件", fill="#e9bd59", font=("Microsoft YaHei UI", 10, "bold"), anchor="w")
            event_candidates = [
                event for event in situation.get("recentEvents", [])
                if event.get("type") in {
                    "CHAMPION_KILL", "DERIVED_TEAMFIGHT", "ELITE_MONSTER_KILL", "BUILDING_KILL", "DRAGON_SOUL_GIVEN",
                    "WARD_PLACED", "WARD_KILL", "ITEM_PURCHASED", "ITEM_SOLD",
                }
            ]
            visible = event_candidates[-6:]
            latest_teamfight = next((event for event in reversed(event_candidates) if event.get("type") == "DERIVED_TEAMFIGHT"), None)
            if latest_teamfight and latest_teamfight not in visible:
                visible = sorted(
                    [latest_teamfight, *visible[-5:]],
                    key=lambda event: int(number(event.get("timestamp")) or 0),
                )
            if not visible:
                canvas.create_text(12, 49, text="当前窗口没有关键事件", fill="#78909a", font=("Microsoft YaHei UI", 9), anchor="w")
            for index, event in enumerate(visible):
                y = 38 + index * 25
                timestamp = format_clock(int(number(event.get("timestamp")) or 0) / 1000)
                canvas.create_text(12, y, text=timestamp, fill="#708892", font=("Consolas", 8), anchor="w")
                canvas.create_text(58, y, text=self._event_display_text(event, public_players), fill="#dce9ed", font=("Microsoft YaHei UI", 8), anchor="w")
        elif mode == "COMPARE":
            phase = situation.get("phase", "EARLY")
            self.replay_layer_caption.set(f"对比 · 当前对位快照 + {PHASE_NAMES.get(phase, phase)}整段基准")
            canvas.create_text(12, 13, text="当前对位", fill="#e9bd59", font=("Microsoft YaHei UI", 10, "bold"), anchor="w")
            y = 29
            for label, key, unit in (("经济差", "gold", ""), ("CS 差", "cs", ""), ("等级差", "level", "级")):
                value = situation.get("currentDiffs", {}).get(key, 0)
                color = "#68ddd5" if value > 0 else "#e98273" if value < 0 else "#dce9ed"
                y = self._insight_row(y, label, f"{value:+,}{unit}", color)
            canvas.create_text(12, y + 5, text="阶段结果与英雄基准", fill="#e9bd59", font=("Microsoft YaHei UI", 9, "bold"), anchor="w")
            y += 23
            rows = comparison_rows(match, phase, self.baselines)
            for row in rows[:3]:
                player_value, baseline, gap = row[1], row[3], row[6]
                color = "#68ddd5" if gap.startswith("+") else "#e98273" if gap.startswith("-") else "#dce9ed"
                y = self._insight_row(y, row[0], f"{player_value} · 基准 {baseline} · {gap}", color)
        else:
            analysis = situation.get("objectiveLossAnalysis") or {}
            self.replay_layer_caption.set("原因 · 最近一次丢龙/先锋的证据图")
            if not analysis:
                canvas.create_text(12, 13, text="本局没有检测到己方丢失的龙或先锋", fill="#78909a", font=("Microsoft YaHei UI", 9), anchor="w")
                return
            event_second = int(number(analysis.get("eventSecond")) or 0)
            canvas.create_text(
                12, 13, text=f"{format_clock(event_second)} · 丢失{analysis.get('objectiveName', '目标')}",
                fill="#ff8b82", font=("Microsoft YaHei UI", 10, "bold"), anchor="w",
            )
            hypotheses = analysis.get("hypotheses", [])
            primary_id = analysis.get("primaryHypothesisId")
            primary = next((item for item in hypotheses if item.get("id") == primary_id), None)
            if primary:
                confidence = float(number(primary.get("confidence")) or 0)
                canvas.create_text(12, 39, text="主要候选原因", fill="#8198a1", font=("Microsoft YaHei UI", 8), anchor="w")
                canvas.create_text(
                    12, 59, text=primary.get("title", "—"), fill="#f4ca68",
                    font=("Microsoft YaHei UI", 10, "bold"), anchor="w",
                )
                canvas.create_text(
                    max(410, canvas.winfo_width()) - 12, 59,
                    text=f"{primary.get('grade', '—')}置信 · {confidence:.0%}", fill="#c292ff",
                    font=("Microsoft YaHei UI", 9, "bold"), anchor="e",
                )
                fact_by_id = {fact.get("id"): fact for fact in analysis.get("facts", [])}
                evidence = [fact_by_id.get(fact_id) for fact_id in primary.get("evidenceIds", [])]
                evidence = [fact for fact in evidence if fact]
                canvas.create_text(12, 86, text="支持证据", fill="#8198a1", font=("Microsoft YaHei UI", 8), anchor="w")
                y = 105
                for fact in evidence[:3]:
                    source = fact.get("source", "数据")
                    canvas.create_text(
                        18, y, text=f"• {fact.get('label')}  [{source}]", fill="#dce9ed",
                        font=("Microsoft YaHei UI", 8), anchor="w",
                    )
                    y += 21
                canvas.create_text(
                    12, y + 3, text=primary.get("explanation", ""), width=max(380, canvas.winfo_width() - 24),
                    fill="#91a6ad", font=("Microsoft YaHei UI", 8), anchor="nw", justify="left",
                )
            else:
                limitation = next((item for item in hypotheses if item.get("kind") == "LIMITATION"), None)
                canvas.create_text(
                    12, 49, text=(limitation or {}).get("title", "现有数据不足以判断主要原因"),
                    fill="#f4ca68", font=("Microsoft YaHei UI", 10, "bold"), anchor="w",
                )
                canvas.create_text(
                    12, 78, text=(limitation or {}).get("explanation", "不会强行生成因果结论。"),
                    width=max(380, canvas.winfo_width() - 24), fill="#91a6ad",
                    font=("Microsoft YaHei UI", 8), anchor="nw", justify="left",
                )
            alternative = next((item for item in hypotheses if item.get("kind") == "ALTERNATIVE"), None)
            if alternative:
                canvas.create_text(
                    12, 201, text=f"另一种解释：{alternative.get('title')}（{alternative.get('confidence', 0):.0%}）",
                    fill="#68ddd5", font=("Microsoft YaHei UI", 8, "bold"), anchor="w",
                )

    def _populate_matches(self) -> None:
        for item in self.match_tree.get_children():
            self.match_tree.delete(item)
        for index, match in enumerate(self.case.get("matches", [])):
            result = "胜" if match.get("win") else "负"
            matchup = f"{match.get('champion', '—')} vs {match.get('opponentChampion') or '未知'}"
            duration = f"{number(match.get('durationMin')) or 0:.1f}m"
            self.match_tree.insert("", "end", iid=str(index), values=(result, matchup, duration), tags=("win" if match.get("win") else "loss",))
        self.match_tree.tag_configure("win", foreground="#68ddd5")
        self.match_tree.tag_configure("loss", foreground="#e98273")
        if self.match_tree.get_children():
            self.match_tree.selection_set(self.match_tree.get_children()[0])
            self.match_tree.focus(self.match_tree.get_children()[0])
            self._on_match_selected()
        self._render_form_strip()

    def _selected_match(self) -> dict | None:
        selected = self.match_tree.selection()
        if not selected:
            return None
        try:
            return self.case.get("matches", [])[int(selected[0])]
        except (IndexError, ValueError):
            return None

    def _on_match_selected(self, _event=None) -> None:
        self._stop_replay()
        self.selection_flash = 1.0
        self._render_comparison()
        self._load_selected_replay()
        self._render_form_strip()

    def _load_selected_replay(self) -> None:
        self.replay_data = None
        match = self._selected_match()
        if not match:
            self._render_replay_unavailable("请选择一场比赛")
            return
        replay_ref = match.get("replayRef")
        if replay_ref:
            replay_file = self.data_dir / "replays" / f"{Path(str(replay_ref)).name}.json"
            if replay_file.exists():
                try:
                    self.replay_data = json.loads(replay_file.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    self.replay_data = None
        if self.replay_data is None:
            self.replay_data = self.bootstrap_replays.get(match.get("matchRef"))
        if not self.replay_data or not self.replay_data.get("frames"):
            self.replay_scale.configure(to=1, state="disabled")
            self.replay_second.set(0)
            self._render_replay_unavailable("这场比赛还没有分钟复盘数据；使用 API 刷新后会自动生成")
            return
        final_second = self._replay_final_second()
        self.replay_scale.configure(to=final_second, state="normal")
        for variable, value in zip(self.timeline_tick_texts, (0, final_second * 0.25, final_second * 0.5, final_second * 0.75, final_second)):
            variable.set(format_clock(value))
        self.replay_second.set(0)
        self._render_replay(0)

    def _replay_final_second(self) -> int:
        if not self.replay_data:
            return 0
        duration = int(number(self.replay_data.get("durationSeconds")) or 0)
        if duration:
            return duration
        return max(0, len(self.replay_data.get("frames", [])) - 1) * 60

    def _render_replay_unavailable(self, message: str) -> None:
        self.map_canvas.delete("replay_marker")
        self.map_canvas.create_text(
            self.map_width / 2, self.map_height / 2, text=message, width=self.map_width * 0.7,
            fill="#e9bd59", font=("Microsoft YaHei UI", 12, "bold"), justify="center",
            tags=("replay_marker",),
        )
        self.replay_time_text.set(message)
        self.timeline_value_text.set("00:00 / --:--")
        for variable in self.timeline_tick_texts:
            variable.set("--:--")
        for canvas in self.scoreboard_canvases.values():
            canvas.delete("all")
        self.replay_insight_canvas.delete("all")
        self.replay_insight_canvas.create_text(
            12, 18, text="等待复盘数据", fill="#78909a", font=("Microsoft YaHei UI", 9), anchor="w",
        )
        self.replay_layer_caption.set("地图信息层")
        self.replay_button.configure(text="播放")

    def _render_replay(self, second: int) -> None:
        if not self.replay_data or not self.replay_data.get("frames"):
            return
        frames = self.replay_data["frames"]
        final_second = self._replay_final_second()
        current_second = min(max(0, int(second)), final_second)
        match = self._selected_match() or {}
        loss_analysis = None
        if self.map_layer_mode.get() == "CAUSES":
            objective_event = nearest_objective_loss(self.replay_data, match, current_second)
            if objective_event:
                current_second = min(
                    final_second, int(number(objective_event.get("timestamp")) or 0) // 1000,
                )
                loss_analysis = objective_loss_analysis(self.replay_data, match, objective_event)
        frame_index = min(current_second // 60, len(frames) - 1)
        frame = loss_analysis.get("frame") if loss_analysis else frames[frame_index]
        sample_second = int(number(frame.get("timestamp")) or frame_index * 60_000) // 1000
        self.replay_second.set(current_second)
        self.replay_time_text.set(f"当前 {format_clock(current_second)} · 人物坐标采样 {format_clock(sample_second)}")
        self.timeline_value_text.set(f"{format_clock(current_second)} / {format_clock(final_second)}")
        self.map_canvas.delete("replay_marker")
        public_players = {player.get("participantId"): player for player in self.replay_data.get("players", [])}
        objectives = objective_snapshot(self.replay_data, current_second)
        tab_state = tab_snapshot(self.replay_data, current_second)
        death_states = death_states_at(self.replay_data, current_second)
        situation = replay_situation_snapshot(self.replay_data, match, current_second)
        situation["objectiveLossAnalysis"] = loss_analysis
        self._draw_map_layer_context(situation, current_second)

        for marker in objectives["markers"]:
            marker_position = marker.get("position") or objective_event_position(marker)
            location = map_coordinates(
                (marker_position or {}).get("x"), (marker_position or {}).get("y"),
                self.map_width, self.map_height,
            )
            if not location:
                continue
            x, y = location
            team_id = marker.get("scoringTeam")
            color = "#45c9ff" if team_id == 100 else "#ff675d"
            kind = marker.get("kind")
            if kind in {"tower", "inhibitor"}:
                target_name = "召唤水晶" if kind == "inhibitor" else "防御塔"
                self._draw_objective_icon(self.map_canvas, x, y, kind, color, size=7, tooltip=f"{format_clock(int(marker.get('timestamp', 0)) / 1000)} 摧毁{target_name}")
            elif kind == "soul" or current_second * 1000 - int(number(marker.get("timestamp")) or 0) <= 90_000:
                monster = marker.get("monsterSubType") or marker.get("monsterType") or "魂"
                icon_kind = "soul" if kind == "soul" else "dragon" if marker.get("monsterType") == "DRAGON" else "baron" if monster == "BARON_NASHOR" else "herald" if monster == "RIFTHERALD" else "grubs"
                objective_name = DRAGON_NAMES.get(monster, monster)
                self._draw_objective_icon(self.map_canvas, x, y, icon_kind, color, size=8, tooltip=f"{format_clock(int(marker.get('timestamp', 0)) / 1000)} · {objective_name}")

        team_rows = {100: [], 200: []}
        layer_mode = self.map_layer_mode.get()
        for player_frame in sorted(frame.get("players", []), key=lambda item: int(item.get("participantId") or 0)):
            participant_id = int(number(player_frame.get("participantId")) or 0)
            player = public_players.get(participant_id, {})
            team_id = int(player.get("teamId") or 0)
            color = "#45c9ff" if team_id == 100 else "#ff675d"
            outline = "#d7f6ff" if team_id == 100 else "#ffe0dc"
            is_focus = participant_id == situation.get("focusId")
            is_opponent = participant_id == situation.get("opponentId")
            icon_size = 26 if is_focus or (layer_mode == "COMPARE" and is_opponent) else 18 if layer_mode == "COMPARE" else 24
            if is_focus:
                outline = "#f4ca68"
            elif layer_mode == "COMPARE" and is_opponent:
                outline = "#c292ff"
            death_state = death_states.get(participant_id)
            map_position = death_state.get("position", {}) if death_state else player_frame
            location = map_coordinates(map_position.get("x"), map_position.get("y"), self.map_width, self.map_height)
            if location:
                x, y = location
                champion_icon = self._champion_icon(player.get("champion"), icon_size)
                if champion_icon:
                    champion_tag = f"map_champion_{participant_id}"
                    self.map_canvas.create_image(x, y, image=champion_icon, tags=("replay_marker", champion_tag))
                    radius = icon_size / 2
                    if death_state:
                        self.map_canvas.create_oval(
                            x - radius, y - radius, x + radius, y + radius,
                            fill="#071015", stipple="gray50", outline="#a7b0b4", width=2,
                            tags=("replay_marker", champion_tag),
                        )
                        self.map_canvas.create_line(
                            x - radius * 0.65, y - radius * 0.65, x + radius * 0.65, y + radius * 0.65,
                            fill="#eef1f2", width=3, tags=("replay_marker", champion_tag),
                        )
                        self.map_canvas.create_line(
                            x + radius * 0.65, y - radius * 0.65, x - radius * 0.65, y + radius * 0.65,
                            fill="#eef1f2", width=3, tags=("replay_marker", champion_tag),
                        )
                        self.map_canvas.create_text(
                            x, y + radius + 9, text=f"☠ 预计 {death_state['remainingSeconds']}s",
                            fill="#e0b4ae", font=("Microsoft YaHei UI", 8, "bold"),
                            tags=("replay_marker", champion_tag),
                        )
                    else:
                        self.map_canvas.create_oval(x - radius, y - radius, x + radius, y + radius, outline=outline, width=3 if is_focus or is_opponent else 2, tags=("replay_marker", champion_tag))
                    if is_focus:
                        self.map_canvas.create_oval(x - radius - 4, y - radius - 4, x + radius + 4, y + radius + 4, outline="#f4ca68", width=1, dash=(3, 3), tags=("replay_marker",))
                    tooltip = f"{player.get('champion')} · {POSITION_NAMES.get(player.get('position'), player.get('position'))}"
                    if death_state:
                        tooltip += (
                            f"\n已阵亡 · 预计 {death_state['remainingSeconds']} 秒后复活"
                            "\n死亡时间/地点：Riot 事件 · 复活时间：估计"
                        )
                    self._bind_tooltip(self.map_canvas, champion_tag, tooltip)
                else:
                    self.map_canvas.create_oval(x - 5, y - 5, x + 5, y + 5, fill="#303b40" if death_state else color, outline="#a7b0b4" if death_state else outline, width=2, tags=("replay_marker",))
            lane_cs = int(number(player_frame.get("minions")) or 0)
            jungle_cs = int(number(player_frame.get("jungleMinions")) or 0)
            player_tab = tab_state.get(participant_id, {"kills": 0, "deaths": 0, "assists": 0, "items": []})
            if team_id not in team_rows:
                continue
            team_rows[team_id].append({
                "champion": player.get("champion") or "未知", "position": player.get("position") or "UNKNOWN",
                "summoner1Id": player.get("summoner1Id"), "summoner2Id": player.get("summoner2Id"),
                "level": int(number(player_frame.get("level")) or 0),
                "kda": f"{player_tab['kills']}/{player_tab['deaths']}/{player_tab['assists']}",
                "cs": lane_cs + jungle_cs, "gold": int(number(player_frame.get("totalGold")) or 0),
                "items": player_tab["items"],
                "dead": bool(death_state),
                "respawnRemaining": death_state.get("remainingSeconds", 0) if death_state else 0,
            })

        self._render_scoreboard(team_rows)
        self._render_replay_insights(situation, objectives, public_players)

    def _seek_replay(self, value) -> None:
        if self.replay_data:
            self._render_replay(round(float(value)))

    def _timeline_pointer(self, event):
        if not self.replay_data:
            return "break"
        self._stop_replay()
        target_second = timeline_second_at_x(
            event.x, event.widget.winfo_width(), self._replay_final_second(),
        )
        self._render_replay(target_second)
        return "break"

    def _jump_replay(self, delta: int) -> None:
        if not self.replay_data:
            return
        self._stop_replay()
        self._render_replay(self.replay_second.get() + int(delta))

    def _jump_replay_edge(self, to_end: bool) -> None:
        if not self.replay_data:
            return
        self._stop_replay()
        final_second = self._replay_final_second()
        self._render_replay(final_second if to_end else 0)

    def _toggle_replay(self) -> None:
        if not self.replay_data:
            return
        if self.replay_playing:
            self._stop_replay()
            return
        final_second = self._replay_final_second()
        if self.replay_second.get() >= final_second:
            self._render_replay(0)
        self.replay_playing = True
        self.replay_button.configure(text="暂停")
        self.replay_job = self.after(250, self._advance_replay)

    def _advance_replay(self) -> None:
        self.replay_job = None
        if not self.replay_playing or not self.replay_data:
            return
        next_second = self.replay_second.get() + 5
        final_second = self._replay_final_second()
        if next_second > final_second:
            self._render_replay(final_second)
            self._stop_replay()
            return
        self._render_replay(next_second)
        self.replay_job = self.after(250, self._advance_replay)

    def _stop_replay(self) -> None:
        self.replay_playing = False
        if self.replay_job is not None:
            self.after_cancel(self.replay_job)
            self.replay_job = None
        if hasattr(self, "replay_button"):
            self.replay_button.configure(text="播放")

    def _render_comparison(self) -> None:
        for item in self.comparison_tree.get_children():
            self.comparison_tree.delete(item)
        match = self._selected_match()
        if not match:
            return
        phase = self.selected_phase.get()
        start_ms = int(match.get("gameStartMs") or 0)
        played = datetime.fromtimestamp(start_ms / 1000).strftime("%Y-%m-%d %H:%M") if start_ms else "未知时间"
        self.match_title.configure(text=f"{played} · {match.get('champion')} vs {match.get('opponentChampion') or '未知'} · {'胜' if match.get('win') else '负'} · {match.get('durationMin')} 分钟")
        if phase == "LATE" and (number(match.get("durationMin")) or 0) < 25:
            self.comparison_tree.insert("", "end", values=("该局未达到 25 分钟", "—", "—", "—", "—", "—", "—", "—", "—", "—"), tags=("phase_note",))
            return
        for index, row in enumerate(comparison_rows(match, phase, self.baselines)):
            self.comparison_tree.insert("", "end", values=row, tags=("stripe",) if index % 2 else ())

    def _saved_key(self) -> str:
        return self.key_path.read_text(encoding="ascii").strip() if self.key_path.exists() else ""

    def _save_key(self) -> bool:
        candidate = self.api_key.get().strip()
        if not candidate:
            if self._saved_key():
                self.status_text.set("本机已经保存了一个 API Key")
                return True
            messagebox.showwarning(APP_TITLE, "请输入以 RGAPI- 开头的 Riot Development API Key。")
            return False
        if not candidate.startswith("RGAPI-") or len(candidate) < 20:
            messagebox.showerror(APP_TITLE, "API Key 格式不正确。")
            return False
        self.key_path.write_text(candidate, encoding="ascii")
        self.api_key.set("")
        self.status_text.set("API Key 已只保存在本机应用数据目录")
        return True

    def refresh_player(self, silent: bool = False) -> None:
        if self.refreshing:
            return
        if self.api_key.get().strip() and not self._save_key():
            return
        key = self._saved_key()
        if not key:
            if not silent:
                messagebox.showwarning(APP_TITLE, "请先输入并保存 Riot API Key。")
            self.status_text.set("等待 Riot API Key")
            return
        try:
            game_name, tag_line = parse_riot_id(self.riot_id.get())
        except ValueError as exc:
            if not silent:
                messagebox.showerror(APP_TITLE, str(exc))
            return
        self.refreshing = True
        self.status_text.set("正在检查 Riot 最近比赛…")
        threading.Thread(target=self._refresh_worker, args=(key, game_name, tag_line, silent), daemon=True).start()

    def _refresh_worker(self, key: str, game_name: str, tag_line: str, silent: bool) -> None:
        try:
            platform = self.settings.get("collection", {}).get("platform", "oc1")
            matches = int(self.settings.get("player_case", {}).get("matches", 20))
            split_minute = int(self.settings["conditional_model"]["late_phase_start_minute"])
            client = RiotClient(key, platform, self.data_dir / "cache")
            account = client.account_by_riot_id(game_name, tag_line)
            requested_ids = client.match_ids(account["puuid"], matches)
            rows = []
            replays = {}
            for match_id in requested_ids:
                match_data = client.match(match_id)
                timeline_data = client.timeline(match_id)
                row = extract_player_match(
                    match_data, timeline_data, account["puuid"],
                    {"tier": "LOCAL_CASE", "rank": "", "leaguePoints": 0}, late_start_minute=split_minute,
                )
                if not row:
                    continue
                fights = number(row.get("late_teamfights")) or 0
                participations = number(row.get("late_teamfight_participations")) or 0
                row["late_teamfight_participation_rate"] = participations / fights if fights else None
                rows.append(row)
                replay = extract_match_replay(match_data, timeline_data)
                if replay:
                    replays[match_id] = replay
            payload = case_payload(
                rows,
                riot_id=f"{account.get('gameName', game_name)}#{account.get('tagLine', tag_line)}",
                platform=platform,
                requested_matches=len(requested_ids),
                conditional_parameters=self.settings["conditional_model"],
            )
            replay_dir = self.data_dir / "replays"
            replay_dir.mkdir(parents=True, exist_ok=True)
            for public_match, row in zip(payload.get("matches", []), rows):
                replay_ref = str(row.get("match_id") or "")
                if not replay_ref or replay_ref not in replays:
                    continue
                public_match["replayRef"] = replay_ref
                replay_file = replay_dir / f"{Path(replay_ref).name}.json"
                replay_next = replay_file.with_suffix(".next")
                replay_next.write_text(json.dumps(replays[replay_ref], ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
                os.replace(replay_next, replay_file)
            old_starts = {match.get("gameStartMs") for match in self.case.get("matches", [])}
            new_count = sum(match.get("gameStartMs") not in old_starts for match in payload.get("matches", []))
            temporary = self.case_path.with_suffix(".next")
            temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(temporary, self.case_path)
            self.after(0, self._apply_refresh, payload, new_count)
        except Exception as exc:
            self.after(0, self._refresh_failed, str(exc), silent)

    def _apply_refresh(self, payload: dict, new_count: int) -> None:
        self.case = payload
        self.riot_id.set(payload.get("meta", {}).get("riotId", self.riot_id.get()))
        self.refreshing = False
        self._populate_matches()
        self._update_dynamic_cards()
        self.status_text.set(f"更新完成 · 新增 {new_count} 场 · {datetime.now().strftime('%H:%M:%S')}")

    def _refresh_failed(self, error: str, silent: bool) -> None:
        self.refreshing = False
        friendly = "Riot API Key 已失效，请粘贴新 Key" if "401" in error or "apikey" in error.lower() else f"更新失败：{error}"
        self.status_text.set(friendly)
        if not silent:
            messagebox.showerror(APP_TITLE, friendly)

    def _auto_tick(self) -> None:
        if self.auto_refresh.get() and not self.refreshing:
            self.refresh_player(silent=True)
        self.after(60_000, self._auto_tick)


def main() -> None:
    app = ComparatorApp()
    app.mainloop()


if __name__ == "__main__":
    main()
