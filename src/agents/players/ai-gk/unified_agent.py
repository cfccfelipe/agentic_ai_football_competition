"""Unified agent factory + invoke handler.

All five position agents share this. The only thing that differs between them
is MY_PLAYER_ID, which the thin main.py passes in. Everything else — the
dynamic prompt, the strategy choice, the MCP tools, the fallback — is identical.

The system prompt is built *inside* invoke(), not at module load, because it
depends on the strategy chosen that tick. Tools are fetched once at startup and
reused; only the Agent object is rebuilt per tick with the fresh prompt.
"""

from __future__ import annotations

import asyncio
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
    GK_CONFIG, DEF_CONFIG, MID_CONFIG, FWD_CONFIG, FWD1_CONFIG, FWD2_CONFIG,
)

import constants  # noqa: E402
import formation_roles  # noqa: E402
import planner  # noqa: E402
import plugin_loader  # noqa: E402
from runtime_guards import wrap_tool_with_timeout  # noqa: E402

# Keyed by ROLE label. FWD is the single merged forward config; FWD1/FWD2 remain
# as transition aliases so any caller still resolves a config.
FALLBACK_CONFIGS = {
    "GK": GK_CONFIG, "DEF": DEF_CONFIG, "MID": MID_CONFIG,
    "FWD": FWD_CONFIG, "FWD1": FWD1_CONFIG, "FWD2": FWD2_CONFIG,
}

GATEWAY_ENV = "AGENTCORE_GATEWAY_TACTICAL_TOOLS_URL"


def _flex_enabled(prompt_data: dict) -> bool:
    """Whether players 2/3/4 may adapt their role this tick (FLEX flag).

    Reads a per-payload flag first (``prompt_data['flexRoles']``), then the env
    ``FLEX_ROLES``. Defaults OFF so a deploy's behaviour never changes unless
    the flag is deliberately set. players 0/1 (GK/DEF) are unaffected either way.
    """
    if "flexRoles" in prompt_data:
        return bool(prompt_data.get("flexRoles"))
    return str(os.environ.get("FLEX_ROLES", "")).strip().lower() in ("1", "true", "yes", "on")


def _team_name_from(prompt_data: dict, team_id) -> str:
    """Best-effort team NAME for the log prefix, else ''.

    The server does not currently send a team name in a fixed field, so we probe
    the common shapes (top-level, gameState, a teams list keyed/indexed by team
    id) and return '' when none is present — the prefix then shows just the team
    id. Never raises on a surprising shape.
    """
    try:
        gs = prompt_data.get("gameState", {}) or {}
        for src in (prompt_data, gs):
            for key in ("teamName", "team_name"):
                val = src.get(key)
                if isinstance(val, str) and val.strip():
                    return val.strip()
        teams = gs.get("teams") or prompt_data.get("teams")
        if isinstance(teams, dict):
            entry = teams.get(str(team_id)) or teams.get(team_id)
            if isinstance(entry, dict) and isinstance(entry.get("name"), str):
                return entry["name"].strip()
            if isinstance(entry, str):
                return entry.strip()
        if isinstance(teams, list) and isinstance(team_id, int) and 0 <= team_id < len(teams):
            entry = teams[team_id]
            if isinstance(entry, dict) and isinstance(entry.get("name"), str):
                return entry["name"].strip()
            if isinstance(entry, str):
                return entry.strip()
    except Exception:
        pass
    return ""


def _log_prefix(team_id, team_name: str, player_id: int, role_label: str) -> str:
    """Build the per-line log prefix once, e.g. [team0 'Lighting Cloud' pos0 GK].

    Includes the team NAME when available so logs separate teams clearly; falls
    back to just the team id (team0/team1) otherwise.
    """
    name_part = f" '{team_name}'" if team_name else ""
    return f"[team{team_id}{name_part} pos{player_id} {role_label}]"


def _default_agent_factory(system_prompt: str, tools):
    """Build a Nova Micro agent for a tick (retries off, optional guardrail)."""
    model = BedrockModel(**constants.bedrock_model_kwargs())
    return Agent(model=model, system_prompt=system_prompt, tools=tools)


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


def register(app, my_player_id: int, agent_factory=None):
    """Build and register the @app.entrypoint invoke handler for one player.

    Three fallback layers, same contract as commons.agent_base:
      1. LLM (with MCP tools) → parsed commands
      2. rule-based fallback for the position
      3. last-resort single command

    Args:
        app: the AgentCore app exposing @entrypoint + logger.
        my_player_id: fixed id for this agent (position derived from it).
        agent_factory: optional callable (system_prompt, tools) -> a
            Strands-like agent (callable with a prompt and a ``limits`` kwarg).
            Injected for offline testing; when None, a Nova Micro agent is
            built per tick with retries disabled and the optional guardrail.
    """
    log = app.logger
    if agent_factory is None:
        agent_factory = _default_agent_factory
    # The STARTUP role label (used only for the last-resort crash command, which
    # must exist even if we never settle a strategy). The per-tick role is
    # resolved inside invoke() via formation_roles once the formation is known.
    # players 0/1 are hard-pinned GK/DEF; others default to the base map.
    startup_role = constants.position_for(my_player_id)
    startup_cfg = FALLBACK_CONFIGS.get(startup_role, MID_CONFIG)
    last_resort = build_last_resort(startup_cfg, my_player_id)
    skill_descriptions = plugin_loader.strategy_descriptions()
    known_strategies = plugin_loader.strategy_names()
    # STATIC base (guardrails + tool catalog) — built ONCE here and captured in
    # the invoke closure. invoke() never recomposes it; only the per-tick
    # strategy body is appended (see compose_tick_prompt in PHASE 2).
    static_base = plugin_loader.build_static_base()

    # Fetch MCP tools once at startup; reuse the client per tick.
    transport = _gateway_transport()
    mcp_client = MCPClient(transport) if transport else None
    cached_tools = []
    if mcp_client is not None:
        try:
            with mcp_client:
                cached_tools = mcp_client.list_tools_sync()
        except Exception as e:  # gateway optional — degrade to no tools
            log.warn(f"[team? pos{my_player_id} {startup_role}] could not fetch MCP tools ({e}); running without them")
            mcp_client = None

    # Bound every tool call so one slow tool cannot eat the tick budget.
    cached_tools = [
        wrap_tool_with_timeout(t, constants.PER_TOOL_TIMEOUT_SECONDS)
        for t in cached_tools
    ]

    @app.entrypoint
    async def invoke(payload, context):
        prompt_data = parse_prompt(payload)
        team_id = team_id_from(prompt_data, log, f"team?-pos{my_player_id}-{startup_role}")
        # Build the per-line log prefix ONCE per tick from team id + team NAME
        # (when the payload provides it) + player id + resolved role (below).
        team_name = _team_name_from(prompt_data, team_id)
        try:
            # --- PHASE 1: resolve role + CONFIRM the strategy (gate) ---------
            # Nothing downstream (skill content, tools) may run until a concrete,
            # known strategy is settled for this tick.
            game_state = prompt_data.get("gameState", {})
            my_players = prompt_data.get("myPlayers", [my_player_id])
            effective_pid = my_players[0] if my_players else my_player_id

            hint = prompt_data.get("strategy", "auto")
            strategy = planner.select_strategy(
                game_state, team_id, skill_descriptions, hint=hint,
                known=known_strategies,
            )
            # GATE: coerce (never assert/raise) an unknown strategy to the
            # default. An assert here would be swallowed by the broad except
            # below and stripped under `python -O`; an explicit logged guard
            # survives both and keeps a known name flowing to PHASE 2.
            if strategy not in known_strategies:
                log.warn(
                    f"[team{team_id} pos{effective_pid}] planner returned unknown "
                    f"strategy {strategy!r}; using default {constants.DEFAULT_STRATEGY!r}"
                )
                strategy = constants.DEFAULT_STRATEGY

            # --- Resolve THIS agent's ROLE for the tick (dynamic roles) ------
            # formation_roles is the single source of truth: player 0 is always
            # GK, player 1 always DEF; players 2/3/4 take the chosen formation's
            # remaining distribution (or may flex when the FLEX flag is on).
            flex = _flex_enabled(prompt_data)
            meta = plugin_loader.strategy_meta(strategy)
            formation = meta.formation if meta is not None else constants.DEFAULT_FORMATION
            role = formation_roles.formation_roles(formation, flex=flex)[effective_pid]
            fallback_cfg = FALLBACK_CONFIGS.get(role, MID_CONFIG)
            fallback_fn = build_fallback(fallback_cfg)
            prefix = _log_prefix(team_id, team_name, effective_pid, role)

            # --- PHASE 2: drill into THIS role's strategy skill content ------
            # Only now, with the strategy confirmed, is the dynamic body
            # appended to the cached static base. FWD-role players resolve to
            # plugins/fwd/ via plugin_loader -> constants.role_folder.
            system_prompt = plugin_loader.compose_tick_prompt(
                static_base, strategy, role, effective_pid
            )
            if formation_roles.is_flexible(effective_pid, flex):
                system_prompt += (
                    "\n\n---\n\n## Flexible role (think about your best position)\n"
                    "The FLEX flag is ON for you. The formation suggests you start as "
                    f"{role}, but you MAY adapt your role within {{DEF, MID, FWD}} for "
                    "this situation given the strategy — choose the position that helps "
                    "the team most right now. You are NEVER the goalkeeper."
                )
            state_summary = summarize_state(game_state, team_id, effective_pid, role)
            log.info(
                f"{prefix} strategy {strategy}, formation {formation}, flex={flex}"
            )

            # --- PHASE 3: controlled ReAct within the caps -------------------
            agent = agent_factory(system_prompt=system_prompt, tools=cached_tools)

            # Cap agent-loop iterations (model call + tools) per tick and run
            # the blocking call on the default executor under a hard wall-clock
            # budget. On timeout we fall through to the deterministic fallback
            # rather than let a slow tick exceed the server decision window.
            limits = {"turns": constants.MAX_TOOL_ITERATIONS}

            def _call_agent():
                if mcp_client is not None:
                    with mcp_client:
                        return agent(state_summary, limits=limits)
                return agent(state_summary, limits=limits)

            loop = asyncio.get_running_loop()
            try:
                response = await asyncio.wait_for(
                    loop.run_in_executor(None, _call_agent),
                    timeout=constants.TICK_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                log.warn(
                    f"{prefix} tick exceeded {constants.TICK_TIMEOUT_SECONDS}s, "
                    "using fallback."
                )
                yield json.dumps(fallback_fn(game_state, team_id, effective_pid))
                return

            commands = parse_commands(str(response), team_id, effective_pid)
            if commands:
                log.info(f"{prefix} LLM returned {len(commands)} commands: "
                         f"{[c.get('commandType') for c in commands]}")
                yield json.dumps(commands)
            else:
                log.warn(f"{prefix} LLM parse failed, using fallback.")
                yield json.dumps(fallback_fn(game_state, team_id, effective_pid))

        except Exception as e:
            log.error(
                f"[team{team_id}{(' ' + repr(team_name)) if team_name else ''} "
                f"pos{my_player_id} {startup_role}] agent error: {e}"
            )
            try:
                my_players = prompt_data.get("myPlayers", [my_player_id])
                effective_pid = my_players[0] if my_players else my_player_id
                # Role may not have been resolved (error before PHASE 1 finished);
                # use the startup config as a safe deterministic fallback.
                crash_fn = build_fallback(FALLBACK_CONFIGS.get(startup_role, MID_CONFIG))
                yield json.dumps(
                    crash_fn(prompt_data.get("gameState", {}), team_id, effective_pid)
                )
            except Exception as fe:
                log.error(
                    f"[team{team_id} pos{my_player_id} {startup_role}] "
                    f"fallback also failed: {fe}"
                )
                cmd = dict(last_resort)
                cmd["teamId"] = team_id
                yield json.dumps([cmd])

    return invoke
