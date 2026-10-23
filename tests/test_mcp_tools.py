"""Tests for the four tactical scripts in plugins/general/scripts/.

Pure functions — no AWS, no network. Each returns a dict.
"""

from calculate_pass_options import calculate_pass_options
from evaluate_shot import evaluate_shot
from find_open_space import find_open_space
from get_defensive_assignment import get_defensive_assignment


def test_pass_options_ranked_by_success():
    result = calculate_pass_options(
        passer_position={"x": 0, "y": 0},
        teammates=[
            {"player_id": 1, "position": {"x": 5, "y": 0}},
            {"player_id": 2, "position": {"x": 40, "y": 20}},
        ],
        opponents=[{"player_id": 3, "position": {"x": 20, "y": 10}}],
    )
    opts = result["pass_options"]
    assert len(opts) == 2
    # Sorted descending by success probability.
    assert opts[0]["success_probability"] >= opts[1]["success_probability"]
    assert all(0.0 <= o["success_probability"] <= 1.0 for o in opts)


def test_evaluate_shot_close_range_is_high():
    close = evaluate_shot({"x": 50, "y": 0}, {"x": 55, "y": 0}, team_side="HOME")
    far = evaluate_shot({"x": 0, "y": 0}, {"x": 55, "y": 0}, team_side="HOME")
    assert close["success_probability"] > far["success_probability"]
    assert close["recommended_aim"] in ("TL", "TR", "BL", "BR", "CENTER")
    assert 0.0 <= close["recommended_power"] <= 1.0


def test_evaluate_shot_should_shoot_flag():
    r = evaluate_shot({"x": 52, "y": 1}, {"x": 55, "y": 6}, team_side="HOME")
    assert r["should_shoot"] == (r["success_probability"] > 0.25)


def test_find_open_space_within_zone():
    r = find_open_space(
        opponent_positions=[{"x": 30, "y": 0}, {"x": 40, "y": 10}],
        zone="attack",
        team_side="HOME",
        my_position={"x": 20, "y": 0},
    )
    assert r["zone"] == "attack"
    # Attack zone for HOME is x in [15, 52].
    assert 15 <= r["recommended_position"]["x"] <= 52
    assert r["nearest_opponent_distance"] >= 0


def test_defensive_assignment_marks_top_threat():
    r = get_defensive_assignment(
        opponents=[
            {"player_id": 3, "position": {"x": -40, "y": 0}},   # near HOME goal
            {"player_id": 4, "position": {"x": 20, "y": 10}},
        ],
        ball={"x": -40, "y": 0, "possession_player_id": 3},
        team_side="HOME",
        my_position={"x": -45, "y": 0},
    )
    assert r["recommended_mark"]["player_id"] == 3
    assert r["threats"][0]["threat_score"] >= r["threats"][1]["threat_score"]
    assert r["action"] in ("MARK", "INTERCEPT")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
    print(f"{len(fns)} tests passed")
