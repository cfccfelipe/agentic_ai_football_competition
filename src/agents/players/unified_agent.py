"""Unified agent factory + invoke handler.

All five position agents share this. The only thing that differs between them
is MY_PLAYER_ID, which the thin main.py passes in. Everything else — the
dynamic prompt, the strategy choice, the MCP tools, the fallback — is identical.

The system prompt is built *inside* invoke(), not at module load, because it
depends on the strategy chosen that tick. Tools are fetched once at startup and
reused; only the Agent object is rebuilt per tick with the fresh prompt.
"""

from __future__ import annotations

import json
import os
import sys

# --- commons/ bootstrap (shared kernel: state, parsing, fallback, agent_base, _bootstrap) ---
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "commons"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "commons"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "commons"))
from _bootstrap import setup_commons_path  # noqa: E402
setup_commons_path(__file__)

# --- src/ root so plugins + sibling modules resolve ---
_SRC_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _SRC_ROOT not in sys.path:
    sys.path.insert(0, _SRC_ROOT)
sys.path.insert(0, os.path.dirname(__file__))

from strands import Agent  # noqa: E402
from strands.models import BedrockModel  # noqa: E402
from strands.tools.mcp.mcp_client import MCPClient  # noqa: E402
from mcp.client.streamable_http import streamablehttp_client  # noqa: E402

from agent_base import parse_prompt, team_id_from  # noqa: E402
from parsing import parse_commands  # noqa: E402
from state import summarize_state  # noqa: E402
from fallback import (  # noqa: E402
    build_fallback, build_last_resort,
    GK_CONFIG, DEF_CONFIG, MID_CONFIG, FWD1_CONFIG, FWD2_CONFIG,
)

import constants  # noqa: E402
import planner  # noqa: E402
import plugin_loader  # noqa: E402

FALLBACK_CONFIGS = {
    "GK": GK_CONFIG, "DEF": DEF_CONFIG, "MID": MID_CONFIG,
    "FWD1": FWD1_CONFIG, "FWD2": FWD2_CONFIG,
}

GATEWAY_ENV = "AGENTCORE_GATEWAY_TACTICAL_TOOLS_URL"


def _gateway_transport():
    """Streamable-HTTP transport to the tactical-tools gateway, if configured."""
    url = os.environ.get(GATEWAY_ENV) or os.environ.get("GATEWAY_URL")
    if not url:
        return None
    headers = {}
    token = os.environ.get("GATEWAY_ACCESS_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return lambda: streamablehttp_client(url, headers=headers)


def register(app, my_player_id: int):
    """Build and register the @app.entrypoint invoke handler for one player.

    Three fallback layers, same contract as commons.agent_base:
      1. LLM (with MCP tools) → parsed commands
      2. rule-based fallback for the position
      3. last-resort single command
    """
    log = app.logger
    position_label = constants.position_for(my_player_id)
    fallback_cfg = FALLBACK_CONFIGS[position_label]
    fallback_fn = build_fallback(fallback_cfg)
    last_resort = build_last_resort(fallback_cfg, my_player_id)
    skill_descriptions = plugin_loader.strategy_descriptions()

    # Fetch MCP tools once at startup; reuse the client per tick.
    transport = _gateway_transport()
    mcp_client = MCPClient(transport) if transport else None
    cached_tools = []
    if mcp_client is not None:
        try:
            with mcp_client:
                cached_tools = mcp_client.list_tools_sync()
        except Exception as e:  # gateway optional — degrade to no tools
            log.warn(f"{position_label}: could not fetch MCP tools ({e}); running without them")
            mcp_client = None

    model = BedrockModel(model_id=constants.MODEL_ID)

    @app.entrypoint
    async def invoke(payload, context):
        prompt_data = parse_prompt(payload)
        team_id = team_id_from(prompt_data, log, position_label)
        try:
            game_state = prompt_data.get("gameState", {})
            my_players = prompt_data.get("myPlayers", [my_player_id])
            effective_pid = my_players[0] if my_players else my_player_id
            pos = constants.position_for(effective_pid)

            hint = prompt_data.get("strategy", "auto")
            strategy = planner.select_strategy(
                game_state, team_id, skill_descriptions, hint=hint
            )

            system_prompt = plugin_loader.build_system_prompt(strategy, pos, effective_pid)
            state_summary = summarize_state(game_state, team_id, effective_pid, pos)
            log.info(
                f"{pos} agent: team {team_id}, player {effective_pid}, strategy {strategy}"
            )

            agent = Agent(model=model, system_prompt=system_prompt, tools=cached_tools)

            if mcp_client is not None:
                with mcp_client:
                    response = agent(state_summary)
            else:
                response = agent(state_summary)

            commands = parse_commands(str(response), team_id, effective_pid)
            if commands:
                log.info(f"LLM returned {len(commands)} commands: "
                         f"{[c.get('commandType') for c in commands]}")
                yield json.dumps(commands)
            else:
                log.warn("LLM parse failed, using fallback.")
                yield json.dumps(fallback_fn(game_state, team_id, effective_pid))

        except Exception as e:
            log.error(f"{position_label} agent error: {e}")
            try:
                my_players = prompt_data.get("myPlayers", [my_player_id])
                effective_pid = my_players[0] if my_players else my_player_id
                yield json.dumps(
                    fallback_fn(prompt_data.get("gameState", {}), team_id, effective_pid)
                )
            except Exception as fe:
                log.error(f"{position_label} fallback also failed: {fe}")
                cmd = dict(last_resort)
                cmd["teamId"] = team_id
                yield json.dumps([cmd])

    return invoke
