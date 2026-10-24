import copy

import pytest

from command_safety import enforce_command_constraints
from stamina import UNKNOWN_STAMINA, normalize_stamina, stamina_context
from state import summarize_state
from test_helpers import GAME_STATE


@pytest.mark.parametrize(
    ("command", "team_id", "player_id", "position"),
    [
        (
            {
                "commandType": "PASS",
                "parameters": {"target_player_id": 0, "type": "GROUND"},
            },
            0,
            1,
            "DEF",
        ),
        (
            {
                "commandType": "GK_DISTRIBUTE",
                "parameters": {"target_player_id": 1, "method": "THROW"},
            },
            0,
            0,
            "GK",
        ),
        (
            {"commandType": "PRESS_BALL", "parameters": {"intensity": 0.8}},
            0,
            1,
            "DEF",
        ),
        (
            {
                "commandType": "MARK",
                "parameters": {"target_player_id": 1, "tightness": "TIGHT"},
            },
            0,
            1,
            "DEF",
        ),
        (
            {
                "commandType": "MARK",
                "parameters": {"target_player_id": 1, "tightness": "TIGHT"},
            },
            0,
            3,
            "FWD1",
        ),
    ],
)
def test_tactical_decisions_are_passed_through_to_game_engine(
    command, team_id, player_id, position
):
    commands, violations = enforce_command_constraints(
        [command], GAME_STATE, team_id, player_id, position
    )

    assert not violations
    assert commands == [command]


def test_move_is_clamped_to_field_boundaries_without_changing_model_choice():
    command = {
        "commandType": "MOVE_TO",
        "playerId": 1,
        "parameters": {
            "target_x": 55,
            "target_y": -35,
            "sprint": True,
        },
    }

    commands, violations = enforce_command_constraints(
        [command], GAME_STATE, 0, 1, "DEF"
    )

    assert not violations
    assert commands[0]["parameters"] == {
        "target_x": 50.0,
        "target_y": -30.0,
        "sprint": True,
    }


def test_invalid_stamina_is_available_in_prompt_but_does_not_rewrite_command():
    game_state = copy.deepcopy(GAME_STATE)
    game_state["players"][1]["stamina"] = None
    command = {
        "commandType": "MOVE_TO",
        "playerId": 1,
        "parameters": {"target_x": -22, "target_y": 0, "sprint": True},
    }

    commands, violations = enforce_command_constraints(
        [command], game_state, 0, 1, "DEF"
    )

    assert not violations
    assert commands[0]["parameters"]["sprint"] is True
    summary = summarize_state(game_state, 0, 1, "DEF")
    assert "stamina is missing or invalid" in summary


def test_invalid_stamina_normalization_remains_safe():
    assert normalize_stamina(75) == (0.75, "stamina was supplied as a percentage")
    normalized, warning = normalize_stamina(None)
    assert normalized == UNKNOWN_STAMINA
    assert warning
    context = stamina_context(None, 300)
    assert context.current == UNKNOWN_STAMINA
    assert context.input_warning


def test_only_one_command_is_accepted_per_tick():
    commands, violations = enforce_command_constraints(
        [
            {"commandType": "MOVE_TO", "parameters": {}},
            {"commandType": "INTERCEPT", "parameters": {}},
        ],
        GAME_STATE,
        0,
        1,
        "DEF",
    )

    assert commands == []
    assert violations == ["expected exactly one command"]


def test_non_object_parameters_are_rejected_as_invalid_command_shape():
    commands, violations = enforce_command_constraints(
        [{"commandType": "PASS", "parameters": None}],
        GAME_STATE,
        0,
        1,
        "DEF",
    )

    assert commands == []
    assert violations == ["command parameters must be an object"]
