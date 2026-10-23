"""Pure metrics over tick records — no I/O, no AWS, no network.

A *tick record* is a plain dict (kept dict-based so any producer, including a
future CloudWatch adapter, can emit the same shape with no class dependency)::

    {
      "team": str,          # team display name, e.g. "Lightning Cloud"
      "position": str,      # one of "GK","DEF","MID","FWD1","FWD2"
      "commandType": str,   # a VALID_COMMANDS value, e.g. "MOVE_TO"
      "latency_ms": float,  # response latency in milliseconds
      "success": bool,      # True iff a valid parsed command returned in budget
    }

Everything here is a pure function of its inputs: given the same records it
returns the same numbers, with no shared mutable state.
"""

from dataclasses import dataclass

from constants import TICK_TIMEOUT_SECONDS

# Single source of truth for command display names. Covers every VALID_COMMANDS
# entry; the first eight match the target report labels 1:1 (SLIDE_TACKLE -> "Clear"
# resolves the brief's "Tackle/Clear" to the label the example actually prints).
COMMAND_DISPLAY_NAMES: dict[str, str] = {
    "MOVE_TO": "Move",
    "MARK": "Mark",
    "PASS": "Pass",
    "PRESS_BALL": "Press",
    "INTERCEPT": "Intercept",
    "SHOOT": "Shoot",
    "GK_DISTRIBUTE": "GK Dist",
    "SLIDE_TACKLE": "Clear",
    "SET_STANCE": "Set Stance",
    "FOLLOW_PLAYER": "Follow",
    "CLEAR_OVERRIDE": "Clear Ovr",
    "RESET": "Reset",
}

# An agent-performance row is flagged when its average latency reaches this
# fraction of the hard tick budget. Derived from constants, never hard-coded.
# Rounded to whole milliseconds so it compares cleanly against the rounded
# avg_latency_ms (and avoids binary-float noise like 2800.0000000000005).
_ALERT_LATENCY_FRACTION = 0.8
ALERT_LATENCY_MS = round(_ALERT_LATENCY_FRACTION * TICK_TIMEOUT_SECONDS * 1000)


@dataclass(frozen=True)
class TickRecord:
    """Ergonomic, immutable constructor for a tick record.

    The metrics functions consume the plain dict form; use ``as_dict()`` to feed
    them. Optional — a producer may build dicts directly.
    """

    team: str
    position: str
    commandType: str
    latency_ms: float
    success: bool

    def as_dict(self) -> dict:
        return {
            "team": self.team,
            "position": self.position,
            "commandType": self.commandType,
            "latency_ms": self.latency_ms,
            "success": self.success,
        }


def display_name(command_type: str) -> str:
    """Display label for a command type; title-cased fallback for unknowns."""
    if command_type in COMMAND_DISPLAY_NAMES:
        return COMMAND_DISPLAY_NAMES[command_type]
    return command_type.replace("_", " ").title()


def _mean(values: list[float]) -> float:
    """Arithmetic mean; 0.0 for an empty sequence."""
    return sum(values) / len(values) if values else 0.0


def _group_by(records: list[dict], keyfn) -> dict:
    """Group records into an insertion-ordered dict keyed by ``keyfn(record)``."""
    groups: dict = {}
    for record in records:
        groups.setdefault(keyfn(record), []).append(record)
    return groups


def command_breakdown(records: list[dict]) -> dict:
    """Per-team command breakdown.

    Returns, per team (in first-seen order)::

        {
          team_name: {
            "total": int,
            "avg_latency_ms": int,              # round(mean latency)
            "commands": [                       # sorted count desc, then label asc
              {"type": "MARK", "display": "Mark", "count": 184, "pct": 40},
              ...
            ],
          },
          ...
        }

    Commands are grouped by display name so any future duplicate raw type mapping
    to the same label aggregates together (today the mapping is 1:1).
    """
    result: dict = {}
    for team, team_records in _group_by(records, lambda r: r["team"]).items():
        total = len(team_records)
        avg_latency = round(_mean([r["latency_ms"] for r in team_records]))

        by_display: dict = {}
        for record in team_records:
            display = display_name(record["commandType"])
            entry = by_display.setdefault(
                display, {"type": record["commandType"], "display": display, "count": 0}
            )
            entry["count"] += 1

        commands = list(by_display.values())
        for entry in commands:
            entry["pct"] = round(entry["count"] / total * 100) if total else 0
        commands.sort(key=lambda e: (-e["count"], e["display"]))

        result[team] = {
            "total": total,
            "avg_latency_ms": avg_latency,
            "commands": commands,
        }
    return result


def agent_performance(records: list[dict]) -> dict:
    """Per-team, per-position response time and success rate.

    Returns, per team then per position (positions with zero records omitted)::

        {
          team_name: {
            "GK": {"avg_latency_ms": int, "success_pct": int, "alert": bool},
            ...
          },
          ...
        }

    ``alert`` is True when success rate is below 100% OR the position's average
    latency reaches 80% of the hard tick budget (``ALERT_LATENCY_MS``).
    """
    result: dict = {}
    for team, team_records in _group_by(records, lambda r: r["team"]).items():
        positions: dict = {}
        for position, pos_records in _group_by(
            team_records, lambda r: r["position"]
        ).items():
            count = len(pos_records)
            avg_latency = round(_mean([r["latency_ms"] for r in pos_records]))
            successes = sum(1 for r in pos_records if r["success"])
            success_pct = round(100 * successes / count) if count else 0
            alert = success_pct < 100 or avg_latency >= ALERT_LATENCY_MS
            positions[position] = {
                "avg_latency_ms": avg_latency,
                "success_pct": success_pct,
                "alert": alert,
            }
        result[team] = positions
    return result
