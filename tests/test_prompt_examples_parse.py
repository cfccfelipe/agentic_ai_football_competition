"""P0 guard: every rendered position/strategy Example must be VALID JSON.

Root cause of the trace failure: the `Example:` line in each
src/plugins/<pos>/<strategy>.md used DOUBLED braces ({{ }}), but
plugin_loader.load_skill_prompt only str.replaces {player_id}/{formation} and
never .format()s — so {{/}} reached the model verbatim as invalid JSON, the
model parroted the broken shape, parse_commands rejected it, and the agent fell
back every tick.

This test renders every position x strategy body and asserts the Example array
parses with json.loads, with NO leftover {{/}} and NO unreplaced placeholders.
It FAILS on the old doubled-brace templates and PASSES after the single-brace fix.
"""

import json

import pytest

import plugin_loader
from parsing import VALID_COMMANDS

# Sample player id per position (0 GK, 1 DEF, 2 MID, 3 FWD1, 4 FWD2).
_SAMPLE_IDS = {"GK": 0, "DEF": 1, "MID": 2, "FWD1": 3, "FWD2": 4}

_POSITIONS = tuple(_SAMPLE_IDS)
_STRATEGIES = plugin_loader.strategy_names()


def _example_array(rendered: str) -> str:
    """Return the JSON text following the `Example:` prefix in a rendered body."""
    lines = [l for l in rendered.splitlines() if l.startswith("Example:")]
    assert lines, "rendered body has no 'Example:' line"
    return lines[0].split("Example:", 1)[1].strip()


@pytest.mark.parametrize("position", _POSITIONS)
@pytest.mark.parametrize("strategy", _STRATEGIES)
def test_rendered_example_is_valid_json(position, strategy):
    player_id = _SAMPLE_IDS[position]
    rendered = plugin_loader.load_skill_prompt(strategy, position, player_id)

    # (a) no doubled braces anywhere in the rendered body
    assert "{{" not in rendered, f"{position}/{strategy}: leftover '{{{{'"
    assert "}}" not in rendered, f"{position}/{strategy}: leftover '}}}}'"

    # (b) no unreplaced single-token placeholders
    assert "{player_id}" not in rendered, f"{position}/{strategy}: unreplaced {{player_id}}"
    assert "{formation}" not in rendered, f"{position}/{strategy}: unreplaced {{formation}}"

    # (c) the Example array parses and is a single valid command object
    arr = json.loads(_example_array(rendered))
    assert isinstance(arr, list) and len(arr) == 1
    cmd = arr[0]
    assert isinstance(cmd, dict)
    assert cmd["commandType"] in VALID_COMMANDS
    assert isinstance(cmd["playerId"], int) and cmd["playerId"] == player_id
    assert isinstance(cmd["parameters"], dict)
