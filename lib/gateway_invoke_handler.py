"""Register an AgentCore invoke handler that keeps the MCP connection active."""

import json
import math
from typing import Callable

from agent_base import parse_prompt, team_id_from
from fallback import FallbackConfig, build_last_resort
from parsing import parse_commands
from state import summarize_state


GOALKEEPER_EXCLUSION_RADIUS = 14.0


def _is_team_player(player, team_id):
    team_code = player.get("teamCode")
    if isinstance(team_code, str):
        return team_code.strip().lower() == ("home" if team_id == 0 else "away")
    return player.get("teamId") == team_id


def _player_index(player):
    agent_id = player.get("agentId")
    if isinstance(agent_id, str):
        try:
            return int(agent_id.rsplit("_", 1)[-1])
        except ValueError:
            return None
    return player.get("playerId")


def _protect_goalkeeper_space(commands, game_state, team_id, player_id, log):
    """Keep defender MOVE_TO destinations outside the goalkeeper's anchored area."""
    if player_id != 1:
        return commands

    players = game_state.get("players", [])
    goalkeeper = next(
        (
            player for player in players
            if _is_team_player(player, team_id) and _player_index(player) == 0
        ),
        None,
    )
    if goalkeeper is None:
        goal_x = -55.0 if team_id == 0 else 55.0
        keeper_x, keeper_y = goal_x * 0.9, 0.0
    else:
        keeper_position = goalkeeper.get("position", {})
        keeper_x = keeper_position.get("x")
        keeper_y = keeper_position.get("y")
        if not isinstance(keeper_x, (int, float)) or not isinstance(keeper_y, (int, float)):
            log.warn("DEF goalkeeper position is invalid; using its anchored home position.")
            goal_x = -55.0 if team_id == 0 else 55.0
            keeper_x, keeper_y = goal_x * 0.9, 0.0

    adjusted = []
    for command in commands:
        parameters = command.get("parameters", {})
        if (
            command.get("commandType") == "MOVE_TO"
            and isinstance(parameters, dict)
            and isinstance(parameters.get("target_x"), (int, float))
            and not isinstance(parameters.get("target_x"), bool)
            and isinstance(parameters.get("target_y"), (int, float))
            and not isinstance(parameters.get("target_y"), bool)
        ):
            dx = parameters["target_x"] - keeper_x
            dy = parameters["target_y"] - keeper_y
            distance = math.hypot(dx, dy)
            if distance < GOALKEEPER_EXCLUSION_RADIUS:
                if distance == 0:
                    dx = 1.0 if team_id == 0 else -1.0
                    dy = 0.0
                    distance = 1.0
                parameters["target_x"] = round(
                    keeper_x + dx * GOALKEEPER_EXCLUSION_RADIUS / distance, 2
                )
                parameters["target_y"] = round(
                    keeper_y + dy * GOALKEEPER_EXCLUSION_RADIUS / distance, 2
                )
                log.warn(
                    "DEF MOVE_TO adjusted to stay outside the goalkeeper's "
                    f"{GOALKEEPER_EXCLUSION_RADIUS:g}-unit protected area."
                )
        adjusted.append(command)
    return adjusted


def create_gateway_invoke_handler(
    app,
    agent,
    mcp_client,
    my_player_id: int,
    position_label: str,
    fallback_fn: Callable[[dict, int, int], list[dict]],
    fallback_cfg: FallbackConfig,
):
    log = app.logger
    last_resort = build_last_resort(fallback_cfg, my_player_id)

    @app.entrypoint
    async def invoke(payload, context):
        prompt_data = parse_prompt(payload)
        team_id = team_id_from(prompt_data, log, position_label)
        my_players = prompt_data.get("myPlayers", [my_player_id])
        effective_pid = my_players[0] if my_players else my_player_id
        game_state = prompt_data.get("gameState", {})
        try:
            state_summary = summarize_state(
                game_state, team_id, effective_pid, position_label
            )
            tool_context = (
                "\n\nRaw game state for tactical tools: "
                + json.dumps(game_state, separators=(",", ":"))
            )
            log.info(
                f"{position_label} gateway agent invoked for team {team_id}, "
                f"controlling player {effective_pid}"
            )
            with mcp_client:
                response = agent(state_summary + tool_context)
            response_text = str(response)
            commands = parse_commands(response_text, team_id, effective_pid)

            if commands:
                commands = _protect_goalkeeper_space(
                    commands, game_state, team_id, effective_pid, log
                )
                log.info(
                    f"LLM+tools returned {len(commands)} commands: "
                    f"{[command.get('commandType') for command in commands]}"
                )
                yield json.dumps(commands)
            else:
                log.warn(
                    f"LLM parse failed, using fallback. "
                    f"Response: {response_text[:200]}"
                )
                commands = fallback_fn(game_state, team_id, effective_pid)
                commands = _protect_goalkeeper_space(
                    commands, game_state, team_id, effective_pid, log
                )
                yield json.dumps(commands)
        except Exception as error:
            log.error(f"{position_label} gateway agent error: {error}")
            try:
                commands = fallback_fn(game_state, team_id, effective_pid)
                commands = _protect_goalkeeper_space(
                    commands, game_state, team_id, effective_pid, log
                )
                yield json.dumps(commands)
            except Exception as fallback_error:
                log.error(
                    f"{position_label} gateway fallback also failed: {fallback_error}"
                )
                command = dict(last_resort)
                command["teamId"] = team_id
                yield json.dumps([command])

    return invoke
