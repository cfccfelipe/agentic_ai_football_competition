"""Single source of truth for configurable values of the unified agent.

Change the model here once and every position picks it up. We use Nova Micro
for all positions until we have confirmed capacity to go bigger.
"""

import os

# Model used by every agent and the planner. Nova Micro everywhere for now.
MODEL_ID = "us.amazon.nova-micro-v1:0"

# --- Runtime hardening (FEAT-002) -----------------------------------------
# Hard wall-clock budget for a single tick's model+tools call. The server
# decision timeout is 5s; we stay well under it so the deterministic fallback
# always has time to run.
TICK_TIMEOUT_SECONDS = 3.5
# Max agent-loop iterations (model call + tool execution) per tick, enforced
# via the Strands per-invocation Limits `turns` cap.
MAX_TOOL_ITERATIONS = 2
# Per-MCP-tool wall-clock budget so one slow tool cannot eat the tick budget.
PER_TOOL_TIMEOUT_SECONDS = 1.0


def guardrail_id() -> str | None:
    """Bedrock guardrail id from the environment, or None when unset."""
    return os.environ.get("BEDROCK_GUARDRAIL_ID")


def guardrail_version() -> str:
    """Bedrock guardrail version from the environment (defaults to DRAFT)."""
    return os.environ.get("BEDROCK_GUARDRAIL_VERSION", "DRAFT")


def bedrock_model_kwargs() -> dict:
    """Kwargs for BedrockModel: model id, disabled retries, optional guardrail.

    Retries are disabled (max_attempts=1) so a slow Bedrock call fails fast
    instead of silently burning the tick budget on boto's automatic retries.
    Guardrail keys are added only when BEDROCK_GUARDRAIL_ID is set, so an
    unconfigured environment produces no guardrail wiring. botocore is imported
    lazily so pure constant reads do not require it.
    """
    from botocore.config import Config

    kwargs: dict = {
        "model_id": MODEL_ID,
        "boto_client_config": Config(
            retries={"max_attempts": 1, "mode": "standard"}
        ),
    }
    gid = guardrail_id()
    if gid:
        kwargs["guardrail_id"] = gid
        kwargs["guardrail_version"] = guardrail_version()
    return kwargs

# Fixed player-id -> position-label map. The server always fields 5 players;
# the position is derived from the id, never guessed.
PLAYER_POSITIONS = {
    0: "GK",
    1: "DEF",
    2: "MID",
    3: "FWD1",
    4: "FWD2",
}

# Strategy used when the planner cannot decide.
DEFAULT_STRATEGY = "balanced"

# Valid strategies (must match plugin folder names under src/plugins/).
STRATEGIES = ("balanced", "aggressive", "defensive")

# Known formations (DEF-MID-FWD distribution of the 4 outfield players; the GK
# is always fielded and not counted). Mirror of .kiro/steering/game-domain.md.
ALLOWED_FORMATIONS = (
    "0-4-0", "1-0-3", "1-1-2", "1-1-1-1", "1-2-1", "2-0-2", "2-1-1", "3-0-1",
)

# Formation used when a strategy declares none (balanced, staggered).
DEFAULT_FORMATION = "1-1-1-1"


def position_for(player_id: int) -> str:
    """Return the position label for a player id, defaulting to MID."""
    return PLAYER_POSITIONS.get(player_id, "MID")
