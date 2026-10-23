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


def load_guardrails() -> str:
    """Return the fixed game guardrails that prefix every system prompt."""
    return GOVERNANCE.read_text(encoding="utf-8")


def load_skill_prompt(strategy: str, position_label: str, player_id: int) -> str:
    """Return the position prompt for a strategy, with {player_id} resolved.

    Falls back to the default strategy if the requested one is unknown, and to
    MID if the position file is missing — never raises on a bad tag.
    """
    strategies = registry.strategies()
    meta = strategies.get(strategy)
    if meta is None:
        from constants import DEFAULT_STRATEGY
        meta = strategies[DEFAULT_STRATEGY]

    position_file = meta.path / f"{position_label.lower()}.md"
    if not position_file.is_file():
        position_file = meta.path / "mid.md"

    template = position_file.read_text(encoding="utf-8")
    return template.replace("{player_id}", str(player_id))


def build_system_prompt(strategy: str, position_label: str, player_id: int) -> str:
    """guardrails (fixed) + the strategy/position prompt (dynamic)."""
    guardrails = load_guardrails()
    skill = load_skill_prompt(strategy, position_label, player_id)
    return f"{guardrails}\n\n---\n\n{skill}"


def strategy_descriptions() -> str:
    """Return the strategy descriptions block for the planner to read."""
    return registry.strategy_descriptions()
