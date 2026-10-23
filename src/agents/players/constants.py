"""Single source of truth for configurable values of the unified agent.

Change the model here once and every position picks it up. We use Nova Micro
for all positions until we have confirmed capacity to go bigger.
"""

# Model used by every agent and the planner. Nova Micro everywhere for now.
MODEL_ID = "us.amazon.nova-micro-v1:0"

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


def position_for(player_id: int) -> str:
    """Return the position label for a player id, defaulting to MID."""
    return PLAYER_POSITIONS.get(player_id, "MID")
