from __future__ import annotations

from collections import defaultdict
import math


def _n(value):
    return float(value or 0)


def _flat_numeric(prefix, source):
    """Preserve every scalar numeric API metric without committing to a fixed patch schema."""
    output = {}
    categorical_ids = {"participantId", "teamId", "championId", "summoner1Id", "summoner2Id", "profileIcon"}
    for key, value in (source or {}).items():
        if key in categorical_ids:
            continue
        if isinstance(value, bool):
            output[f"{prefix}{key}"] = int(value)
        elif isinstance(value, (int, float)):
            output[f"{prefix}{key}"] = value
    return output


def _frame_at(frames, minute: int):
    eligible = [f for f in frames if _n(f.get("timestamp")) <= minute * 60_000]
    return eligible[-1] if eligible else frames[0]


def _participant_frame(frame, participant_id: int):
    return frame.get("participantFrames", {}).get(str(participant_id), {})


def _snapshot(pf):
    damage = pf.get("damageStats", {})
    return {
        "gold": _n(pf.get("totalGold")), "xp": _n(pf.get("xp")),
        "cs": _n(pf.get("minionsKilled")) + _n(pf.get("jungleMinionsKilled")),
        "champion_damage": _n(damage.get("totalDamageDoneToChampions")),
        "damage_taken": _n(damage.get("totalDamageTaken")),
    }


def _phase_events(frames, start_minute: int, end_minute: int | None):
    start, end = start_minute * 60_000, (end_minute * 60_000 if end_minute else float("inf"))
    return [e for f in frames for e in f.get("events", []) if start <= _n(e.get("timestamp")) < end]


def _combat(events, pid):
    kills = deaths = assists = 0
    for e in events:
        if e.get("type") != "CHAMPION_KILL":
            continue
        kills += e.get("killerId") == pid
        deaths += e.get("victimId") == pid
        assists += pid in e.get("assistingParticipantIds", [])
    return kills, deaths, assists


def _role(participant: dict) -> str:
    return str(participant.get("teamPosition") or participant.get("individualPosition") or "UNKNOWN").upper()


def _lane_for_role(role: str) -> str | None:
    if role == "TOP":
        return "TOP"
    if role == "MIDDLE":
        return "MIDDLE"
    if role in {"BOTTOM", "UTILITY"}:
        return "BOTTOM"
    return None


def _jungle_action_metrics(events: list[dict], participant: dict, participants: list[dict]) -> dict:
    """Observable jungle actions from Match-v5 timeline events.

    Riot does not emit a reliable failed-gank event. A gank here therefore means
    a kill/assist by the jungler on a non-jungle opponent, and the name exported
    to the model explicitly calls it an effective gank/takedown proxy.
    """
    pid = participant.get("participantId")
    team_id = participant.get("teamId")
    by_id = {item.get("participantId"): item for item in participants}
    team_kills = 0
    takedowns = 0
    gank_events = []
    enemy_jungle_takedowns = 0
    for event in events:
        if event.get("type") != "CHAMPION_KILL":
            continue
        killer = by_id.get(event.get("killerId"), {})
        if killer.get("teamId") == team_id:
            team_kills += 1
        involved = event.get("killerId") == pid or pid in (event.get("assistingParticipantIds") or [])
        if not involved:
            continue
        takedowns += 1
        victim_role = _role(by_id.get(event.get("victimId"), {}))
        if victim_role == "JUNGLE":
            enemy_jungle_takedowns += 1
        elif _lane_for_role(victim_role):
            gank_events.append(event)

    lanes = {
        _lane_for_role(_role(by_id.get(event.get("victimId"), {})))
        for event in gank_events
    }
    lanes.discard(None)
    epic = {"dragons": 0, "void_grubs": 0, "rift_heralds": 0}
    personal_secures = 0
    monster_fields = {
        "DRAGON": "dragons",
        "HORDE": "void_grubs",
        "RIFTHERALD": "rift_heralds",
    }
    for event in events:
        if event.get("type") != "ELITE_MONSTER_KILL" or event.get("killerTeamId") != team_id:
            continue
        field = monster_fields.get(str(event.get("monsterType") or "").upper())
        if not field:
            continue
        epic[field] += 1
        personal_secures += event.get("killerId") == pid

    return {
        "gank_takedowns": len(gank_events),
        "gank_lanes": len(lanes),
        "first_gank_minute": round(min((event.get("timestamp", 0) for event in gank_events), default=0) / 60_000, 3)
        if gank_events else None,
        "enemy_jungle_takedowns": enemy_jungle_takedowns,
        "kill_participation_rate": takedowns / team_kills if team_kills else None,
        "team_dragons": epic["dragons"],
        "team_void_grubs": epic["void_grubs"],
        "team_rift_heralds": epic["rift_heralds"],
        "personal_epic_secures": personal_secures,
        "team_epic_monsters": sum(epic.values()),
    }


JUNGLE_PHASE_FIELDS = (
    "gank_takedowns", "gank_lanes", "first_gank_minute", "enemy_jungle_takedowns",
    "kill_participation_rate", "team_dragons", "team_void_grubs", "team_rift_heralds",
    "personal_epic_secures", "gank_takedown_diff_vs_enemy_jungle",
    "epic_monster_diff_vs_enemy_jungle",
)


def _jungle_phase_output(prefix: str, own: dict | None, opponent: dict | None) -> dict:
    output = {f"{prefix}_{field}": None for field in JUNGLE_PHASE_FIELDS}
    if own is None:
        return output
    for field in JUNGLE_PHASE_FIELDS[:9]:
        output[f"{prefix}_{field}"] = own[field]
    if opponent is not None:
        output[f"{prefix}_gank_takedown_diff_vs_enemy_jungle"] = own["gank_takedowns"] - opponent["gank_takedowns"]
        output[f"{prefix}_epic_monster_diff_vs_enemy_jungle"] = own["team_epic_monsters"] - opponent["team_epic_monsters"]
    return output


def _teamfights(events):
    kills = sorted((e for e in events if e.get("type") == "CHAMPION_KILL"), key=lambda e: e.get("timestamp", 0))
    groups = []
    for event in kills:
        if not groups or event.get("timestamp", 0) - groups[-1][-1].get("timestamp", 0) > 15_000:
            groups.append([event])
        else:
            groups[-1].append(event)
    return [g for g in groups if len(g) >= 3]


def _public_event(event):
    """Keep replay-relevant event fields while excluding player account identifiers."""
    fields = (
        "type", "timestamp", "killerId", "victimId", "creatorId", "participantId",
        "assistingParticipantIds", "killerTeamId", "teamId", "monsterType", "monsterSubType",
        "buildingType", "towerType", "laneType", "wardType", "shutdownBounty", "name",
        "itemId", "beforeId", "afterId", "goldGain",
    )
    output = {key: event[key] for key in fields if key in event}
    position = event.get("position") or {}
    if "x" in position and "y" in position:
        output["position"] = {"x": position["x"], "y": position["y"]}
    return output


def extract_match_replay(match: dict, timeline: dict) -> dict | None:
    """Create an anonymous, minute-normalized ten-player map replay.

    Riot timeline frames are approximately one minute apart. We normalize them
    to integer minute slots and use the latest available frame at each slot.
    Coordinates are real timeline samples, not interpolated paths.
    """
    info = match.get("info", {})
    participants = info.get("participants", [])
    frames = timeline.get("info", {}).get("frames", [])
    if len(participants) != 10 or not frames:
        return None
    public_players = []
    for participant in participants:
        public_players.append({
            "participantId": participant.get("participantId"),
            "teamId": participant.get("teamId"),
            "champion": participant.get("championName"),
            "position": participant.get("teamPosition") or participant.get("individualPosition") or "UNKNOWN",
            "summoner1Id": participant.get("summoner1Id"), "summoner2Id": participant.get("summoner2Id"),
            "win": bool(participant.get("win")),
            "kills": participant.get("kills", 0), "deaths": participant.get("deaths", 0),
            "assists": participant.get("assists", 0), "totalGold": participant.get("goldEarned", 0),
        })
    duration_seconds = int(info.get("gameDuration", 0))
    total_minutes = max(0, math.floor(duration_seconds / 60))
    replay_frames = []
    for minute in range(total_minutes + 1):
        frame = _frame_at(frames, minute)
        players = []
        for participant in public_players:
            pf = _participant_frame(frame, participant["participantId"])
            position = pf.get("position") or {}
            players.append({
                "participantId": participant["participantId"],
                "x": position.get("x"), "y": position.get("y"),
                "level": pf.get("level", 0), "xp": pf.get("xp", 0),
                "currentGold": pf.get("currentGold", 0), "totalGold": pf.get("totalGold", 0),
                "minions": pf.get("minionsKilled", 0), "jungleMinions": pf.get("jungleMinionsKilled", 0),
            })
        minute_events = [
            _public_event(event)
            for raw_frame in frames
            for event in raw_frame.get("events", [])
            if minute * 60_000 <= _n(event.get("timestamp")) < (minute + 1) * 60_000
            and event.get("type") in {
                "CHAMPION_KILL", "ELITE_MONSTER_KILL", "BUILDING_KILL",
                "DRAGON_SOUL_GIVEN", "WARD_PLACED", "WARD_KILL",
                "ITEM_PURCHASED", "ITEM_SOLD", "ITEM_DESTROYED", "ITEM_UNDO",
            }
        ]
        replay_frames.append({"minute": minute, "timestamp": minute * 60_000, "players": players, "events": minute_events})
    return {
        "schemaVersion": 3,
        "matchId": match.get("metadata", {}).get("matchId"),
        "gameVersion": info.get("gameVersion"), "queueId": info.get("queueId"),
        "durationSeconds": duration_seconds, "mapId": info.get("mapId"),
        "coordinateSource": "Riot Match-v5 Timeline participantFrames; latest frame at each integer minute",
        "players": public_players, "frames": replay_frames,
    }


def extract_player_match(match: dict, timeline: dict, puuid: str, rank: dict, late_start_minute: int = 30) -> dict | None:
    info = match.get("info", {})
    participants = info.get("participants", [])
    participant = next((p for p in participants if p.get("puuid") == puuid), None)
    if not participant or info.get("queueId") != 420 or info.get("gameDuration", 0) < 900:
        return None
    pid = participant["participantId"]
    frames = timeline.get("info", {}).get("frames", [])
    if not frames:
        return None
    s0 = _snapshot(_participant_frame(frames[0], pid))
    s15 = _snapshot(_participant_frame(_frame_at(frames, 15), pid))
    split_minute = int(late_start_minute)
    s_late = _snapshot(_participant_frame(_frame_at(frames, split_minute), pid))
    send = _snapshot(_participant_frame(frames[-1], pid))
    early = _phase_events(frames, 0, 15)
    mid = _phase_events(frames, 15, split_minute)
    late = _phase_events(frames, split_minute, None)
    ek, ed, ea = _combat(early, pid); mk, md, ma = _combat(mid, pid); lk, ld, la = _combat(late, pid)
    team_id = participant.get("teamId")
    player_role = _role(participant)
    is_jungle = player_role == "JUNGLE"
    opponent = next((
        item for item in participants
        if item.get("teamId") != team_id and _role(item) == player_role
    ), None)
    opposing_jungler = next((
        item for item in participants
        if item.get("teamId") != team_id and _role(item) == "JUNGLE"
    ), None)
    early_jungle = _jungle_action_metrics(early, participant, participants) if is_jungle else None
    mid_jungle = _jungle_action_metrics(mid, participant, participants) if is_jungle else None
    enemy_early_jungle = _jungle_action_metrics(early, opposing_jungler, participants) if opposing_jungler else None
    enemy_mid_jungle = _jungle_action_metrics(mid, opposing_jungler, participants) if opposing_jungler else None
    mid_turrets = sum(e.get("type") == "BUILDING_KILL" and e.get("buildingType") == "TOWER_BUILDING" and e.get("teamId") != team_id for e in mid)
    mid_dragons = sum(e.get("type") == "ELITE_MONSTER_KILL" and e.get("monsterType") == "DRAGON" and e.get("killerTeamId") == team_id for e in mid)
    fights = _teamfights(late)
    participated = [g for g in fights if any(e.get("killerId") == pid or pid in e.get("assistingParticipantIds", []) or e.get("victimId") == pid for e in g)]
    first_target_deaths = sum(g[0].get("victimId") == pid for g in fights)
    duration_min = info.get("gameDuration", 0) / 60
    late_duration_min = max(0, duration_min - split_minute)
    late_champion_damage = max(0, send["champion_damage"] - s_late["champion_damage"])
    late_damage_taken = max(0, send["damage_taken"] - s_late["damage_taken"])
    opponent_fields = {
        "opponent_champion_id": None, "opponent_champion": None, "opponent_position": None,
    }
    for phase in ("early", "mid", "late"):
        for metric in (
            ("gold_15", "xp_15", "cs_15", "kills", "deaths", "assists") if phase == "early" else
            ("gold_gain", "cs_gain", "champion_damage", "kills", "deaths", "assists", "team_turrets", "team_dragons") if phase == "mid" else
            ("duration_min", "champion_damage", "damage_taken", "champion_damage_per_min", "damage_taken_per_min",
             "kills", "deaths", "assists", "teamfights", "teamfight_participations", "teamfight_participation_rate",
             "first_target_deaths")
        ):
            opponent_fields[f"opponent_{phase}_{metric}"] = None

    if opponent:
        opponent_pid = opponent.get("participantId")
        opponent_team_id = opponent.get("teamId")
        opponent_s0 = _snapshot(_participant_frame(frames[0], opponent_pid))
        opponent_s15 = _snapshot(_participant_frame(_frame_at(frames, 15), opponent_pid))
        opponent_s_late = _snapshot(_participant_frame(_frame_at(frames, split_minute), opponent_pid))
        opponent_send = _snapshot(_participant_frame(frames[-1], opponent_pid))
        oek, oed, oea = _combat(early, opponent_pid)
        omk, omd, oma = _combat(mid, opponent_pid)
        olk, old, ola = _combat(late, opponent_pid)
        opponent_mid_turrets = sum(
            e.get("type") == "BUILDING_KILL"
            and e.get("buildingType") == "TOWER_BUILDING"
            and e.get("teamId") != opponent_team_id
            for e in mid
        )
        opponent_mid_dragons = sum(
            e.get("type") == "ELITE_MONSTER_KILL"
            and e.get("monsterType") == "DRAGON"
            and e.get("killerTeamId") == opponent_team_id
            for e in mid
        )
        opponent_participated = [
            group for group in fights
            if any(
                event.get("killerId") == opponent_pid
                or opponent_pid in event.get("assistingParticipantIds", [])
                or event.get("victimId") == opponent_pid
                for event in group
            )
        ]
        opponent_first_target_deaths = sum(group[0].get("victimId") == opponent_pid for group in fights)
        opponent_late_damage = max(0, opponent_send["champion_damage"] - opponent_s_late["champion_damage"])
        opponent_late_taken = max(0, opponent_send["damage_taken"] - opponent_s_late["damage_taken"])
        opponent_fields.update({
            "opponent_champion_id": opponent.get("championId"),
            "opponent_champion": opponent.get("championName"),
            "opponent_position": opponent.get("teamPosition") or opponent.get("individualPosition"),
            "opponent_early_gold_15": opponent_s15["gold"] - opponent_s0["gold"],
            "opponent_early_xp_15": opponent_s15["xp"] - opponent_s0["xp"],
            "opponent_early_cs_15": opponent_s15["cs"] - opponent_s0["cs"],
            "opponent_early_kills": oek, "opponent_early_deaths": oed, "opponent_early_assists": oea,
            "opponent_mid_gold_gain": max(0, opponent_s_late["gold"] - opponent_s15["gold"]),
            "opponent_mid_cs_gain": max(0, opponent_s_late["cs"] - opponent_s15["cs"]),
            "opponent_mid_champion_damage": max(0, opponent_s_late["champion_damage"] - opponent_s15["champion_damage"]),
            "opponent_mid_kills": omk, "opponent_mid_deaths": omd, "opponent_mid_assists": oma,
            "opponent_mid_team_turrets": opponent_mid_turrets, "opponent_mid_team_dragons": opponent_mid_dragons,
            "opponent_late_duration_min": round(late_duration_min, 3) if late_duration_min > 0 else None,
            "opponent_late_champion_damage": opponent_late_damage,
            "opponent_late_damage_taken": opponent_late_taken,
            "opponent_late_champion_damage_per_min": round(opponent_late_damage / late_duration_min, 4) if late_duration_min > 0 else None,
            "opponent_late_damage_taken_per_min": round(opponent_late_taken / late_duration_min, 4) if late_duration_min > 0 else None,
            "opponent_late_kills": olk, "opponent_late_deaths": old, "opponent_late_assists": ola,
            "opponent_late_teamfights": len(fights),
            "opponent_late_teamfight_participations": len(opponent_participated),
            "opponent_late_teamfight_participation_rate": len(opponent_participated) / len(fights) if fights else None,
            "opponent_late_first_target_deaths": opponent_first_target_deaths,
        })
    row = {
        "match_id": match.get("metadata", {}).get("matchId"), "game_version": info.get("gameVersion"),
        "game_start_ms": info.get("gameStartTimestamp"), "duration_min": round(duration_min, 3),
        "puuid": puuid, "tier": rank.get("tier"), "division": rank.get("rank"), "league_points": rank.get("leaguePoints"),
        "champion_id": participant.get("championId"), "champion": participant.get("championName"),
        "position": participant.get("teamPosition") or participant.get("individualPosition"), "win": int(bool(participant.get("win"))),
        "early_gold_15": s15["gold"] - s0["gold"], "early_xp_15": s15["xp"] - s0["xp"], "early_cs_15": s15["cs"] - s0["cs"],
        "early_kills": ek, "early_deaths": ed, "early_assists": ea,
        "phase_split_minute": split_minute,
        "mid_gold_gain": max(0, s_late["gold"] - s15["gold"]), "mid_cs_gain": max(0, s_late["cs"] - s15["cs"]),
        "mid_champion_damage": max(0, s_late["champion_damage"] - s15["champion_damage"]),
        "mid_kills": mk, "mid_deaths": md, "mid_assists": ma, "mid_team_turrets": mid_turrets, "mid_team_dragons": mid_dragons,
        "late_duration_min": round(late_duration_min, 3) if late_duration_min > 0 else None,
        "late_champion_damage": late_champion_damage,
        "late_damage_taken": late_damage_taken,
        "late_champion_damage_per_min": round(late_champion_damage / late_duration_min, 4) if late_duration_min > 0 else None,
        "late_damage_taken_per_min": round(late_damage_taken / late_duration_min, 4) if late_duration_min > 0 else None,
        "late_kills": lk, "late_deaths": ld, "late_assists": la,
        "late_teamfights": len(fights), "late_teamfight_participations": len(participated), "late_first_target_deaths": first_target_deaths,
        "cs_per_min": round((_n(participant.get("totalMinionsKilled")) + _n(participant.get("neutralMinionsKilled"))) / max(duration_min, 1), 4),
        "damage_per_min": round(_n(participant.get("totalDamageDealtToChampions")) / max(duration_min, 1), 4),
        "vision_per_min": round(_n(participant.get("visionScore")) / max(duration_min, 1), 4),
    }
    row.update(opponent_fields)
    row.update(_jungle_phase_output("early", early_jungle, enemy_early_jungle))
    mid_jungle_output = _jungle_phase_output("mid", mid_jungle, enemy_mid_jungle)
    # mid_team_dragons is a shared role metric already populated above. Keep it
    # available for every position instead of replacing non-jungle rows with None.
    mid_jungle_output.pop("mid_team_dragons", None)
    row.update(mid_jungle_output)
    jungle_resource_fields = {
        "early_gold_diff_vs_enemy_jungle": None,
        "early_xp_diff_vs_enemy_jungle": None,
        "early_cs_diff_vs_enemy_jungle": None,
    }
    if is_jungle and opposing_jungler:
        enemy_pid = opposing_jungler.get("participantId")
        enemy_s15 = _snapshot(_participant_frame(_frame_at(frames, 15), enemy_pid))
        jungle_resource_fields.update({
            "early_gold_diff_vs_enemy_jungle": s15["gold"] - enemy_s15["gold"],
            "early_xp_diff_vs_enemy_jungle": s15["xp"] - enemy_s15["xp"],
            "early_cs_diff_vs_enemy_jungle": s15["cs"] - enemy_s15["cs"],
        })
    row.update(jungle_resource_fields)
    opponent_jungle_fields = {}
    if is_jungle and opposing_jungler:
        for key, value in _jungle_phase_output("early", enemy_early_jungle, early_jungle).items():
            opponent_jungle_fields[f"opponent_{key}"] = value
        opponent_mid_output = _jungle_phase_output("mid", enemy_mid_jungle, mid_jungle)
        opponent_mid_output.pop("mid_team_dragons", None)
        for key, value in opponent_mid_output.items():
            opponent_jungle_fields[f"opponent_{key}"] = value
        opponent_jungle_fields.update({
            "opponent_early_gold_diff_vs_enemy_jungle": -jungle_resource_fields["early_gold_diff_vs_enemy_jungle"],
            "opponent_early_xp_diff_vs_enemy_jungle": -jungle_resource_fields["early_xp_diff_vs_enemy_jungle"],
            "opponent_early_cs_diff_vs_enemy_jungle": -jungle_resource_fields["early_cs_diff_vs_enemy_jungle"],
        })
    else:
        for phase in ("early", "mid"):
            for key in _jungle_phase_output(phase, None, None):
                if key == "mid_team_dragons":
                    continue
                opponent_jungle_fields[f"opponent_{key}"] = None
        opponent_jungle_fields.update({
            "opponent_early_gold_diff_vs_enemy_jungle": None,
            "opponent_early_xp_diff_vs_enemy_jungle": None,
            "opponent_early_cs_diff_vs_enemy_jungle": None,
        })
    row.update(opponent_jungle_fields)
    if split_minute == 30:
        row.update({
            "mid_gold_15_30": row["mid_gold_gain"],
            "mid_cs_15_30": row["mid_cs_gain"],
            "mid_champion_damage_15_30": row["mid_champion_damage"],
        })
    if duration_min < split_minute:
        for metric in (
            "late_duration_min", "late_champion_damage", "late_damage_taken",
            "late_champion_damage_per_min", "late_damage_taken_per_min",
            "late_kills", "late_deaths", "late_assists",
            "late_teamfights", "late_teamfight_participations", "late_first_target_deaths",
        ):
            row[metric] = None
            row[f"opponent_{metric}"] = None
    # Keep the complete numeric end-of-game and Challenges surfaces. Stable, named
    # phase metrics above remain the primary research variables; these columns make
    # exploratory modelling possible as Riot adds/removes patch-specific fields.
    row.update(_flat_numeric("end_", participant))
    row.update(_flat_numeric("challenge_", participant.get("challenges")))
    return row
