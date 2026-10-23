---
inclusion: auto
name: game-domain
description: Football match rules, agent commands, tactical MCP tools, the game-state shape, and the model policy. Load when working on gameplay logic, strategy prompts, skills, the planner, parsing, or anything about how agents play the match.
---

# Game Domain (loaded for gameplay/strategy/prompt work)

This file is the single source of truth for how the match works. Where it describes
commands or state, it mirrors the code — keep it in sync with:
- `src/commons/parsing.py` (`VALID_COMMANDS`, parameter clamping/defaults)
- `src/commons/state.py` (how the game state is read and summarized)
- `src/agents/players/constants.py` (`MODEL_ID`, player→position map)

## The Game (fixed rules)
- 5v5. Always field 5 players: `0=GK, 1=DEF, 2=MID, 3=FWD1, 4=FWD2`. Strategy is chosen
  per tick; all five players are always created.
- Field: `x ∈ [-55, +55]`, `y ∈ [-35, +35]`. Team 0 (HOME) attacks +x and defends the
  goal at `x=-55`; Team 1 (AWAY) attacks -x and defends the goal at `x=+55`.
- Continuous play — the ball never leaves the field. No throw-ins, corners, or goal kicks.
- After a goal, all players reset to start positions and the conceding team kicks off
  from center.
- Cadence: ~1 invocation every 2s per agent; 5s decision timeout. If an agent does not
  answer in time, its **last command repeats**. Latency is therefore competitive: a slow
  tick costs a decision.
- Every agent returns a JSON array containing **exactly ONE** command object for its own
  player. The parser forces the correct `teamId`/`playerId` onto the command, so the model
  does not need to set them.

## Commands

Each command is `{"commandType": NAME, "parameters": { ... }}`. Only the command types in
`VALID_COMMANDS` (parsing.py) are accepted; anything else is dropped. The four groups below
cover every valid type.

### Movement
| Command | Parameters | Notes |
|---|---|---|
| `MOVE_TO` | `target_x`, `target_y`, `sprint` (bool) | `target_x` clamped to [-55,55], `target_y` to [-35,35] by the parser. |
| `FOLLOW_PLAYER` | `target_player_id`, `target_team`, `distance` | Shadow a player at a given spacing. |

### Attacking (require possession)
| Command | Parameters | Notes |
|---|---|---|
| `SHOOT` | `aim_location`, `power` | Prefer `evaluate_shot` before a long attempt. |
| `PASS` | `target_player_id`, `type` | If `target_player_id` is missing, the parser defaults it to a forward (3, or 4 if the passer is 3). |
| `GK_DISTRIBUTE` | `target_player_id`, `method` | Goalkeeper restart/distribution. Same missing-target default as `PASS`. |

### Defensive
| Command | Parameters | Notes |
|---|---|---|
| `PRESS_BALL` | `intensity` | Close down the ball carrier. |
| `MARK` | `target_player_id`, `tightness` | Missing `target_player_id` defaults to `0` (opponent GK) — almost never the right mark, so set it explicitly. |
| `INTERCEPT` | `aggressive` (bool) | Cut a passing or dribbling lane. |
| `SLIDE_TACKLE` | `target_player_id` | Missing target defaults to `-1`, meaning "the ball carrier". |

### Tactical / Control
| Command | Parameters | Notes |
|---|---|---|
| `SET_STANCE` | `stance: 0=Balanced, 1=Attack, 2=Defend` | Posture only; does not move the player. |
| `CLEAR_OVERRIDE` | — | Drop a manual override, return to default behaviour. |
| `RESET` | — | Reset the player's command state. |

- **Commands persist** until overridden or cleared. A single `SET_STANCE` keeps applying
  every tick after it is issued.
- Parser recovery: the model may emit Python-flavoured JSON (`True`/`False`/`None`, a
  trailing comma, or a ```` ```json ```` fence). `parsing.py` recovers these rather than
  dropping the command. Prose that merely contains a word like `True`, or brackets in the
  text, is left untouched and never corrupts a real command.

## Game State (payload shape)

The invocation payload carries `{ prompt: { teamId, gameState, myPlayers? } }`. `state.py`
summarizes `gameState` into the text the model sees. Two server formats are supported
transparently — do not assume one:

- **New format:** players use `agentId` (e.g. `"agentId_3"`) and `teamCode` (`"home"`/
  `"away"`); the ball uses `possessionAgentId` + `isFree`.
- **Old format:** players use numeric `playerId` and `teamId`; the ball uses
  `possessionPlayerId` (+ optional `possessionTeamId`).

```jsonc
{
  "tick": 150,
  "gameTime": 120.5,              // seconds
  "playMode": "OPEN_PLAY",
  "modeTeamId": null,
  "score": { "home": 1, "away": 0 },
  "ball": {
    "position": { "x": 15.3, "y": -5.2, "z": 0 },
    "velocity": { "x": 0, "y": 0, "z": 0 },
    "isFree": false,              // authoritative; honor it over inference
    "possessionAgentId": "agentId_3"
  },
  "players": [
    {
      "agentId": "agentId_3",     // index 0-4 parsed from the suffix
      "teamCode": "home",         // compared case-insensitively
      "position": { "x": 14, "y": -5 },
      "velocity": { "x": 2, "y": 0 },
      "orientation": 0,
      "stamina": 0.65,            // FRACTION 0.0-1.0, not 0-100
      "currentAction": 5,
      "lastAction": "DribbleTo",
      "speed": 1.5,
      "isSprinting": true
    }
    // ... 10 entries total: 5 home + 5 away
  ],
  "teamChat": []
}
```

Gotchas that the code handles deliberately — respect them when editing state/prompt logic:
- **`stamina` is a 0.0-1.0 fraction.** Rendering it as an integer or rounding to one digit
  collapses it to 0/1 and hides real stamina.
- **`teamCode` case varies** (`HOME`/`home`). Compare case-insensitively, or an agent's own
  player drops out of its prompt and teammates read as opponents.
- **`agentId` is NOT unique across teams** — `agentId_N` appears once per team. Identify a
  player by index **and** team (`holder_is_me`), never by index alone, or a player can act
  on a ball the opposing same-index player holds.
- **`isFree` is authoritative.** A possession claim that cannot be resolved is reported as
  `unknown`, never as `free`, so a carrier is not told to chase a ball it already holds.

## Tactical Tools (MCP Gateway)

Deterministic tools the agent calls instead of guessing. Force tool use before long shots
or blind passes — this is the biggest competitive lever, since it replaces a small model's
guess with real math:
- `evaluate_shot` — is this shot worth taking?
- `calculate_pass_options` — which passes are open and valuable?
- `find_open_space` — where to move to be useful?
- `get_defensive_assignment` — who to mark / cover.

Source of truth: pure functions in `src/plugins/general/scripts/`; the Lambda wrappers in
`src/agents/players/gateway_tools/` are thin adapters, not logic.

## Model Policy
- Nova Micro (`us.amazon.nova-micro-v1:0`) for ALL agents and the planner until capacity
  for larger models is confirmed. Single source of truth: `src/agents/players/constants.py`
  (`MODEL_ID`). Change it there, nowhere else.

## Formations

A formation distributes the four OUTFIELD players as `DEF-MID-FWD` (the GK is always
fielded and is not counted). All four numbers sum to 4. Formation is a tactical lever a
strategy can set — e.g. a defensive strategy leans on back-heavy shapes, an aggressive one
on forward-heavy shapes.

Known formations (name → DEF-MID-FWD distribution of the 4 outfield players):
- `0-4-0` — all four in midfield (control the centre)
- `1-0-3` — one back, three forward (all-out attack)
- `1-1-2` — one back, one mid, two forward (attacking)
- `1-1-1-1` — spread across all lines (balanced, staggered)
- `1-2-1` — one back, two mid, one forward (balanced, midfield-anchored)
- `2-0-2` — two back, two forward (split, direct)
- `2-1-1` — two back, one mid, one forward (balanced-defensive)
- `3-0-1` — three back, one forward (park the bus, counter)

Notes for strategy/prompt work:
- The GK (player 0) is fixed and NOT part of the formation count — formations only arrange
  players 1-4.
- Formation choice should follow the same per-tick, state-aware logic as strategy
  (scoreline, clock, possession): chase the game → forward-heavy; protect a lead →
  back-heavy. Keep it inside the tick budget; never block on it.

## Strategy selection
- The planner reads the `description` field in each `src/plugins/<strategy>/skill.md` to
  choose a strategy per tick. Keep those descriptions accurate and decision-relevant — the
  planner's choice is only as good as the descriptions it compares.
- Strategies today: `balanced`, `aggressive`, `defensive`, each with a `skill.md` plus one
  prompt per position (`gk/def/mid/fwd1/fwd2.md`). Adding a strategy is additive: drop a
  new folder with those files — no code change (the registry discovers it by scanning).
- Fixed rules every agent must always obey live in `src/governance/guardrails.md` and are
  prepended to every system prompt.
