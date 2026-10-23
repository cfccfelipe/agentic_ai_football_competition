"""Tests for plugin_loader — guardrails + strategy/position prompt composition."""

import plugin_loader


def test_guardrails_loaded():
    g = plugin_loader.load_guardrails()
    assert "Guardrails" in g or "guardrails" in g.lower()
    assert "JSON array" in g  # response-format rule is present


def test_skill_prompt_resolves_player_id():
    prompt = plugin_loader.load_skill_prompt("aggressive", "FWD1", 3)
    assert "{player_id}" not in prompt
    assert "player 3" in prompt


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


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
    print(f"{len(fns)} tests passed")
