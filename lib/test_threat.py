import copy

from test_helpers import GAME_STATE
from threat import assess_threats


def test_free_ball_does_not_mark_nearby_opponents_as_carriers():
    game_state = copy.deepcopy(GAME_STATE)
    game_state["ball"]["isFree"] = True
    game_state["ball"]["possessionAgentId"] = None
    game_state["ball"]["position"] = {"x": 25, "y": 10}
    game_state["players"][7]["position"] = {"x": 25, "y": 10}
    game_state["players"][8]["position"] = {"x": 26, "y": 10}

    threats = assess_threats(game_state, 0)

    assert threats
    assert not any("has ball" in threat.label for threat in threats)


def test_only_the_confirmed_opponent_holder_is_reported_as_carrier():
    game_state = copy.deepcopy(GAME_STATE)
    away_player_one = game_state["players"].pop(6)
    game_state["players"].insert(0, away_player_one)
    game_state["ball"]["isFree"] = False
    game_state["ball"]["possessionAgentId"] = "agentId_1"

    threats = assess_threats(game_state, 0)

    carriers = [threat.player_id for threat in threats if "has ball" in threat.label]
    assert carriers == [1]


if __name__ == "__main__":
    test_free_ball_does_not_mark_nearby_opponents_as_carriers()
    test_only_the_confirmed_opponent_holder_is_reported_as_carrier()
    print("2 threat tests passed")
