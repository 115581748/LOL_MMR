import unittest
import json
import io
import tempfile
from pathlib import Path
from unittest.mock import patch

from riot_model.benchmark import build_benchmarks, read_csv
from riot_model.cli import _checkpoint_rows, _materialize_checkpoint, diamond_plus_entries
from riot_model.client import RiotClient
from riot_model.features import extract_match_replay, extract_player_match
from tools.build_conditional_model import group_specs, phase_metrics, unique_player_matches
from tools.build_player_case import primary_profile, public_match
from tools.audit_player_matches import audit_csv, audit_jsonl
from tools.player_case_server import parse_riot_id
from tools.refresh_comparison_profiles import PREFIX as CONDITIONAL_PREFIX, refresh as refresh_comparisons
from tools.derive_late_rates import late_rate_values


def frame(minute, gold, xp, cs, damage, taken, events=None):
    return {"timestamp": minute * 60_000, "participantFrames": {"1": {"totalGold": gold, "xp": xp, "minionsKilled": cs,
            "jungleMinionsKilled": 0, "damageStats": {"totalDamageDoneToChampions": damage, "totalDamageTaken": taken}}}, "events": events or []}


class PipelineTests(unittest.TestCase):
    def test_player_case_server_parses_riot_id_and_opgg_url(self):
        self.assertEqual(parse_riot_id("Geolonwe#OC"), ("Geolonwe", "OC"))
        self.assertEqual(
            parse_riot_id("https://op.gg/lol/summoners/oce/Addy%20The%20Great-OC"),
            ("Addy The Great", "OC"),
        )
        with self.assertRaises(ValueError):
            parse_riot_id("missing-tag")

    def test_player_match_audit_detects_and_cleans_duplicates(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            checkpoint = root / "matches.jsonl"
            clean = root / "clean.jsonl"
            processed = root / "matches.csv"
            checkpoint.write_text("".join([
                json.dumps({"puuid": "a", "match_id": "OC1_1", "value": 1}) + "\n",
                json.dumps({"puuid": "b", "match_id": "OC1_1", "value": 2}) + "\n",
                json.dumps({"puuid": "a", "match_id": "OC1_1", "value": 3}) + "\n",
                json.dumps({"puuid": "", "match_id": "OC1_2"}) + "\n",
                "not-json\n",
            ]), encoding="utf-8")
            report = audit_jsonl(checkpoint, clean)
            self.assertEqual(report["unique_player_matches"], 2)
            self.assertEqual(report["duplicate_rows_removed"], 1)
            self.assertEqual(report["conflicting_duplicate_rows"], 1)
            self.assertEqual(report["missing_identity_lines_removed"], 1)
            self.assertEqual(report["invalid_json_lines_removed"], 1)
            cleaned = [json.loads(line) for line in clean.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(next(row for row in cleaned if row["puuid"] == "a")["value"], 3)
            processed.write_text("puuid,match_id\na,OC1_1\nb,OC1_1\n", encoding="utf-8")
            self.assertEqual(audit_csv(processed)["duplicate_rows"], 0)

    def test_riot_client_retries_socket_read_timeout(self):
        client = RiotClient("test-key")
        with patch("riot_model.client.urllib.request.urlopen", side_effect=[
            TimeoutError("timed out"),
            io.BytesIO(b'{"ok": true}'),
        ]), patch("riot_model.client.time.sleep"):
            self.assertEqual(client._get("oc1", "/test"), {"ok": True})

    def test_riot_client_preserves_documented_token_header_case(self):
        client = RiotClient("test-key")

        def open_request(request, timeout):
            headers = dict(request.header_items())
            self.assertEqual(timeout, 30)
            self.assertEqual(headers.get("X-Riot-Token"), "test-key")
            self.assertNotIn("X-riot-token", headers)
            return io.BytesIO(b'{"ok": true}')

        with patch("riot_model.client.urllib.request.urlopen", side_effect=open_request):
            self.assertEqual(client._get("oc1", "/test"), {"ok": True})

    def test_diamond_plus_enumerates_all_oce_tiers_with_ttl(self):
        class FakeClient:
            def __init__(self):
                self.cache_ages = []

            def league_entries(self, tier, division, page, cache_max_age_seconds=None):
                self.cache_ages.append(cache_max_age_seconds)
                return [{"puuid": f"diamond-{division}", "tier": tier, "rank": division}] if page == 1 else []

            def top_league(self, tier):
                return {"entries": [{"puuid": tier, "leaguePoints": 500}]}

        client = FakeClient()
        entries = diamond_plus_entries(client, league_cache_max_age_minutes=120)
        self.assertEqual(len(entries), 7)
        self.assertEqual({entry["tier"] for entry in entries}, {"DIAMOND", "MASTER", "GRANDMASTER", "CHALLENGER"})
        self.assertTrue(all(age == 7200 for age in client.cache_ages))

    def test_extract_phases(self):
        match = {"metadata": {"matchId": "OC1_1"}, "info": {"queueId": 420, "gameDuration": 2100, "gameVersion": "16.1",
                 "gameStartTimestamp": 1, "participants": [{"puuid": "p", "participantId": 1, "teamId": 100, "championId": 103,
                 "championName": "Ahri", "teamPosition": "MIDDLE", "win": True, "totalMinionsKilled": 200, "neutralMinionsKilled": 0,
                 "totalDamageDealtToChampions": 21000, "visionScore": 35}]}}
        early_kill = {"type": "CHAMPION_KILL", "timestamp": 10*60_000, "killerId": 1, "victimId": 6, "assistingParticipantIds": []}
        dragon = {"type": "ELITE_MONSTER_KILL", "timestamp": 20*60_000, "monsterType": "DRAGON", "killerTeamId": 100}
        timeline = {"info": {"frames": [frame(0, 500, 0, 0, 0, 0), frame(10, 4000, 4000, 70, 2000, 1000, [early_kill]),
                    frame(15, 6000, 6000, 110, 4000, 2000), frame(20, 8000, 8000, 145, 7000, 3500, [dragon]), frame(25, 9500, 9500, 170, 9000, 4500),
                    frame(30, 11000, 11000, 190, 12000, 6000), frame(35, 14000, 13000, 220, 21000, 9000)]}}
        row = extract_player_match(match, timeline, "p", {"tier": "CHALLENGER", "rank": "I", "leaguePoints": 900})
        self.assertEqual(row["early_gold_15"], 5500); self.assertEqual(row["early_kills"], 1)
        self.assertEqual(row["mid_team_dragons"], 1); self.assertEqual(row["late_champion_damage"], 9000)
        self.assertEqual(row["late_duration_min"], 5)
        self.assertEqual(row["late_champion_damage_per_min"], 1800)
        self.assertEqual(row["end_visionScore"], 35)
        row_25 = extract_player_match(match, timeline, "p", {"tier": "CHALLENGER"}, late_start_minute=25)
        self.assertEqual(row_25["phase_split_minute"], 25)
        self.assertEqual(row_25["mid_gold_gain"], 3500)
        self.assertEqual(row_25["late_champion_damage"], 12000)
        self.assertEqual(row_25["late_duration_min"], 10)
        self.assertEqual(row_25["late_champion_damage_per_min"], 1200)
        self.assertIsNone(row_25["early_gank_takedowns"])

    def test_jungle_actions_distinguish_equal_resource_games(self):
        participants = []
        roles = ["JUNGLE", "TOP", "MIDDLE", "BOTTOM", "UTILITY"] * 2
        for index, role in enumerate(roles, 1):
            participants.append({
                "puuid": "player" if index == 1 else f"p{index}",
                "participantId": index,
                "teamId": 100 if index <= 5 else 200,
                "championId": index,
                "championName": f"Champion{index}",
                "teamPosition": role,
                "win": index <= 5,
            })

        def jungle_frame(minute, own_gold, own_xp, own_cs, enemy_gold, enemy_xp, enemy_cs, events=None):
            def participant_frame(gold, xp, cs):
                return {
                    "totalGold": gold,
                    "xp": xp,
                    "minionsKilled": 0,
                    "jungleMinionsKilled": cs,
                    "damageStats": {"totalDamageDoneToChampions": 0, "totalDamageTaken": 0},
                }
            return {
                "timestamp": minute * 60_000,
                "participantFrames": {
                    "1": participant_frame(own_gold, own_xp, own_cs),
                    "6": participant_frame(enemy_gold, enemy_xp, enemy_cs),
                },
                "events": events or [],
            }

        early_events = [
            {"type": "CHAMPION_KILL", "timestamp": 8 * 60_000, "killerId": 3, "victimId": 7, "assistingParticipantIds": [1]},
            {"type": "CHAMPION_KILL", "timestamp": 10 * 60_000, "killerId": 1, "victimId": 8, "assistingParticipantIds": []},
            {"type": "CHAMPION_KILL", "timestamp": 13 * 60_000, "killerId": 6, "victimId": 2, "assistingParticipantIds": []},
            {"type": "ELITE_MONSTER_KILL", "timestamp": 11 * 60_000, "monsterType": "DRAGON", "killerTeamId": 100, "killerId": 1},
            {"type": "ELITE_MONSTER_KILL", "timestamp": 12 * 60_000, "monsterType": "HORDE", "killerTeamId": 100, "killerId": 3},
        ]
        match = {
            "metadata": {"matchId": "OC1_JUNGLE"},
            "info": {
                "queueId": 420,
                "gameDuration": 1800,
                "gameVersion": "16.15",
                "gameStartTimestamp": 1,
                "participants": participants,
            },
        }
        timeline = {"info": {"frames": [
            jungle_frame(0, 500, 0, 0, 500, 0, 0),
            jungle_frame(15, 6000, 6000, 80, 5800, 5700, 75, early_events),
            jungle_frame(25, 9500, 9500, 140, 9300, 9200, 135),
            jungle_frame(30, 12000, 11000, 170, 11800, 10800, 165),
        ]}}
        row = extract_player_match(match, timeline, "player", {"tier": "MASTER"}, late_start_minute=25)
        self.assertEqual(row["early_gold_diff_vs_enemy_jungle"], 200)
        self.assertEqual(row["early_xp_diff_vs_enemy_jungle"], 300)
        self.assertEqual(row["early_cs_diff_vs_enemy_jungle"], 5)
        self.assertEqual(row["early_gank_takedowns"], 2)
        self.assertEqual(row["early_gank_lanes"], 2)
        self.assertEqual(row["early_first_gank_minute"], 8)
        self.assertEqual(row["early_team_dragons"], 1)
        self.assertEqual(row["early_team_void_grubs"], 1)
        self.assertEqual(row["early_personal_epic_secures"], 1)
        self.assertEqual(row["early_gank_takedown_diff_vs_enemy_jungle"], 1)
        self.assertEqual(row["early_epic_monster_diff_vs_enemy_jungle"], 2)
        self.assertEqual(row["opponent_champion"], "Champion6")
        self.assertEqual(row["opponent_position"], "JUNGLE")
        self.assertEqual(row["opponent_early_gold_15"], 5300)
        self.assertEqual(row["opponent_early_gank_takedowns"], 1)
        self.assertEqual(row["opponent_early_gank_takedown_diff_vs_enemy_jungle"], -1)
        self.assertEqual(row["opponent_early_epic_monster_diff_vs_enemy_jungle"], -2)
        exported = public_match(row, 0)
        self.assertEqual(exported["opponentChampion"], "Champion6")
        self.assertEqual(exported["opponent_early_gold_15"], 5300)

    def test_replay_has_every_player_at_every_minute(self):
        participants = []
        participant_frames = {}
        for pid in range(1, 11):
            participants.append({"participantId": pid, "teamId": 100 if pid <= 5 else 200,
                                 "championName": f"Champion{pid}", "teamPosition": "MIDDLE", "win": pid <= 5,
                                 "summoner1Id": 4, "summoner2Id": 14})
            participant_frames[str(pid)] = {"position": {"x": 1000 * pid, "y": 900 * pid}, "level": 2,
                                            "xp": 100, "currentGold": 500, "totalGold": 1000,
                                            "minionsKilled": 5, "jungleMinionsKilled": 0}
        match = {"metadata": {"matchId": "OC1_REPLAY"}, "info": {"queueId": 420, "mapId": 11,
                 "gameDuration": 125, "gameVersion": "16.1", "participants": participants}}
        timeline = {"info": {"frames": [{"timestamp": minute * 60_000, "participantFrames": participant_frames, "events": []}
                                         for minute in range(3)]}}
        replay = extract_match_replay(match, timeline)
        self.assertEqual(len(replay["frames"]), 3)
        self.assertEqual(replay["schemaVersion"], 3)
        self.assertEqual(replay["players"][0]["summoner1Id"], 4)
        self.assertEqual(replay["players"][0]["summoner2Id"], 14)
        self.assertTrue(all(len(frame["players"]) == 10 for frame in replay["frames"]))
        self.assertEqual(replay["frames"][1]["players"][9]["x"], 10000)

    def test_iqr_removes_outlier(self):
        rows = [{"champion": "Ahri", "position": "MIDDLE", "metric": x} for x in [10, 10, 11, 9, 100]]
        model = build_benchmarks(rows, 5)
        self.assertEqual(model[0]["n_clean"], 4); self.assertEqual(model[0]["mean"], 10)

    def test_iqr_multiplier_is_parameterized(self):
        rows = [{"champion": "Ahri", "position": "MIDDLE", "metric": x} for x in [10, 10, 11, 9, 100]]
        relaxed = build_benchmarks(rows, minimum_samples=5, iqr_multiplier=100)
        self.assertEqual(relaxed[0]["n_clean"], 5)

    def test_conditional_comparison_deduplicates_player_matches(self):
        rows = [
            {"match_id": "OC1_1", "puuid": "a", "metric": 1},
            {"match_id": "OC1_1", "puuid": "a", "metric": 1},
            {"match_id": "OC1_1", "puuid": "b", "metric": 2},
            {"match_id": "OC1_2", "puuid": "a", "metric": 3},
        ]
        unique = unique_player_matches(rows)
        self.assertEqual(len(unique), 3)

    def test_reference_model_has_no_game_state_dimension(self):
        row = {"patch": "16.15", "champion": "Ashe", "position": "BOTTOM", "rankBand": "DIAMOND_IV_II"}
        specs = list(group_specs(row, "EARLY"))
        self.assertTrue(all(len(parts) == 6 for parts in specs))
        self.assertIn(("CHAMPION_ALL_PATCH", "ALL", "Ashe", "BOTTOM", "ALL", "EARLY"), specs)
        exported = public_match({
            "phase_split_minute": 25, "game_start_ms": 1, "game_version": "16.15",
            "duration_min": 30, "champion": "Ashe", "position": "BOTTOM", "win": 1,
            "state15": "AHEAD", "stateLateStart": "EVEN", "goldDiff15": 1500,
        }, 0)
        self.assertFalse(any("state" in field.lower() or "golddiff" in field.lower() for field in exported))
        self.assertIn("early_gank_takedowns", phase_metrics("EARLY", "JUNGLE"))
        self.assertNotIn("early_gank_takedowns", phase_metrics("EARLY", "BOTTOM"))

    def test_checkpoint_rows_deduplicate_player_matches_using_latest_row(self):
        rows = [
            {"puuid": "a", "match_id": "OC1_1", "league_points": 10},
            {"puuid": "b", "match_id": "OC1_1", "league_points": 20},
            {"puuid": "a", "match_id": "OC1_1", "league_points": 30},
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "checkpoint.jsonl"
            path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
            recovered = _checkpoint_rows(path)
        self.assertEqual(len(recovered), 2)
        latest = next(row for row in recovered if row["puuid"] == "a")
        self.assertEqual(latest["league_points"], 30)

    def test_checkpoint_materialization_streams_latest_unique_rows(self):
        rows = [
            {"puuid": "a", "match_id": "OC1_1", "league_points": 10},
            {"puuid": "b", "match_id": "OC1_1", "champion": "Ashe"},
            {"puuid": "a", "match_id": "OC1_1", "league_points": 30, "position": "BOTTOM"},
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            checkpoint = root / "checkpoint.jsonl"
            output = root / "matches.csv"
            checkpoint.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
            report = _materialize_checkpoint(checkpoint, output)
            materialized = read_csv(output)
        self.assertEqual(report, {"players": 2, "matches": 1, "rows": 2})
        self.assertEqual(len(materialized), 2)
        latest = next(row for row in materialized if row["puuid"] == "a")
        self.assertEqual(latest["league_points"], "30")
        self.assertEqual(latest["position"], "BOTTOM")

    def test_player_case_derives_primary_champion_within_primary_position(self):
        rows = [
            {"position": "BOTTOM", "champion": "Jhin"},
            {"position": "BOTTOM", "champion": "Jhin"},
            {"position": "BOTTOM", "champion": "Ashe"},
            {"position": "TOP", "champion": "Aatrox"},
        ]
        self.assertEqual(primary_profile(rows), {
            "primaryPosition": "BOTTOM",
            "primaryPositionMatches": 3,
            "primaryChampion": "Jhin",
            "primaryChampionPositionMatches": 2,
        })

    def test_comparison_refresh_selects_only_current_player_pairs(self):
        def profile(champion, phase):
            return {
                "scope": "CHAMPION_ALL_PATCH", "patch": "ALL", "champion": champion,
                "position": "JUNGLE", "rankBand": "ALL", "phase": phase,
                "sampleSize": 30, "metrics": {},
            }

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model_path = root / "conditional.js"
            player_path = root / "player.js"
            profiles = {}
            for champion in ("XinZhao", "Graves"):
                for phase in ("EARLY", "MID", "LATE"):
                    key = f"CHAMPION_ALL_PATCH|ALL|{champion}|JUNGLE|ALL|{phase}"
                    profiles[key] = profile(champion, phase)
            model_path.write_text(
                CONDITIONAL_PREFIX + json.dumps({"meta": {}, "profiles": profiles}) + ";\n",
                encoding="utf-8",
            )
            player_path.write_text(
                "window.PLAYER_CASE=" + json.dumps({
                    "matches": [{
                        "champion": "XinZhao", "position": "JUNGLE",
                        "opponentChampion": "Graves", "opponentPosition": "JUNGLE",
                    }],
                }) + ";\n",
                encoding="utf-8",
            )
            result = refresh_comparisons(model_path, player_path, model_path)
            refreshed = json.loads(model_path.read_text(encoding="utf-8")[len(CONDITIONAL_PREFIX):-2])
        self.assertEqual(result, {"pairs": 2, "profiles": 6})
        self.assertTrue(any("XinZhao" in key for key in refreshed["comparisonProfiles"]))
        self.assertTrue(any("Graves" in key for key in refreshed["comparisonProfiles"]))
        self.assertEqual(refreshed["meta"]["comparisonPlayerPairs"], [["Graves", "JUNGLE"], ["XinZhao", "JUNGLE"]])

    def test_benchmark_does_not_treat_opponent_snapshot_as_own_average(self):
        rows = [
            {"champion": "Ahri", "position": "MIDDLE", "metric": value, "opponent_metric": 100 + value}
            for value in [10, 10, 11, 9, 12]
        ]
        model = build_benchmarks(rows, 5)
        self.assertEqual([entry["metric"] for entry in model], ["metric"])

    def test_late_damage_rates_normalize_different_game_lengths(self):
        thirty_five = late_rate_values({
            "duration_min": 35, "phase_split_minute": 25,
            "late_champion_damage": 10000, "late_damage_taken": 12000,
        })
        fifty = late_rate_values({
            "duration_min": 50, "phase_split_minute": 25,
            "late_champion_damage": 25000, "late_damage_taken": 30000,
        })
        self.assertEqual(thirty_five["late_champion_damage_per_min"], 1000)
        self.assertEqual(fifty["late_champion_damage_per_min"], 1000)
        self.assertEqual(thirty_five["late_damage_taken_per_min"], 1200)
        self.assertEqual(fifty["late_damage_taken_per_min"], 1200)


if __name__ == "__main__": unittest.main()
