"""Tests for plugin_loader — guardrails + strategy/position prompt composition."""

import plugin_loader


def test_guardrails_loaded():
    g = plugin_loader.load_guardrails()
    assert "Guardrails" in g or "guardrails" in g.lower()
    assert "JSON array" in g  # response-format rule is present


def test_skill_prompt_resolves_player_id():
    prompt = plugin_loader.load_skill_prompt("aggressive", "FWD", 3)
    assert "{player_id}" not in prompt
    assert "player 3" in prompt


def test_fwd_aliases_resolve_to_the_merged_fwd_body():
    # FWD1/FWD2 are transition aliases: all three load plugins/fwd/<strategy>.md.
    fwd = plugin_loader.load_skill_prompt("balanced", "FWD", 3)
    fwd1 = plugin_loader.load_skill_prompt("balanced", "FWD1", 3)
    assert "Forward" in fwd
    # FWD and the FWD1 alias load the SAME merged body for the same id.
    assert fwd1 == fwd


def test_unknown_strategy_falls_back_to_default():
    # Must not raise — unknown strategy degrades to the default (balanced).
    prompt = plugin_loader.load_skill_prompt("nonexistent", "GK", 0)
    assert "{player_id}" not in prompt
    assert "goalkeeper" in prompt.lower()


def test_unknown_position_falls_back_to_mid():
    prompt = plugin_loader.load_skill_prompt("balanced", "STRIKERX", 2)
    assert "midfielder" in prompt.lower()


def test_build_system_prompt_layers_guardrails_then_skill():
    full = plugin_loader.build_system_prompt("defensive", "DEF", 1)
    sep = full.index("---")
    assert "Guardrails" in full[:sep] or "guardrails" in full[:sep].lower()
    assert "DEFENSIVE" in full[sep:].upper()
    assert "player 1" in full


def test_strategy_descriptions_available():
    block = plugin_loader.strategy_descriptions().lower()
    assert "aggressive" in block and "defensive" in block


def test_strategy_names_returns_discovered_set():
    names = plugin_loader.strategy_names()
    assert set(names) >= {"balanced", "aggressive", "defensive"}
    assert "general" not in names  # scripts plugin is not a strategy


def test_build_system_prompt_renders_formation_and_keeps_guardrails():
    # defensive declares 2-1-1 (a solid two-defender block); its formation
    # posture line must render while the guardrails.md text stays untouched.
    full = plugin_loader.build_system_prompt("defensive", "DEF", 1)
    assert "2-1-1" in full
    assert "Formation" in full
    assert "{formation}" not in full
    # guardrails block is still present and intact.
    assert "JSON array" in full


def test_mid_aggressive_loads_position_file_and_composes_prompt():
    # The position prose for a mid + aggressive tick comes from
    # plugins/mid/aggressive.md; the composed prompt must carry BOTH the
    # guardrails block and aggressive's 1-0-3 formation line.
    skill = plugin_loader.load_skill_prompt("aggressive", "MID", 2)
    assert "midfielder" in skill.lower()
    assert "player 2" in skill
    assert "1-1-2" in skill  # aggressive formation substituted into {formation}
    assert "{formation}" not in skill and "{player_id}" not in skill

    full = plugin_loader.build_system_prompt("aggressive", "MID", 2)
    assert "JSON array" in full  # guardrails block present
    assert "1-1-2" in full
    assert "Formation" in full


def test_unknown_strategy_formation_defaults():
    from constants import DEFAULT_FORMATION

    full = plugin_loader.build_system_prompt("nonexistent", "GK", 0)
    assert DEFAULT_FORMATION in full
    assert "{formation}" not in full


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
    print(f"{len(fns)} tests passed")
