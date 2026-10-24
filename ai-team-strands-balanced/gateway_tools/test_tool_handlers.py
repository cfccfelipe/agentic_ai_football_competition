import json
import unittest

from tool_handlers import (
    calculate_pass_options,
    evaluate_shot,
    find_open_space,
    get_defensive_assignment,
)


GAME_STATE = {
    "ball": {
        "position": {"x": 2, "y": 1},
        "possessionAgentId": "agentId_2",
    },
    "players": [
        {"agentId": "agentId_0", "teamCode": "home", "position": {"x": -50, "y": 0}},
        {"agentId": "agentId_1", "teamCode": "home", "position": {"x": -10, "y": 2}},
        {"agentId": "agentId_2", "teamCode": "home", "position": {"x": 1, "y": 1}},
        {"agentId": "agentId_3", "teamCode": "home", "position": {"x": 20, "y": -4}},
        {"agentId": "agentId_4", "teamCode": "home", "position": {"x": 22, "y": 5}},
        {"agentId": "agentId_0", "teamCode": "away", "position": {"x": 50, "y": 0}},
        {"agentId": "agentId_1", "teamCode": "away", "position": {"x": -20, "y": 2}},
        {"agentId": "agentId_2", "teamCode": "away", "position": {"x": 4, "y": 1}},
        {"agentId": "agentId_3", "teamCode": "away", "position": {"x": 30, "y": -10}},
        {"agentId": "agentId_4", "teamCode": "away", "position": {"x": 35, "y": 5}},
    ],
}


def result(handler, **arguments):
    response = handler({"game_state": GAME_STATE, "team_id": 0, **arguments})
    return json.loads(response["body"])


class TacticalToolTests(unittest.TestCase):
    def test_defensive_assignment_ranks_opponent_with_ball(self):
        state = dict(GAME_STATE)
        state["players"] = list(GAME_STATE["players"])
        away_carrier = next(
            player for player in state["players"]
            if player["teamCode"] == "away" and player["agentId"] == "agentId_2"
        )
        state["players"].remove(away_carrier)
        home_carrier = next(
            player for player in state["players"]
            if player["teamCode"] == "home" and player["agentId"] == "agentId_2"
        )
        state["players"].insert(state["players"].index(home_carrier), away_carrier)
        assignment = json.loads(get_defensive_assignment({
            "game_state": state, "team_id": 0, "player_id": 1
        })["body"])
        carrier = next(
            threat for threat in assignment["threats"] if threat["player_id"] == 2
        )
        self.assertTrue(carrier["has_ball"])
        self.assertEqual(assignment["recommended_mark"]["player_id"], 2)

    def test_pass_options_exclude_passer_and_rank_options(self):
        options = result(calculate_pass_options, player_id=1)["pass_options"]
        self.assertEqual(len(options), 4)
        self.assertNotIn(1, [option["target_player_id"] for option in options])
        self.assertEqual(
            options,
            sorted(options, key=lambda option: option["success_probability"], reverse=True),
        )

    def test_find_open_space_returns_field_point(self):
        target = result(find_open_space, zone="defense")["target"]
        self.assertLessEqual(-55, target["x"])
        self.assertLessEqual(target["x"], -10)
        self.assertLessEqual(abs(target["y"]), 30)

    def test_evaluate_shot_returns_probability(self):
        shot = result(evaluate_shot, player_id=3)
        self.assertGreaterEqual(shot["shot_probability"], 0)
        self.assertLessEqual(shot["shot_probability"], 1)


if __name__ == "__main__":
    unittest.main()
