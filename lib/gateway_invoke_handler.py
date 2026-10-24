"""Register an AgentCore invoke handler that keeps the MCP connection active."""

import json
import math
from threading import Lock
from datetime import timedelta
from typing import Callable
from uuid import uuid4

from agent_base import parse_prompt, team_id_from
from command_safety import enforce_command_constraints
from fallback import FallbackConfig, build_last_resort
from parsing import parse_commands
from state import holder_is_me, summarize_state


GOALKEEPER_EXCLUSION_RADIUS = 14.0
MAX_TOOL_TURNS = 1
MAX_TOOL_CALLS_PER_TICK = 2
TOOL_TIMEOUT_SECONDS = 2
DEFENDER_X_LIMIT = 50.0
DEFENDER_Y_LIMIT = 30.0

DEFENSIVE_ASSIGNMENT_TOOL = (
    "get-defensive-assignment___get_defensive_assignment"
)
PASS_OPTIONS_TOOL = "calculate-pass-options___calculate_pass_options"


def _call_tactical_tool(mcp_client, name, arguments):
    result = mcp_client.call_tool_sync(
        uuid4().hex,
        name,
        arguments,
        read_timeout_seconds=timedelta(seconds=TOOL_TIMEOUT_SECONDS),
    )
    if result.get("status") != "success":
        raise RuntimeError(f"MCP tool {name} returned status {result.get('status')}")

    structured = result.get("structuredContent")
    if isinstance(structured, dict):
        return structured

    for item in result.get("content", []):
        text = item.get("text") if isinstance(item, dict) else None
        if not text:
            continue
        response = json.loads(text)
        if isinstance(response, dict) and "statusCode" in response:
            if response["statusCode"] != 200:
                raise RuntimeError(
                    f"MCP tool {name} returned HTTP {response['statusCode']}"
                )
            response = response.get("body")
        if isinstance(response, str):
            response = json.loads(response)
        if isinstance(response, dict):
            return response

    raise RuntimeError(f"MCP tool {name} returned no JSON result")


def _tactical_tool_context(mcp_client, game_state, team_id, player_id, log):
    results = {}
    failed_tools = []
    try:
        results["defensive_assignment"] = _call_tactical_tool(
            mcp_client,
            DEFENSIVE_ASSIGNMENT_TOOL,
            {
                "game_state": game_state,
                "team_id": team_id,
                "player_id": player_id,
            },
        )
    except (RuntimeError, ValueError, TimeoutError, OSError) as error:
        failed_tools.append("get_defensive_assignment")
        results["defensive_assignment_error"] = str(error)
        log.error(f"DEF tactical tool get_defensive_assignment failed: {error}")

    if holder_is_me(
        game_state.get("ball", {}),
        game_state.get("players", []),
        team_id,
        player_id,
    ):
        if len(results) >= MAX_TOOL_CALLS_PER_TICK:
            raise RuntimeError("Tactical tool call limit reached")
        try:
            results["pass_options"] = _call_tactical_tool(
                mcp_client,
                PASS_OPTIONS_TOOL,
                {
                    "game_state": game_state,
                    "team_id": team_id,
                    "player_id": player_id,
                },
            )
        except (RuntimeError, ValueError, TimeoutError, OSError) as error:
            failed_tools.append("calculate_pass_options")
            results["pass_options_error"] = str(error)
            log.error(f"DEF tactical tool calculate_pass_options failed: {error}")

    assignment = results.get("defensive_assignment")
    if isinstance(assignment, dict):
        target = assignment.get("recommended_mark")
        target_id = target.get("player_id") if isinstance(target, dict) else None
        threats = assignment.get("threats", [])
        log.info(
            "DEF defensive-assignment result: "
            f"action={assignment.get('action')}, target={target_id}, "
            f"threats={len(threats) if isinstance(threats, list) else 'invalid'}"
        )
        if assignment.get("warning"):
            log.warn(f"DEF defensive-assignment warning: {assignment['warning']}")

    pass_result = results.get("pass_options")
    if isinstance(pass_result, dict):
        options = pass_result.get("pass_options", [])
        best = options[0] if isinstance(options, list) and options else None
        log.info(
            "DEF pass-options result: "
            f"count={len(options) if isinstance(options, list) else 'invalid'}, "
            f"best_target={best.get('target_player_id') if isinstance(best, dict) else None}, "
            f"best_progress={best.get('progress') if isinstance(best, dict) else None}"
        )
    guidance = []
    assignment = results.get("defensive_assignment")
    recommended_mark = (
        assignment.get("recommended_mark")
        if isinstance(assignment, dict)
        else None
    )
    if isinstance(recommended_mark, dict):
        target_id = recommended_mark.get("player_id")
        if isinstance(target_id, int) and not isinstance(target_id, bool):
            guidance.append(
                f"For MARK, prefer recommended opponent player {target_id} "
                "unless the game state makes that target invalid."
            )

    pass_result = results.get("pass_options")
    options = (
        pass_result.get("pass_options", [])
        if isinstance(pass_result, dict)
        else []
    )
    safe_forward = next(
        (
            option for option in options
            if isinstance(option, dict) and option.get("safe_forward") is True
        ),
        None,
    ) if isinstance(options, list) else None
    if isinstance(safe_forward, dict):
        guidance.append(
            "If passing, prefer the safe forward option to player "
            f"{safe_forward.get('target_player_id')} "
            f"(type={safe_forward.get('type')})."
        )
    guidance_text = (
        "\nMANDATORY TOOL GUIDANCE: " + " ".join(guidance)
        if guidance else ""
    )
    return (
        guidance_text
        + "\n\nTactical analysis (already computed; use these results, do not call tools): "
        + json.dumps(results, separators=(",", ":")),
        len(results) - len(failed_tools),
        failed_tools,
        results,
    )


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
                safe_x = round(
                    keeper_x + dx * GOALKEEPER_EXCLUSION_RADIUS / distance, 2
                )
                safe_y = round(
                    keeper_y + dy * GOALKEEPER_EXCLUSION_RADIUS / distance, 2
                )
                safe_x = max(-DEFENDER_X_LIMIT, min(DEFENDER_X_LIMIT, safe_x))
                safe_y = max(-DEFENDER_Y_LIMIT, min(DEFENDER_Y_LIMIT, safe_y))
                if math.hypot(safe_x - keeper_x, safe_y - keeper_y) < GOALKEEPER_EXCLUSION_RADIUS:
                    inward_x = keeper_x + (
                        GOALKEEPER_EXCLUSION_RADIUS
                        if team_id == 0
                        else -GOALKEEPER_EXCLUSION_RADIUS
                    )
                    if -DEFENDER_X_LIMIT <= inward_x <= DEFENDER_X_LIMIT:
                        safe_x = round(inward_x, 2)
                        safe_y = max(
                            -DEFENDER_Y_LIMIT,
                            min(DEFENDER_Y_LIMIT, keeper_y),
                        )
                    else:
                        inward_y = keeper_y + (
                            GOALKEEPER_EXCLUSION_RADIUS
                            if parameters["target_y"] >= keeper_y
                            else -GOALKEEPER_EXCLUSION_RADIUS
                        )
                        safe_x = max(
                            -DEFENDER_X_LIMIT,
                            min(DEFENDER_X_LIMIT, keeper_x),
                        )
                        safe_y = max(
                            -DEFENDER_Y_LIMIT,
                            min(DEFENDER_Y_LIMIT, inward_y),
                        )
                parameters["target_x"] = safe_x
                parameters["target_y"] = safe_y
                log.warn(
                    "DEF MOVE_TO adjusted to stay outside the goalkeeper's "
                    f"{GOALKEEPER_EXCLUSION_RADIUS:g}-unit protected area."
                )
        adjusted.append(command)
    return adjusted


def _keep_defender_off_boundaries(commands, player_id, log):
    if player_id != 1:
        return commands

    for command in commands:
        parameters = command.get("parameters", {})
        if command.get("commandType") != "MOVE_TO" or not isinstance(parameters, dict):
            continue
        target_x = parameters.get("target_x")
        target_y = parameters.get("target_y")
        if (
            not isinstance(target_x, (int, float))
            or isinstance(target_x, bool)
            or not isinstance(target_y, (int, float))
            or isinstance(target_y, bool)
        ):
            continue
        safe_x = max(-DEFENDER_X_LIMIT, min(DEFENDER_X_LIMIT, target_x))
        safe_y = max(-DEFENDER_Y_LIMIT, min(DEFENDER_Y_LIMIT, target_y))
        if safe_x != target_x or safe_y != target_y:
            parameters["target_x"] = safe_x
            parameters["target_y"] = safe_y
            log.warn("DEF MOVE_TO adjusted to stay clear of the field boundaries.")
    return commands


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
    agent_lock = Lock()

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
            log.info(
                f"{position_label} gateway agent invoked for team {team_id}, "
                f"controlling player {effective_pid}"
            )
            # Every tick includes the complete game state, so prior turns are
            # stale context and can cause the model to echo earlier commands.
            with agent_lock:
                messages = getattr(agent, "messages", None)
                if isinstance(messages, list):
                    messages.clear()
                with mcp_client:
                    (
                        tool_context,
                        tool_call_count,
                        failed_tools,
                        tool_results,
                    ) = _tactical_tool_context(
                        mcp_client, game_state, team_id, effective_pid, log
                    )
                    log.info(
                        f"{position_label} tactical MCP calls: "
                        f"{tool_call_count} succeeded, {len(failed_tools)} failed"
                    )
                    response = agent(
                        state_summary + tool_context,
                        limits={"turns": MAX_TOOL_TURNS},
                    )
            response_text = str(response)
            commands = parse_commands(response_text, team_id, effective_pid)
            commands, violations = enforce_command_constraints(
                commands, game_state, team_id, effective_pid, position_label, log
            )
            if violations:
                log.warn(
                    f"{position_label} rejected unsafe model command: "
                    + "; ".join(violations)
                )

            if commands:
                commands = _keep_defender_off_boundaries(
                    commands, effective_pid, log
                )
                commands = _protect_goalkeeper_space(
                    commands, game_state, team_id, effective_pid, log
                )
                log.info(
                    f"LLM+tools returned {len(commands)} commands: "
                    f"{[(command.get('commandType'), command.get('parameters', {}).get('target_player_id')) for command in commands]}"
                )
                yield json.dumps(commands)
            else:
                log.warn(
                    f"{position_label} produced no safe command; using fallback. "
                    f"Response: {response_text[:200]}"
                )
                commands = fallback_fn(game_state, team_id, effective_pid)
                commands, violations = enforce_command_constraints(
                    commands, game_state, team_id, effective_pid, position_label, log
                )
                if violations:
                    log.error(
                        f"{position_label} fallback violated command constraints: "
                        + "; ".join(violations)
                    )
                    command = dict(last_resort)
                    command["teamId"] = team_id
                    yield json.dumps([command])
                    return
                commands = _keep_defender_off_boundaries(
                    commands, effective_pid, log
                )
                commands = _protect_goalkeeper_space(
                    commands, game_state, team_id, effective_pid, log
                )
                yield json.dumps(commands)
        except Exception as error:
            log.error(f"{position_label} gateway agent error: {error}")
            try:
                commands = fallback_fn(game_state, team_id, effective_pid)
                commands, violations = enforce_command_constraints(
                    commands, game_state, team_id, effective_pid, position_label, log
                )
                if violations:
                    log.error(
                        f"{position_label} fallback violated command constraints: "
                        + "; ".join(violations)
                    )
                    command = dict(last_resort)
                    command["teamId"] = team_id
                    yield json.dumps([command])
                    return
                commands = _keep_defender_off_boundaries(
                    commands, effective_pid, log
                )
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
