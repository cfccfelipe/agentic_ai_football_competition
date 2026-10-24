"""Tactical analysis functions exposed to agents through the MCP gateway."""

import json
import math


FIELD_X = 55


def _request(event):
    body = event.get("body", event)
    if isinstance(body, str):
        body = json.loads(body)
    if not isinstance(body, dict) or not isinstance(body.get("game_state"), dict):
        raise ValueError("game_state must be an object")
    team_id = body.get("team_id")
    if team_id not in (0, 1):
        raise ValueError("team_id must be 0 or 1")
    return body, body["game_state"], team_id


def _position(player):
    position = player.get("position", {})
    if not isinstance(position, dict) or "x" not in position or "y" not in position:
        raise ValueError("Every player must have a position with x and y")
    return {"x": float(position["x"]), "y": float(position["y"])}


def _is_team(player, team_id):
    team_code = player.get("teamCode")
    if isinstance(team_code, str):
        return team_code.strip().lower() == ("home" if team_id == 0 else "away")
    return player.get("teamId") == team_id


def _player_number(player):
    try:
        return int(str(player.get("agentId", "")).rsplit("_", 1)[1])
    except (IndexError, ValueError):
        return player.get("playerId")


def _players(game_state, team_id):
    players = game_state.get("players")
    if not isinstance(players, list):
        raise ValueError("game_state.players must be an array")
    own = [player for player in players if _is_team(player, team_id)]
    opponents = [player for player in players if _is_team(player, 1 - team_id)]
    return own, opponents


def _ball_position(game_state):
    ball = game_state.get("ball", {})
    position = ball.get("position", ball)
    if not isinstance(position, dict) or "x" not in position or "y" not in position:
        raise ValueError("game_state.ball must contain a position with x and y")
    return {"x": float(position["x"]), "y": float(position["y"])}


def _ball_holder(game_state):
    ball = game_state.get("ball", {})
    players = game_state.get("players", [])
    agent_id = ball.get("possessionAgentId")
    if isinstance(agent_id, str):
        matches = [player for player in players if player.get("agentId") == agent_id]
        team_code = ball.get("possessionTeamCode")
        if team_code:
            matches = [
                player for player in matches
                if player.get("teamCode", "").lower() == team_code.lower()
            ]
        team_id = ball.get("possessionTeamId")
        if team_id is not None:
            matches = [player for player in matches if _is_team(player, team_id)]
        return matches[0] if matches else None

    player_id = ball.get("possessionPlayerId")
    if player_id is None:
        return None
    matches = [player for player in players if player.get("playerId") == player_id]
    team_id = ball.get("possessionTeamId")
    if team_id is not None:
        matches = [player for player in matches if player.get("teamId") == team_id]
    return matches[0] if matches else None


def _distance(first, second):
    return math.hypot(first["x"] - second["x"], first["y"] - second["y"])


def _response(result):
    return {"statusCode": 200, "body": json.dumps(result)}


def get_defensive_assignment(event, context=None):
    body, game_state, team_id = _request(event)
    player_id = body.get("player_id")
    own, opponents = _players(game_state, team_id)
    defender = next(
        (player for player in own if _player_number(player) == player_id), None
    )
    if defender is None:
        raise ValueError(f"Player {player_id} was not found on team {team_id}")

    ball = _ball_position(game_state)
    holder = _ball_holder(game_state)
    goal_x = -FIELD_X if team_id == 0 else FIELD_X
    threats = []
    for opponent in opponents:
        position = _position(opponent)
        goal_distance = _distance(position, {"x": goal_x, "y": 0})
        ball_distance = _distance(position, ball)
        has_ball = opponent is holder
        score = (
            max(0.0, 1.0 - goal_distance / (2 * FIELD_X))
            + (0.3 if ball_distance < 10 else 0.15 if ball_distance < 20 else 0)
            + (0.4 if has_ball else 0)
        )
        threats.append({
            "player_id": _player_number(opponent),
            "threat_score": round(score, 2),
            "distance_to_goal": round(goal_distance, 1),
            "distance_to_defender": round(_distance(position, _position(defender)), 1),
            "has_ball": has_ball,
            "recommended_tightness": "TIGHT" if score > 0.7 else "LOOSE",
        })
    threats.sort(key=lambda threat: threat["threat_score"], reverse=True)
    target = threats[0] if threats else None
    return _response({
        "threats": threats,
        "recommended_mark": target,
        "action": "MARK" if target and target["distance_to_defender"] < 30 else "INTERCEPT",
    })


def calculate_pass_options(event, context=None):
    body, game_state, team_id = _request(event)
    player_id = body.get("player_id")
    own, opponents = _players(game_state, team_id)
    passer = next(
        (player for player in own if _player_number(player) == player_id), None
    )
    if passer is None:
        raise ValueError(f"Player {player_id} was not found on team {team_id}")

    start = _position(passer)
    options = []
    for teammate in own:
        if teammate is passer:
            continue
        end = _position(teammate)
        distance = _distance(start, end)
        nearest_opponent = min(
            (_distance(_position(opponent), end) for opponent in opponents),
            default=FIELD_X * 2,
        )
        success = max(0.0, min(1.0, 1.0 - distance / 110 + nearest_opponent / 100))
        options.append({
            "target_player_id": _player_number(teammate),
            "distance": round(distance, 1),
            "success_probability": round(success, 2),
            "type": "THROUGH" if end["x"] * (1 if team_id == 0 else -1) >
                    start["x"] * (1 if team_id == 0 else -1) else "GROUND",
        })
    options.sort(key=lambda option: option["success_probability"], reverse=True)
    return _response({"pass_options": options})


def find_open_space(event, context=None):
    body, game_state, team_id = _request(event)
    zone = body.get("zone", "midfield")
    zone_ranges = {
        "defense": (-FIELD_X, -10),
        "midfield": (-25, 25),
        "attack": (10, FIELD_X),
    }
    if zone not in zone_ranges:
        raise ValueError("zone must be defense, midfield, or attack")
    own, opponents = _players(game_state, team_id)
    direction = 1 if team_id == 0 else -1
    low_x, high_x = zone_ranges[zone]
    if direction < 0:
        low_x, high_x = -high_x, -low_x
    candidates = [
        {"x": x, "y": y}
        for x in range(low_x, high_x + 1, 5)
        for y in range(-30, 31, 5)
    ]
    occupied = [_position(player) for player in own + opponents]
    best = max(
        candidates,
        key=lambda point: min(
            (_distance(point, opponent) for opponent in occupied),
            default=FIELD_X,
        ),
    )
    return _response({"target": best, "zone": zone})


def evaluate_shot(event, context=None):
    body, game_state, team_id = _request(event)
    player_id = body.get("player_id")
    own, opponents = _players(game_state, team_id)
    shooter = next(
        (player for player in own if _player_number(player) == player_id), None
    )
    if shooter is None:
        raise ValueError(f"Player {player_id} was not found on team {team_id}")
    position = _position(shooter)
    goal = {"x": FIELD_X if team_id == 0 else -FIELD_X, "y": 0}
    distance = _distance(position, goal)
    nearest_defender = min(
        (_distance(position, _position(opponent)) for opponent in opponents),
        default=FIELD_X,
    )
    probability = max(0.0, min(1.0, 1.0 - distance / 100 + nearest_defender / 100))
    return _response({
        "distance_to_goal": round(distance, 1),
        "nearest_defender_distance": round(nearest_defender, 1),
        "shot_probability": round(probability, 2),
        "recommended_aim": "TL" if position["y"] <= 0 else "TR",
    })
