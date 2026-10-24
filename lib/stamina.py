"""Stamina-aware decision helpers for AI soccer agents.

The raw stamina value (0.0–1.0) already appears in the state summary, but the
LLM has no reference point: `stam=0.45` looks the same whether the game just
started (critically low) or the half is almost over (expected).

This module provides:
  - `stamina_context`   — computes a StaminaCtx with contextualised advice
  - `sprint_ok`         — whether sprinting is advisable right now
  - `press_intensity`   — scaled pressing intensity based on current stamina
  - `format_for_prompt` — injects a one-line annotation next to the stamina value

The context label and advice are written in second-person so they can be
dropped verbatim into the state summary without extra formatting.
"""

from __future__ import annotations
from dataclasses import dataclass
import math


# Assumed match half duration in seconds.  The server does not expose this
# directly, so we use a conservative estimate.  Agents that know the actual
# duration (e.g. because the prompt contains it) can pass it explicitly.
DEFAULT_HALF_DURATION: float = 300.0


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class StaminaCtx:
    current: float          # raw 0.0–1.0 stamina
    expected: float         # what we'd expect at this point in the half
    ratio: float            # current / expected  (>1 = fresher than expected)
    label: str              # FRESH | OK | TIRED | CRITICAL
    advice: str             # short text injected into the LLM prompt
    sprint_ok: bool         # whether sprinting is advisable
    press_intensity: float  # 0.3 – 0.85 scaled to current stamina
    input_warning: str | None = None


UNKNOWN_STAMINA = 0.20


def normalize_stamina(value) -> tuple[float, str | None]:
    """Normalize fractional or percentage stamina; unknown values are conservative."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        stamina = float(value)
        if math.isfinite(stamina):
            if 0.0 <= stamina <= 1.0:
                return stamina, None
            if 1.0 < stamina <= 100.0:
                return stamina / 100.0, "stamina was supplied as a percentage"
    return UNKNOWN_STAMINA, "stamina is missing or invalid; using a conservative value"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def stamina_context(
    stamina,
    game_time: float,
    half_duration: float = DEFAULT_HALF_DURATION,
) -> StaminaCtx:
    """Build a StaminaCtx from raw values.

    Parameters
    ----------
    stamina       : float   Current stamina (0.0–1.0).
    game_time     : float   Seconds elapsed this half.
    half_duration : float   Expected length of the half in seconds.
    """
    stamina, input_warning = normalize_stamina(stamina)

    # Expected stamina drains linearly from 1.0 at kick-off to ~0.5 by the
    # end of the half — a reasonable model for 5v5 arcade soccer.
    progress     = min(1.0, game_time / max(1.0, half_duration))
    expected     = 1.0 - (0.5 * progress)
    ratio        = stamina / expected if expected > 0 else 1.0

    label, advice, ok, intensity = _classify(stamina, ratio)

    return StaminaCtx(
        current        = stamina,
        expected       = round(expected, 2),
        ratio          = round(ratio, 2),
        label          = label,
        advice         = advice,
        sprint_ok      = ok,
        press_intensity= round(intensity, 2),
        input_warning  = input_warning,
    )


def sprint_ok(stamina: float, game_time: float,
              half_duration: float = DEFAULT_HALF_DURATION) -> bool:
    """Convenience wrapper — True when sprinting is advisable."""
    return stamina_context(stamina, game_time, half_duration).sprint_ok


def press_intensity(stamina: float, game_time: float,
                    half_duration: float = DEFAULT_HALF_DURATION) -> float:
    """Convenience wrapper — recommended pressing intensity (0.3–0.85)."""
    return stamina_context(stamina, game_time, half_duration).press_intensity


def format_for_prompt(ctx: StaminaCtx) -> str:
    """Return a compact annotation to append after the raw stamina value.

    Example output:
      [TIRED — conserve energy, avoid unnecessary sprints]
    """
    warning = f"; {ctx.input_warning}" if ctx.input_warning else ""
    return f"[{ctx.label} — {ctx.advice}{warning}]"


# ---------------------------------------------------------------------------
# Internal classification
# ---------------------------------------------------------------------------

def _classify(
    stamina: float,
    ratio: float,
) -> tuple[str, str, bool, float]:
    """Return (label, advice, sprint_ok, press_intensity)."""

    # Absolute stamina thresholds take precedence — even early in the game a
    # very low value is alarming.
    if stamina < 0.25:
        return (
            "CRITICAL",
            "stamina critically low — walk, no sprinting, minimal pressing",
            False, 0.30,
        )
    if stamina < 0.45:
        return (
            "TIRED",
            "conserve energy, avoid unnecessary sprints",
            False, 0.45,
        )

    # Relative ratio: is the player fresher or more tired than expected?
    if ratio >= 1.15:
        return (
            "FRESH",
            "fully energised — sprint freely, press hard",
            True, 0.85,
        )
    if ratio >= 0.90:
        return (
            "OK",
            "stamina on track — sprint for key moments only",
            True, 0.65,
        )
    # ratio < 0.90 and stamina >= 0.45: draining faster than expected
    return (
        "TIRED",
        "draining faster than expected — pick your sprints carefully",
        False, 0.50,
    )
