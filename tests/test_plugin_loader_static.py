"""Static/dynamic prompt split in plugin_loader.

Covers:
  T-CAT      — load_tool_catalog() names exactly the four tactical tools and
               contradicts no guardrail rule.
  T-STATIC-a — build_static_base() = guardrails + tool catalog, built pure and
               deterministic (two calls identical).
  T-DYNAMIC  — compose_tick_prompt() joins the cached static base with the
               position/strategy body; build_system_prompt() stays a thin
               wrapper that still carries guardrails + formation (Finding 5).

Pure: no AWS, no network.
"""

import re

from test_helpers import mock_agentcore_gateway

mock_agentcore_gateway()

import plugin_loader  # noqa: E402

FOUR_TOOLS = (
    "evaluate_shot",
    "calculate_pass_options",
    "find_open_space",
    "get_defensive_assignment",
)


# --- T-CAT ------------------------------------------------------------------

def test_tool_catalog_names_exactly_the_four_tools():
    catalog = plugin_loader.load_tool_catalog()
    for name in FOUR_TOOLS:
        assert name in catalog

    # No other tool-looking snake_case token beyond the four (ignore the
    # commands GK_DISTRIBUTE etc. which are upper-case, not tool names).
    snake_tokens = set(re.findall(r"\b[a-z]+_[a-z_]+\b", catalog))
    extra = snake_tokens - set(FOUR_TOOLS) - {"aim_location"}
    # Only the four tactical tools may appear as lower_snake tool-looking names.
    assert extra == set(), f"unexpected tool-looking tokens: {extra}"


def test_tool_catalog_contradicts_no_guardrail_rule():
    catalog = plugin_loader.load_tool_catalog().lower()
    # Must not restate a rule that contradicts guardrails.md.
    assert "own goal" not in catalog
    assert "prose" not in catalog or "no prose" not in catalog  # no "return prose"
    assert "two commands" not in catalog
    assert "multiple commands" not in catalog


# --- T-STATIC-a -------------------------------------------------------------

def test_build_static_base_contains_guardrails_and_all_tools():
    base = plugin_loader.build_static_base()
    # Full guardrails text present (marker from guardrails.md).
    assert "JSON array" in base
    # All four tool names present (tool catalog folded in).
    for name in FOUR_TOOLS:
        assert name in base


def test_build_static_base_is_deterministic():
    assert plugin_loader.build_static_base() == plugin_loader.build_static_base()


def test_build_static_base_has_no_strategy_or_position_markers():
    base = plugin_loader.build_static_base()
    # Static base is strategy/position agnostic — no skill body markers.
    assert "{player_id}" not in base
    assert "Forward 1" not in base
    assert "Goalkeeper" not in base


# --- T-DYNAMIC --------------------------------------------------------------

def test_compose_tick_prompt_joins_base_and_skill_body():
    base = plugin_loader.build_static_base()
    composed = plugin_loader.compose_tick_prompt(base, "aggressive", "FWD", 3)
    expected = base + "\n\n---\n\n" + plugin_loader.load_skill_prompt("aggressive", "FWD", 3)
    assert composed == expected
    # Forward (merged) body marker + aggressive's resolved formation present.
    assert "Forward" in composed
    assert "1-1-2" in composed


def test_build_system_prompt_wrapper_keeps_e2e_markers():
    prompt = plugin_loader.build_system_prompt("aggressive", "FWD", 3)
    # Finding 5 — these are the markers test_e2e_tick.py asserts on.
    assert "JSON array" in prompt          # full guardrails
    assert "Formation" in prompt           # formation posture section
    assert "1-1-2" in prompt               # aggressive's remapped formation
    # Tool catalog folded in via build_static_base.
    assert "evaluate_shot" in prompt
