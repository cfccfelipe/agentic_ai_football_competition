"""Strategy selection.

The agent chooses its own strategy by reading the skill descriptions and the
current game state. A lightweight LLM call does the reading; if it is
unavailable or returns something unexpected, a deterministic rule based on the
scoreline and clock takes over so a strategy is always produced.

Single Responsibility: decide *which* strategy applies this tick. It does not
build prompts or talk to AgentCore.
"""

from __future__ import annotations

from constants import DEFAULT_STRATEGY, MODEL_ID, STRATEGIES


def _score_for(game_state: dict, team_id: int) -> tuple[int, int]:
    """Return (my_score, opp_score) from the game state."""
    score = game_state.get("score", {})
    home, away = score.get("home", 0), score.get("away", 0)
    return (home, away) if team_id == 0 else (away, home)


def rule_based_strategy(game_state: dict, team_id: int) -> str:
    """Deterministic fallback: scoreline + clock → strategy.

    Mirrors the descriptions in the skill.md files so the rule and the LLM
    agree on intent.
    """
    my_score, opp_score = _score_for(game_state, team_id)
    diff = my_score - opp_score
    game_time = game_state.get("gameTime", 0) or 0

    if diff < 0 and (game_time > 70 or diff <= -2):
        return "aggressive"
    if diff > 0 and (game_time > 75 or (diff >= 2 and game_time > 65)):
        return "defensive"
    return DEFAULT_STRATEGY


def _parse_choice(text: str) -> str | None:
    """Extract a known strategy name from free LLM text."""
    low = text.lower()
    for name in STRATEGIES:
        if name in low:
            return name
    return None


def select_strategy(
    game_state: dict,
    team_id: int,
    skill_descriptions: str,
    hint: str = "auto",
    agent_factory=None,
) -> str:
    """Return the strategy for this tick.

    Args:
        game_state: current game state dict.
        team_id: 0 (HOME) or 1 (AWAY).
        skill_descriptions: text block of strategy names + descriptions
            (from registry.strategy_descriptions()).
        hint: a pinned strategy, or "auto" to let the planner decide.
        agent_factory: optional zero-arg callable returning a Strands-like
            agent (callable with a prompt). Injected for testing; when None,
            a Nova Micro agent is created lazily. If creation or the call
            fails, the rule-based strategy is used.

    Non-auto hints pass through unchanged (after validation).
    """
    if hint != "auto":
        return hint if hint in STRATEGIES else DEFAULT_STRATEGY

    my_score, opp_score = _score_for(game_state, team_id)
    game_time = game_state.get("gameTime", 0) or 0
    prompt = (
        "You are a football match tactician. Choose ONE strategy for this tick.\n\n"
        f"Score: us {my_score} - {opp_score} them. Game time: {game_time:.0f}.\n\n"
        f"Strategies:\n{skill_descriptions}\n\n"
        "Reply with ONLY the strategy name."
    )

    try:
        agent = agent_factory() if agent_factory else _default_agent()
        choice = _parse_choice(str(agent(prompt)))
        if choice:
            return choice
    except Exception:
        pass

    return rule_based_strategy(game_state, team_id)


def _default_agent():
    """Create a Nova Micro agent for strategy selection (lazy import)."""
    from strands import Agent
    from strands.models import BedrockModel

    return Agent(model=BedrockModel(model_id=MODEL_ID))
