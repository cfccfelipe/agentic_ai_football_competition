"""Tactical tool: get_defensive_assignment.

Ranks opponent players by threat level and recommends which opponent a
defender should mark, based on proximity to goal, ball possession, and
positioning.

Pure function — no AWS, no network. Registered as an MCP tool by the server
and deployable as a Lambda behind AgentCore Gateway.
"""

import math

GOAL_HOME = {"x": -55, "y": 0}
GOAL_AWAY = {"x": 55, "y": 0}


def _distance(p1: dict, p2: dict) -> float:
    return math.sqrt((p1["x"] - p2["x"]) ** 2 + (p1["y"] - p2["y"]) ** 2)


def get_defensive_assignment(
    opponents: list[dict],
    ball: dict,
    team_side: str = "HOME",
    my_position: dict | None = None,
) -> dict:
    """Rank opponent threats and recommend a marking target.

    Args:
        opponents: [{"player_id": int, "position": {"x","y"}}, ...]
        ball: {"x","y","possession_player_id"}
        team_side: "HOME" (defends -x) or "AWAY" (defends +x)
        my_position: {"x","y"} — current position

    Returns:
        {"threats": [...], "recommended_mark": {...}|None, "action": "MARK"|"INTERCEPT"}
    """
    my_position = my_position or {"x": 0, "y": 0}
    my_goal = GOAL_HOME if team_side == "HOME" else GOAL_AWAY

    threats = []
    for opp in opponents:
        pos = opp["position"]
        dist_to_goal = _distance(pos, my_goal)
        dist_to_ball = _distance(pos, {"x": ball["x"], "y": ball["y"]})
        dist_to_me = _distance(pos, my_position)

        goal_threat = max(0, 1.0 - (dist_to_goal / 80.0))
        ball_bonus = 0.3 if dist_to_ball < 10 else (0.15 if dist_to_ball < 20 else 0)
        has_ball = opp.get("player_id") == ball.get("possession_player_id")
        possession_bonus = 0.4 if has_ball else 0.0

        threat_score = round(goal_threat + ball_bonus + possession_bonus, 2)

        threats.append({
            "player_id": opp["player_id"],
            "threat_score": threat_score,
            "distance_to_goal": round(dist_to_goal, 1),
            "distance_to_me": round(dist_to_me, 1),
            "has_ball": has_ball,
            "recommended_tightness": "TIGHT" if threat_score > 0.7 else "LOOSE",
        })

    threats.sort(key=lambda x: x["threat_score"], reverse=True)
    top_threat = threats[0] if threats else None

    return {
        "threats": threats,
        "recommended_mark": top_threat,
        "action": "MARK" if top_threat and top_threat["distance_to_me"] < 30 else "INTERCEPT",
    }
