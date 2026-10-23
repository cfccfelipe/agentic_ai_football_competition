"""Tactical tool: evaluate_shot.

Evaluates shot success probability from a given position, considering
distance to goal, angle, goalkeeper position, and blockers.

Pure function — no AWS, no network. Registered as an MCP tool by the server
and deployable as a Lambda behind AgentCore Gateway.
"""

import math

GOAL_HOME = {"x": -55, "y": 0}  # HOME team's goal
GOAL_AWAY = {"x": 55, "y": 0}   # AWAY team's goal
GOAL_HALF_WIDTH = 5.0


def _distance(p1: dict, p2: dict) -> float:
    return math.sqrt((p1["x"] - p2["x"]) ** 2 + (p1["y"] - p2["y"]) ** 2)


def evaluate_shot(
    shooter_position: dict,
    goalkeeper_position: dict,
    team_side: str = "HOME",
    blocker_positions: list[dict] | None = None,
) -> dict:
    """Return shot success probability and recommended aim/power.

    Args:
        shooter_position: {"x": float, "y": float}
        goalkeeper_position: {"x": float, "y": float} — opponent GK
        team_side: "HOME" or "AWAY" — which goal you attack
        blocker_positions: [{"x","y"}, ...] opponents near the shooting lane

    Returns:
        {"success_probability", "distance_to_goal", "recommended_aim",
         "recommended_power", "should_shoot"}
    """
    blockers = blocker_positions or []
    goal = GOAL_AWAY if team_side == "HOME" else GOAL_HOME

    dist_to_goal = _distance(shooter_position, goal)
    dist_gk_to_goal = _distance(goalkeeper_position, goal)

    angle_to_goal = math.atan2(GOAL_HALF_WIDTH, dist_to_goal)
    angle_factor = min(1.0, angle_to_goal / 0.15)

    distance_factor = max(0.0, 1.0 - (dist_to_goal / 55.0))

    gk_offset = abs(goalkeeper_position["y"])
    gk_factor = min(1.0, gk_offset / 8.0) * 0.3
    gk_dist_factor = min(1.0, dist_gk_to_goal / 15.0) * 0.2

    blocker_penalty = 0.0
    for b in blockers:
        b_dist = _distance(shooter_position, b)
        if b_dist < 10:
            blocker_penalty += (10 - b_dist) / 10.0 * 0.15
    blocker_penalty = min(blocker_penalty, 0.4)

    probability = round(
        max(0.02, min(0.95,
            (distance_factor * 0.45) + (angle_factor * 0.25)
            + gk_factor + gk_dist_factor - blocker_penalty
        )), 2
    )

    if goalkeeper_position["y"] > 1:
        aim = "BL" if shooter_position["y"] > 0 else "BR"
    elif goalkeeper_position["y"] < -1:
        aim = "TL" if shooter_position["y"] > 0 else "TR"
    else:
        aim = "TR" if shooter_position["y"] <= 0 else "TL"

    recommended_power = round(min(1.0, 0.6 + (dist_to_goal / 80.0)), 2)

    return {
        "success_probability": probability,
        "distance_to_goal": round(dist_to_goal, 1),
        "recommended_aim": aim,
        "recommended_power": recommended_power,
        "should_shoot": probability > 0.25,
    }
