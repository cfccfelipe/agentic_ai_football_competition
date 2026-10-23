"""Composes the final system prompt from governance guardrails + the selected
strategy's position file.

Single Responsibility: this module only *reads and composes text*. It does not
decide the strategy (planner does) and does not know about Strands or AgentCore.
It leans on plugins.registry for discovery so it never hard-codes plugin names.
"""

from __future__ import annotations

import sys
from pathlib import Path

# src/ root, so `from plugins import registry` resolves.
_SRC_ROOT = Path(__file__).resolve().parents[2]
if str(_SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(_SRC_ROOT))

from plugins import registry  # noqa: E402

GOVERNANCE = _SRC_ROOT / "governance" / "guardrails.md"
TOOL_CATALOG = _SRC_ROOT / "governance" / "tool_catalog.md"

# Root of the plugins tree. Resolved from _SRC_ROOT so it matches both the
# local checkout (src/plugins) and the deployed bundle, where deploy_all.py
# stages src/plugins as a sibling `plugins/` directory next to unified_agent.py.
_PLUGINS_ROOT = _SRC_ROOT / "plugins"


def load_guardrails() -> str:
    """Return the fixed game guardrails that prefix every system prompt."""
    return GOVERNANCE.read_text(encoding="utf-8")


def load_tool_catalog() -> str:
    """Return the static tactical-tool catalog (names + when-to-use triggers).

    Ships inside the deployed bundle's governance/ folder, same as guardrails.
    A missing file raises FileNotFoundError at build time — a packaging error
    that must surface loudly at process init, never silently mid-match.
    """
    return TOOL_CATALOG.read_text(encoding="utf-8")


def build_static_base() -> str:
    """The STATIC system-prompt base, built once per agent and cached.

    guardrails (fixed rules) + the tactical-tool catalog. It is strategy- and
    position-agnostic, so it never changes across ticks and is composed once at
    register() time, not per tick.
    """
    return f"{load_guardrails()}\n\n---\n\n{load_tool_catalog()}"


def load_skill_prompt(strategy: str, position_label: str, player_id: int) -> str:
    """Return the position prompt for a strategy, with {player_id} and
    {formation} resolved.

    Falls back to the default strategy if the requested one is unknown, and to
    MID if the position file is missing — never raises on a bad tag. When the
    requested strategy is unknown the formation is DEFAULT_FORMATION (the
    position text still comes from the default strategy's files).
    """
    from constants import DEFAULT_FORMATION, DEFAULT_STRATEGY

    strategies = registry.strategies()
    meta = strategies.get(strategy)
    if meta is None:
        resolved_strategy = DEFAULT_STRATEGY
        formation = DEFAULT_FORMATION
    else:
        resolved_strategy = strategy
        formation = meta.formation

    # Position prose lives in the POSITION folder, grouped by strategy name:
    # plugins/<position>/<strategy>.md. meta.path now points at plugins/
    # strategies/, so it is NOT used to locate the body. Unknown position
    # falls back to MID.
    position_file = _PLUGINS_ROOT / position_label.lower() / f"{resolved_strategy}.md"
    if not position_file.is_file():
        position_file = _PLUGINS_ROOT / "mid" / f"{resolved_strategy}.md"

    template = position_file.read_text(encoding="utf-8")
    return (
        template
        .replace("{player_id}", str(player_id))
        .replace("{formation}", formation)
    )


def compose_tick_prompt(
    static_base: str, strategy: str, position_label: str, player_id: int
) -> str:
    """Per-tick composition: the cached STATIC base + the DYNAMIC strategy body.

    Called once per tick AFTER the strategy is confirmed. One string join over
    an already-cached base plus a local skill-file read — no network.
    """
    skill = load_skill_prompt(strategy, position_label, player_id)
    return f"{static_base}\n\n---\n\n{skill}"


def build_system_prompt(strategy: str, position_label: str, player_id: int) -> str:
    """static base (guardrails + tool catalog) + the strategy/position prompt.

    Thin wrapper retained for tests / one-shot callers. The hot path builds the
    static base once at register() and calls compose_tick_prompt() directly.
    """
    return compose_tick_prompt(
        build_static_base(), strategy, position_label, player_id
    )


def strategy_descriptions() -> str:
    """Return the strategy descriptions block for the planner to read."""
    return registry.strategy_descriptions()


def strategy_names() -> tuple[str, ...]:
    """Return the discovered strategy names (the planner's selectable set)."""
    return tuple(registry.strategies().keys())
