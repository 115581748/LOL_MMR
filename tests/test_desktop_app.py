import unittest

from desktop.lol_high_rank_comparator import (
    approximate_percentile,
    blend_hex,
    comparison_rows,
    death_states_at,
    detected_teamfight_events,
    estimated_minion_waves,
    estimated_respawn_seconds,
    format_clock,
    focus_participant_ids,
    map_coordinates,
    nearest_objective_loss,
    objective_loss_analysis,
    objective_loss_events,
    objective_event_position,
    objective_snapshot,
    parse_riot_id,
    recent_form_summary,
    replay_phase,
    replay_situation_snapshot,
    replay_event_lines,
    tab_snapshot,
    timeline_second_at_x,
)


class DesktopAppTests(unittest.TestCase):
    def test_dynamic_ui_helpers(self):
        self.assertEqual(blend_hex("#000000", "#ffffff", 0.5), "#808080")
        self.assertEqual(blend_hex("#112233", "#ffffff", -1), "#112233")
        summary = recent_form_summary([
            {"win": True}, {"win": True}, {"win": False}, {"win": True},
        ])
        self.assertEqual(summary["wins"], 3)
        self.assertEqual(summary["losses"], 1)
        self.assertEqual(summary["streak"], 2)
        self.assertTrue(summary["streakWin"])

    def test_parse_riot_id(self):
        self.assertEqual(parse_riot_id("Geolonwe#OC"), ("Geolonwe", "OC"))
        self.assertEqual(
            parse_riot_id("https://op.gg/lol/summoners/oce/Addy%20The%20Great-OC"),
            ("Addy The Great", "OC"),
        )

    def test_percentile_and_four_way_comparison(self):
        stats = {"p10": 10, "p25": 20, "median": 30, "p75": 40, "p90": 50}
        self.assertEqual(approximate_percentile(30, stats), 50)
        baselines = {
            "XinZhao|JUNGLE|EARLY": {"sampleSize": 100, "metrics": {"early_gold_15": stats}},
            "Vi|JUNGLE|EARLY": {"sampleSize": 80, "metrics": {"early_gold_15": {**stats, "median": 25}}},
        }
        match = {
            "champion": "XinZhao", "position": "JUNGLE",
            "opponentChampion": "Vi", "opponentPosition": "JUNGLE",
            "early_gold_15": 35, "opponent_early_gold_15": 20,
        }
        row = comparison_rows(match, "EARLY", baselines)[0]
        self.assertEqual(row[1], "35")
        self.assertEqual(row[2], "20")
        self.assertEqual(row[5], "+15")
        self.assertEqual(row[6], "+5")
        self.assertEqual(row[7], "-5")

    def test_map_coordinates_flip_vertical_axis(self):
        self.assertEqual(map_coordinates(0, 0, 600, 600), (0.0, 600.0))
        self.assertEqual(map_coordinates(15000, 15000, 600, 600), (600.0, 0.0))
        self.assertEqual(map_coordinates(7500, 7500, 600, 600), (300.0, 300.0))
        self.assertIsNone(map_coordinates(None, 100, 600, 600))

    def test_replay_situation_identifies_focus_objective_and_live_diffs(self):
        replay = {
            "players": [
                {"participantId": 2, "teamId": 100, "champion": "Talon", "position": "JUNGLE"},
                {"participantId": 7, "teamId": 200, "champion": "XinZhao", "position": "JUNGLE"},
            ],
            "frames": [{
                "timestamp": 10 * 60_000,
                "players": [
                    {"participantId": 2, "x": 9700, "y": 4500, "level": 8, "totalGold": 5200, "minions": 8, "jungleMinions": 70},
                    {"participantId": 7, "x": 9900, "y": 4300, "level": 7, "totalGold": 4900, "minions": 12, "jungleMinions": 60},
                ],
                "events": [
                    {"type": "WARD_PLACED", "timestamp": 9 * 60_000 + 30_000, "creatorId": 7},
                    {"type": "ELITE_MONSTER_KILL", "timestamp": 10 * 60_000 + 30_000, "killerTeamId": 100, "monsterType": "DRAGON", "monsterSubType": "FIRE_DRAGON"},
                ],
            }],
        }
        match = {"champion": "XinZhao", "position": "JUNGLE", "opponentChampion": "Talon", "opponentPosition": "JUNGLE"}
        self.assertEqual(focus_participant_ids(replay, match), (7, 2))
        self.assertEqual(replay_phase(899), "EARLY")
        self.assertEqual(replay_phase(900), "MID")
        self.assertEqual(replay_phase(1500), "LATE")
        snapshot = replay_situation_snapshot(replay, match, 600)
        self.assertEqual(snapshot["nextEpicName"], "火龙")
        self.assertEqual(snapshot["secondsUntilEpic"], 30)
        self.assertEqual(snapshot["nearby"], {100: 1, 200: 1})
        self.assertEqual(snapshot["wardsPlaced"], 1)
        self.assertEqual(snapshot["currentDiffs"], {"gold": -300, "cs": -6, "level": -1})
        self.assertEqual(objective_event_position(snapshot["nextEpic"]), {"x": 9850, "y": 4400})

    def test_objective_loss_analysis_builds_evidence_graph(self):
        players = [
            {"participantId": 1, "teamId": 100, "champion": "XinZhao", "position": "JUNGLE"},
            {"participantId": 2, "teamId": 100, "champion": "Ashe", "position": "BOTTOM"},
            {"participantId": 3, "teamId": 100, "champion": "Ahri", "position": "MIDDLE"},
            {"participantId": 6, "teamId": 200, "champion": "Nocturne", "position": "JUNGLE"},
            {"participantId": 7, "teamId": 200, "champion": "Jinx", "position": "BOTTOM"},
            {"participantId": 8, "teamId": 200, "champion": "Syndra", "position": "MIDDLE"},
        ]
        loss_event = {
            "type": "ELITE_MONSTER_KILL", "timestamp": 600_000,
            "killerTeamId": 200, "monsterType": "DRAGON", "monsterSubType": "FIRE_DRAGON",
        }
        replay = {
            "players": players,
            "frames": [{
                "timestamp": 600_000,
                "players": [
                    {"participantId": 1, "x": 3000, "y": 12000, "totalGold": 4700, "level": 8},
                    {"participantId": 2, "x": 9400, "y": 4400, "totalGold": 4300, "level": 7},
                    {"participantId": 3, "x": 7000, "y": 7000, "totalGold": 4500, "level": 8},
                    {"participantId": 6, "x": 9800, "y": 4400, "totalGold": 5200, "level": 9},
                    {"participantId": 7, "x": 10100, "y": 4300, "totalGold": 5000, "level": 8},
                    {"participantId": 8, "x": 9600, "y": 4700, "totalGold": 4900, "level": 9},
                ],
                "events": [
                    {"type": "ITEM_PURCHASED", "timestamp": 550_000, "participantId": 1, "itemId": 1036},
                    {"type": "CHAMPION_KILL", "timestamp": 565_000, "killerId": 6, "victimId": 3, "assistingParticipantIds": [7], "position": {"x": 9300, "y": 4500}},
                    {"type": "CHAMPION_KILL", "timestamp": 575_000, "killerId": 6, "victimId": 2, "assistingParticipantIds": [7, 8], "position": {"x": 9600, "y": 4400}},
                    {"type": "CHAMPION_KILL", "timestamp": 580_000, "killerId": 7, "victimId": 1, "assistingParticipantIds": [6, 8], "position": {"x": 9800, "y": 4300}},
                    {"type": "WARD_PLACED", "timestamp": 585_000, "creatorId": 7},
                    {"type": "WARD_PLACED", "timestamp": 590_000, "creatorId": 8},
                    loss_event,
                    {"type": "BUILDING_KILL", "timestamp": 630_000, "teamId": 200, "buildingType": "TOWER_BUILDING"},
                ],
            }],
        }
        match = {
            "champion": "XinZhao", "position": "JUNGLE",
            "opponentChampion": "Nocturne", "opponentPosition": "JUNGLE",
        }

        self.assertEqual(objective_loss_events(replay, match), [loss_event])
        self.assertIs(nearest_objective_loss(replay, match, 590), loss_event)
        analysis = objective_loss_analysis(replay, match, loss_event)
        primary = next(item for item in analysis["hypotheses"] if item["id"] == analysis["primaryHypothesisId"])
        self.assertEqual(primary["code"], "LOST_TEAMFIGHT_BEFORE_OBJECTIVE")
        self.assertEqual(analysis["detectorVersion"], "objective-loss-v2")
        self.assertTrue(any(item["code"] == "AREA_NUMBERS_DISADVANTAGE" for item in analysis["hypotheses"]))
        self.assertTrue(any(item["code"] == "CROSS_MAP_TRADE" for item in analysis["hypotheses"]))
        self.assertTrue(any(edge["type"] == "SUPPORTS" for edge in analysis["edges"]))
        self.assertTrue(any(edge["type"] == "MAY_CONTRIBUTE_TO" for edge in analysis["edges"]))

    def test_teamfight_detection_groups_exact_kill_events(self):
        replay = {
            "players": [
                {"participantId": 1, "teamId": 100, "champion": "XinZhao"},
                {"participantId": 2, "teamId": 100, "champion": "Ashe"},
                {"participantId": 3, "teamId": 100, "champion": "Ahri"},
                {"participantId": 6, "teamId": 200, "champion": "Nocturne"},
                {"participantId": 7, "teamId": 200, "champion": "Jinx"},
            ],
            "frames": [{"events": [
                {"type": "CHAMPION_KILL", "timestamp": 100_000, "killerId": 1, "victimId": 6, "assistingParticipantIds": [2], "position": {"x": 7000, "y": 7000}},
                {"type": "CHAMPION_KILL", "timestamp": 112_000, "killerId": 7, "victimId": 2, "assistingParticipantIds": [6], "position": {"x": 7200, "y": 7100}},
                {"type": "CHAMPION_KILL", "timestamp": 124_000, "killerId": 1, "victimId": 7, "assistingParticipantIds": [3], "position": {"x": 7400, "y": 7200}},
                {"type": "CHAMPION_KILL", "timestamp": 200_000, "killerId": 1, "victimId": 6},
                {"type": "CHAMPION_KILL", "timestamp": 216_000, "killerId": 7, "victimId": 2},
            ]}],
        }

        fights = detected_teamfight_events(replay)
        self.assertEqual(len(fights), 1)
        fight = fights[0]
        self.assertEqual(fight["timestamp"], 124_000)
        self.assertEqual(fight["killCount"], 3)
        self.assertEqual(fight["killsByTeam"], {100: 2, 200: 1})
        self.assertEqual(fight["winningTeamId"], 100)
        self.assertEqual(fight["position"], {"x": 7200, "y": 7100})
        self.assertTrue(fight["derived"])
        self.assertIn("规则识别", fight["source"])

    def test_replay_event_lines_use_champion_names(self):
        players = [
            {"participantId": 1, "champion": "XinZhao"},
            {"participantId": 6, "champion": "Vi"},
            {"participantId": 2, "champion": "Ashe"},
        ]
        frame = {"events": [{
            "type": "CHAMPION_KILL", "killerId": 1, "victimId": 6,
            "assistingParticipantIds": [2],
        }]}
        self.assertEqual(replay_event_lines(frame, players), ["击杀：XinZhao → Vi（助攻：Ashe）"])

    def test_second_precision_objectives_and_tab_state(self):
        replay = {
            "players": [
                {"participantId": 1, "teamId": 100, "champion": "Ashe"},
                {"participantId": 6, "teamId": 200, "champion": "Vi"},
            ],
            "frames": [{"events": [
                {"type": "ITEM_PURCHASED", "timestamp": 1000, "participantId": 1, "itemId": 1055},
                {"type": "CHAMPION_KILL", "timestamp": 12_500, "killerId": 1, "victimId": 6},
                {"type": "BUILDING_KILL", "timestamp": 20_000, "teamId": 200, "buildingType": "TOWER_BUILDING", "position": {"x": 100, "y": 100}},
                {"type": "ELITE_MONSTER_KILL", "timestamp": 25_000, "killerTeamId": 100, "monsterType": "DRAGON", "monsterSubType": "FIRE_DRAGON"},
                {"type": "DRAGON_SOUL_GIVEN", "timestamp": 30_000, "teamId": 100, "name": "Infernal"},
                {"type": "ITEM_DESTROYED", "timestamp": 40_000, "participantId": 1, "itemId": 1055},
            ]}],
        }
        self.assertEqual(format_clock(125), "02:05")
        self.assertEqual(timeline_second_at_x(500, 1000, 1800), 900)
        self.assertEqual(timeline_second_at_x(0, 1000, 1800), 0)
        self.assertEqual(timeline_second_at_x(1000, 1000, 1800), 1800)
        at_35 = objective_snapshot(replay, 35)["teams"][100]
        self.assertEqual(at_35["towers"], 1)
        self.assertEqual(at_35["dragons"], ["火龙"])
        self.assertEqual(at_35["soul"], "火龙魂")
        self.assertEqual(tab_snapshot(replay, 35)[1]["items"], [1055])
        self.assertEqual(tab_snapshot(replay, 35)[1]["kills"], 1)
        self.assertEqual(tab_snapshot(replay, 35)[6]["deaths"], 1)
        self.assertEqual(tab_snapshot(replay, 45)[1]["items"], [])

    def test_death_state_uses_exact_event_position_and_estimated_respawn(self):
        replay = {
            "frames": [
                {
                    "timestamp": 9 * 60_000,
                    "players": [{"participantId": 6, "x": 7000, "y": 7000, "level": 8}],
                    "events": [],
                },
                {
                    "timestamp": 10 * 60_000,
                    "players": [{"participantId": 6, "x": 7300, "y": 7200, "level": 9}],
                    "events": [{
                        "type": "CHAMPION_KILL", "timestamp": 605_500,
                        "killerId": 1, "victimId": 6,
                        "position": {"x": 9100, "y": 4300},
                    }],
                },
            ],
        }

        self.assertEqual(death_states_at(replay, 605), {})
        state = death_states_at(replay, 606)[6]
        self.assertEqual(state["position"], {"x": 9100, "y": 4300})
        self.assertTrue(state["deathObserved"])
        self.assertTrue(state["respawnEstimated"])
        self.assertGreater(state["remainingSeconds"], 0)
        self.assertEqual(death_states_at(replay, 700), {})

    def test_respawn_estimate_is_bounded_and_grows_late(self):
        self.assertEqual(estimated_respawn_seconds(1, 5 * 60), 10)
        self.assertEqual(estimated_respawn_seconds(99, 5 * 60), 52)
        self.assertEqual(estimated_respawn_seconds(18, 55 * 60), 78)

    def test_minion_wave_estimate_uses_spawn_cadence(self):
        self.assertEqual(estimated_minion_waves(64), [])
        spawn = estimated_minion_waves(65)
        self.assertEqual(len(spawn), 6)
        self.assertTrue(all(wave["estimated"] for wave in spawn))
        self.assertTrue(all(wave["spawnSecond"] == 65 for wave in spawn))
        moved = estimated_minion_waves(75)
        blue_mid_spawn = next(wave for wave in spawn if wave["teamId"] == 100 and wave["lane"] == "MIDDLE")
        blue_mid_moved = next(wave for wave in moved if wave["teamId"] == 100 and wave["lane"] == "MIDDLE")
        self.assertGreater(blue_mid_moved["x"], blue_mid_spawn["x"])


if __name__ == "__main__":
    unittest.main()
