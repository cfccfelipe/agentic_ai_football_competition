"""P1 guard: fallback SHOOT aim is SITUATIONAL, not a blind fixed corner.

The deterministic fallback used to hardcode FWD1->TR, FWD2->BL, MID->TR. Those
corners ignored both the shooter's position and the attacking direction, so a
fallback shot was aimed at a fixed corner regardless of where the shooter stood
or which goal they attacked.

These tests prove the fallback now picks the corner from the shooter's y (a
shooter below goal-centre aims high, above aims low) while keeping FWD1/FWD2's
distinct flanks, and that it works for BOTH HOME (opp goal +55) and AWAY (opp
goal -55).
"""

import pytest

import fallback

VALID_CORNERS = {"TL", "TR", "BL", "BR"}

# team_id -> opponent goal x (from get_goal_positions)
_OPP_GOAL_X = {0: 55.0, 1: -55.0}


def _state_with_shooter(team_id: int, shooter_id: int, shooter_x: float, shooter_y: float) -> dict:
    """A minimal game state where exactly one player (ours) holds the ball.

    Only our team's shooter is present, so _resolve_holder is unambiguous and
    holder_is_me() is true for the given shooter — isolating the aim logic from
    the agentId-non-uniqueness handled elsewhere.
    """
    team_code = "home" if team_id == 0 else "away"
    agent = f"agentId_{shooter_id}"
    return {
        "ball": {
            "position": {"x": shooter_x, "y": shooter_y, "z": 0},
            "velocity": {"x": 0, "y": 0, "z": 0},
            "isFree": False,
            "possessionAgentId": agent,
        },
        "players": [
            {
                "agentId": agent,
                "teamCode": team_code,
                "position": {"x": shooter_x, "y": shooter_y},
                "velocity": {"x": 0, "y": 0},
                "stamina": 0.9,
            }
        ],
    }


def _shoot_cmd(cfg, team_id, shooter_id, shooter_y):
    """Run the fallback for a shooter in range and return the SHOOT command."""
    opp_goal_x = _OPP_GOAL_X[team_id]
    # Place the shooter well inside shoot_threshold of the opponent goal.
    shooter_x = opp_goal_x - 5 if team_id == 0 else opp_goal_x + 5
    state = _state_with_shooter(team_id, shooter_id, shooter_x, shooter_y)
    cmds = fallback.build_fallback(cfg)(state, team_id, shooter_id)
    assert len(cmds) == 1
    cmd = cmds[0]
    assert cmd["commandType"] == "SHOOT"
    return cmd


@pytest.mark.parametrize("team_id", [0, 1])
@pytest.mark.parametrize(
    "cfg, shooter_id",
    [
        (fallback.FWD1_CONFIG, 3),
        (fallback.FWD2_CONFIG, 4),
        (fallback.MID_CONFIG, 2),
    ],
)
def test_fallback_shoot_aims_at_a_valid_corner_home_and_away(cfg, shooter_id, team_id):
    cmd = _shoot_cmd(cfg, team_id, shooter_id, shooter_y=-5)
    assert cmd["parameters"]["aim_location"] in VALID_CORNERS


@pytest.mark.parametrize("team_id", [0, 1])
@pytest.mark.parametrize(
    "cfg, shooter_id",
    [
        (fallback.FWD1_CONFIG, 3),
        (fallback.FWD2_CONFIG, 4),
        (fallback.MID_CONFIG, 2),
    ],
)
def test_fallback_aim_is_situational_not_constant(cfg, shooter_id, team_id):
    # Shooter below goal centre -> TOP corner; above centre -> BOTTOM corner.
    low = _shoot_cmd(cfg, team_id, shooter_id, shooter_y=-10)["parameters"]["aim_location"]
    high = _shoot_cmd(cfg, team_id, shooter_id, shooter_y=10)["parameters"]["aim_location"]
    assert low.startswith("T"), f"{cfg} y<0 should aim top, got {low}"
    assert high.startswith("B"), f"{cfg} y>0 should aim bottom, got {high}"
    # Proves it is not a single fixed corner for the position.
    assert low != high


@pytest.mark.parametrize("team_id", [0, 1])
def test_fwd1_and_fwd2_keep_distinct_flanks(team_id):
    # Same y, same direction: FWD1 and FWD2 still favour opposite goal halves.
    fwd1 = _shoot_cmd(fallback.FWD1_CONFIG, team_id, 3, shooter_y=-5)["parameters"]["aim_location"]
    fwd2 = _shoot_cmd(fallback.FWD2_CONFIG, team_id, 4, shooter_y=-5)["parameters"]["aim_location"]
    assert fwd1.endswith("L"), f"FWD1 should favour the left half, got {fwd1}"
    assert fwd2.endswith("R"), f"FWD2 should favour the right half, got {fwd2}"
    assert fwd1 != fwd2


@pytest.mark.parametrize("team_id", [0, 1])
def test_merged_fwd_config_shoots_situationally(team_id):
    # The single merged forward config still picks a situational corner.
    low = _shoot_cmd(fallback.FWD_CONFIG, team_id, 3, shooter_y=-8)["parameters"]["aim_location"]
    high = _shoot_cmd(fallback.FWD_CONFIG, team_id, 3, shooter_y=8)["parameters"]["aim_location"]
    assert low in VALID_CORNERS and high in VALID_CORNERS
    assert low.startswith("T") and high.startswith("B")


# --- item 17: DEF may SHOOT in fallback when close to the opponent goal ------


@pytest.mark.parametrize("team_id", [0, 1])
def test_def_fallback_shoots_when_close_to_goal(team_id):
    # A defender carrying the ball into a close chance SHOULD shoot (the DEF
    # goal that won us a match). Situational aim, valid corner.
    cmd = _shoot_cmd(fallback.DEF_CONFIG, team_id, 1, shooter_y=-5)
    assert cmd["commandType"] == "SHOOT"
    assert cmd["parameters"]["aim_location"] in VALID_CORNERS


def test_def_fallback_builds_out_when_far_and_never_to_gk():
    # Far from goal, DEF passes forward (builds out) and NEVER recycles to the
    # GK (pass_exclude_ids=[0]).
    team_id = 0
    # Defender deep in own half, not near opponent goal; add teammates to pass to.
    state = {
        "ball": {
            "position": {"x": -40, "y": 0, "z": 0},
            "velocity": {"x": 0, "y": 0, "z": 0},
            "isFree": False,
            "possessionAgentId": "agentId_1",
        },
        "players": [
            {"agentId": "agentId_0", "teamCode": "home", "position": {"x": -52, "y": 0}},
            {"agentId": "agentId_1", "teamCode": "home", "position": {"x": -40, "y": 0}},
            {"agentId": "agentId_2", "teamCode": "home", "position": {"x": -10, "y": 5}},
            {"agentId": "agentId_3", "teamCode": "home", "position": {"x": 20, "y": -8}},
        ],
    }
    cmds = fallback.build_fallback(fallback.DEF_CONFIG)(state, team_id, 1)
    assert len(cmds) == 1
    cmd = cmds[0]
    assert cmd["commandType"] == "PASS"
    assert cmd["parameters"]["target_player_id"] != 0  # never back to the GK
