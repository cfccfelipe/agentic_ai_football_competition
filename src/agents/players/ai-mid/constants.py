"""Single source of truth for configurable values of the unified agent.

Change the model here once and every position picks it up. We use Nova Micro
for all positions until we have confirmed capacity to go bigger.
"""

import os

# Model used by every EXECUTION agent (per-tick command). Nova Micro: fast + cheap,
# which matters because every player runs it ~every 2s under a 5s decision window.
MODEL_ID = "us.amazon.nova-2-lite-v1:0"


def planner_model_id() -> str:
    """Model id for the PLANNER (the per-tick strategy + formation decision).

    Execution stays Nova Micro (MODEL_ID); planning is the ONE place a stronger
    model earns its latency, because a wrong strategy pick costs the whole tick.
    Resolved from env PLANNER_MODEL_ID so a stronger Bedrock id (e.g. a Nova
    Lite/Pro or Claude Haiku id) can be enabled without a code change; defaults
    to MODEL_ID so a deploy NEVER breaks when no stronger model is confirmed
    enabled in the account/region. See .env.example for a candidate id.
    """
    return os.environ.get("PLANNER_MODEL_ID") or MODEL_ID


# Back-compat module constant (snapshot at import). Prefer planner_model_id()
# so an env override set after import is still honored.
PLANNER_MODEL_ID = os.environ.get("PLANNER_MODEL_ID") or MODEL_ID

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
# Wall-clock budget for the ONE-TIME startup fetch of MCP tools from the
# gateway. The AgentCore runtime must finish initialization within ~30s or it
# is killed ("Runtime initialization time exceeded"). A slow/unreachable
# gateway must NOT hang init: if the fetch exceeds this, the agent starts with
# NO tools (LLM + deterministic fallback still work) rather than failing to
# initialize. Kept well under the 30s init ceiling.
TOOL_FETCH_TIMEOUT_SECONDS = 8.0


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


def planner_model_kwargs() -> dict:
    """Kwargs for the PLANNER's BedrockModel — mirrors bedrock_model_kwargs()
    but uses the (optionally stronger) PLANNER_MODEL_ID.

    Same retries-off + optional guardrail wiring as the execution model, so the
    only difference between planning and execution is the model id.
    """
    from botocore.config import Config

    kwargs: dict = {
        "model_id": planner_model_id(),
        "boto_client_config": Config(
            retries={"max_attempts": 1, "mode": "standard"}
        ),
    }
    gid = guardrail_id()
    if gid:
        kwargs["guardrail_id"] = gid
        kwargs["guardrail_version"] = guardrail_version()
    return kwargs

# Fixed player-id -> position-label map. The server always fields 5 players.
# player 0 is ALWAYS GK and player 1 ALWAYS DEF (hard-pinned, see
# formation_roles). players 2/3/4 default to these labels but may be reassigned
# a role per the formation / flex flag — formation_roles is the source of truth.
PLAYER_POSITIONS = {
    0: "GK",
    1: "DEF",
    2: "MID",
    3: "FWD",
    4: "FWD",
}

# The 4-role set every player resolves to (the GK is always player 0). Forward
# players 3/4 (and any flexed player) collapse to the single FWD role folder.
ROLES = ("GK", "DEF", "MID", "FWD")

# Role label -> plugins/<folder>. FWD1/FWD2 are accepted as transition aliases
# for FWD so older callers/tests keep loading the merged forward body.
_ROLE_FOLDERS = {
    "GK": "gk", "DEF": "def", "MID": "mid", "FWD": "fwd",
    "FWD1": "fwd", "FWD2": "fwd",
}


def role_folder(role_label: str) -> str:
    """Map a role label (GK/DEF/MID/FWD, or FWD1/FWD2 alias) to its plugin folder.

    Unknown labels fall back to their lowercase form so a genuinely new role
    folder still resolves; FWD1/FWD2 both resolve to the single ``fwd`` folder.
    """
    return _ROLE_FOLDERS.get(role_label.upper(), role_label.lower())

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
DEFAULT_FORMATION = "1-1-1-2"


def position_for(player_id: int) -> str:
    """Return the position label for a player id, defaulting to MID."""
    return PLAYER_POSITIONS.get(player_id, "MID")
