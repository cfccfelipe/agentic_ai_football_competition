# Match Trace Findings — Why We Lost 0-1 (CloudWatch diagnostic)

Read-only investigation of real Bedrock AgentCore CloudWatch traces for OUR 5 runtimes
(`TeamUnified_ai_*`, all version 5), region us-east-1, account 937592087229. This report
feeds the markdown-tuning workflow. Nothing was edited; no AWS resources changed.

## Which traces were analyzed

The specific original 0-1 traces have partly rotated, but the **two most recent full
matches** are present and our team played one as HOME and one as AWAY — matching the
user's "en ambos hemos perdido 0-1". I pulled the complete `runtime-logs-*` streams for all
five positions of both:

- **HOME match** — session `effbb829-acfd-4133-a18b-260124f52b8a`, our agents on **team0**
  (HOME, attacks +x, defends goal at x=-55), pos0-4, ~14:43-14:48 UTC on 2026-10-23.
  Line counts: GK 1420, DEF 1477, MID 1417, FWD1 1482, FWD2 1465.
- **AWAY match** — session `a016c546-4b5f-444e-a2b3-a74972956101`, our agents on **team1**
  (AWAY, attacks -x, defends goal at x=+55), pos0-4, ~14:51 UTC. Line counts GK 1064, DEF
  1033, MID 1017, FWD1 1042, FWD2 1051.

The `otel-rt-logs`/`spans` streams exist but the structured per-tick decisions live in the
`runtime-logs-<session>-teamN-posK` streams, which is what I analyzed.

---

## TL;DR — the single biggest finding

**Our agents almost never acted on an LLM decision. On 85-100% of ticks the model output
failed to parse and the rule-based FALLBACK ran instead.** The root cause is a
prompt-templating bug: the few-shot example in every position prompt is written with
doubled braces (`{{ ... }}`) for Python `str.format`, but `plugin_loader.load_skill_prompt`
fills placeholders with plain `str.replace("{player_id}", ...)` / `str.replace("{formation}",
...)` — it **never calls `.format()`**, so the doubled braces are never collapsed. The model
is shown a literal `[{{"commandType":"SHOOT",...{{"aim_location":"TR"...}}]` as its template,
copies that malformed shape back (prefixed with the strategy name, e.g.
`aggressive[{{...}}]`), and `parse_commands` rejects it → `"LLM parse failed, using
fallback."` fires every tick.

Everything the tuning workflow wants to fix (blind shots to a fixed corner, over-pressing,
under-passing, no tool use) is therefore being produced by the **fallback config**, not by
the prompts — because the prompts are not reaching the pitch. Fixing the templating is the
prerequisite for any markdown tuning to have an effect.

Evidence (per-tick, both matches):

| Agent | `LLM parse failed, using fallback` | `LLM returned N commands` (success) | Fallback share |
|---|---|---|---|
| HOME GK   | 166 | 10 | ~94% |
| HOME DEF  | 182 | 0  | 100% |
| HOME MID  | 160 | 16 | ~91% |
| HOME FWD1 | 180 | 4  | ~98% |
| HOME FWD2 | 176 | 6  | ~97% |
| AWAY GK   | 128 | 2  | ~98% |
| AWAY DEF  | 124 | 4  | ~97% |
| AWAY MID  | 114 | 12 | ~90% |
| AWAY FWD1 | 126 | 2  | ~98% |
| AWAY FWD2 | 126 | 4  | ~97% |

Representative log line (HOME FWD1, every tick, `unified_agent.py:199`):

> `{"level": "WARNING", "message": "LLM parse failed, using fallback.", ... "sessionId":
> "effbb829-...-team0-pos3"}`

The model's echoed output (a 6,613-char accumulation seen in HOME FWD1) starts:

> `aggressive[{{"commandType":"MOVE_TO","playerId":3,"parameters":{{"x":-10,"y":0}},"duration":0}}]aggressive[{{"commandType":"SHOOT","playerId":3,"parameters":{{"aim_location":"TR","power":1.0}},"duration":0}}]...`

Note the doubled `{{`/`}}` and the `aggressive`/`defensive`/`balanced` prefixes — the model
is parroting the raw template, confirming the placeholder is never collapsed.

Source confirmation — `src/agents/players/plugin_loader.py`, `load_skill_prompt`:

```python
return (
    template
    .replace("{player_id}", str(player_id))
    .replace("{formation}", formation)
)
```

and the example line in `src/plugins/fwd1/aggressive.md`:

```
Example: [{{"commandType":"SHOOT","playerId":{player_id},"parameters":{{"aim_location":"TR","power":1.0}},"duration":0}}]
```

The `{player_id}` single-brace token IS replaced, but the `{{` `}}` around the JSON are
left literal — invalid JSON for the parser.

---

## Q1 — STRATEGY: what did the planner pick, and was it sensible?

The planner overwhelmingly picked **`aggressive`** for every position in both matches, with
a small number of `defensive` and almost no `balanced`:

- HOME: GK aggressive=154/defensive=22; DEF aggressive=162/defensive=20; MID
  aggressive=148/defensive=22/balanced=6; FWD1 aggressive=158/defensive=26; FWD2
  aggressive=160/defensive=22.
- AWAY: every position ~aggressive=122-128 with only 0-8 defensive, 0-2 balanced.

Log line (`unified_agent.py:160`): `"FWD1 agent: team 0, player 3, strategy aggressive"`.

Assessment: the planner leaned "aggressive" almost the whole match — the mirror image of
the user's earlier "defensive at 1-0, gameTime 120" complaint, but the same underlying
problem: **the strategy mix is not tracking the game state well and is close to a constant.**
However, this is a secondary issue right now, because (see TL;DR) the chosen strategy's
prompt barely reaches the model — the fallback ignores the strategy label entirely and runs
the same per-position rules regardless. **Strategy tuning cannot help until the prompt
actually parses.** The one place the strategy still matters even under fallback is formation
(set by the planner, applied by the engine), so an always-aggressive `1-0-3` shape left us
thin at the back — consistent with "mucho tiempo en zona defensiva hasta que nos marcaron"
and conceding a 4th-minute goal on a counter.

## Q2 — COMMANDS emitted per position (and why 6 shots, 0 on target)

Command types observed in the logs (these are the commands that were logged; most ticks
went through the fallback, whose output is not individually logged as `commandType` unless
it was the LLM path). Where `commandType` appears:

- HOME GK: MOVE_TO=15, INTERCEPT=13, GK_DISTRIBUTE=2, PASS=2, PRESS_BALL=1.
- HOME DEF: MOVE_TO=52, PASS=8, MARK=2, CARRY_FORWARD=1 (note `CARRY_FORWARD` is **not a
  valid command** per the domain spec — another sign of the model inventing commands that
  get dropped).
- HOME FWD1: MOVE_TO=47, **SHOOT=11**, MARK=2, PRESS_BALL=1, SET_STANCE=1, INTERCEPT=1, PASS=1.
- AWAY FWD1: MOVE_TO=40, **SHOOT=10**, PRESS_BALL=4, INTERCEPT=1.
- AWAY FWD2: **SHOOT=12**, MOVE_TO=11, PRESS_BALL=2.

The FWDs DO emit SHOOT, and every shot uses a **fixed corner + near-max power**:

- FWD1 (both matches): `"aim_location":"TR","power":1.0"` on essentially every shot
  (occasional `BR`/`0.8`, `TR`/`0.5`).
- FWD2 (away): `"aim_location":"BL","power":1.0"` / `"BL","power":0.5"`.

Why 6 shots, 0 on target:
1. **The aim is a hardcoded constant, not situational.** It comes from the broken prompt
   example (`TR` for FWD1, `BL` for FWD2) AND from the fallback config
   (`src/commons/fallback.py`: `FWD1_CONFIG.shoot_aim="TR"`, `FWD2_CONFIG.shoot_aim="BL"`).
   A fixed corner with no relation to keeper position or shot angle is a coin-flip at best.
2. **`aim_location` is never explained relative to attacking direction.** The label set
   (`TR/TL/BR/BL`) is given no meaning in the prompt or state summary, so "TR" is applied
   identically whether attacking the +x goal (HOME) or the -x goal (AWAY). At least one of
   those is the wrong half of the goal mouth.
3. **Speculative long shots.** `fwd1/aggressive.md` says: *"SHOOT at every possible
   opportunity — from any distance within ~40 units. Take speculative shots... Power shots
   at 1.0 — always shoot with maximum power."* The fallback only shoots inside 25 units of
   the opp goal, but when the LLM path does fire it shoots from range at power 1.0. Low-
   percentage attempts from bad positions → 0 on target.

## Q3 — TOOL USE: do agents call the tactical MCP tools?

**No. Zero tactical-tool invocations in either match.** In HOME FWD1: `tools/call`
occurrences = 0, `toolUse`/`tool_use` = 0, while raw MCP POSTs to the gateway = 187. Those
187 POSTs are only the connection handshake — each tick shows the pattern:

> `HTTP Request: POST https://teamunified-tactical-tools-...gateway...amazonaws.com/mcp
> "HTTP/1.1 200 OK"` → `Negotiated protocol version: 2025-03-26` → `... "HTTP/1.1 202
> Accepted"`

i.e. connect + `initialize`/`tools/list`, never a `tools/call`. The names
`evaluate_shot`, `calculate_pass_options`, `find_open_space`, `get_defensive_assignment`
appear **0 times** in the decision logs. The agents connect to the gateway and list tools,
then never use them — so every shot/pass/move decision is a raw guess (and usually the
fallback's guess). Contributing cause: the model is stuck echoing the malformed example
instead of reasoning, so it never reaches a tool-calling step. Also note the per-tick
Strands warning `tool=<_TimeoutTool object> | unrecognized tool specification` (x5/tick) —
benign (the timeout guard wrapper isn't a real tool), but it means the only "tools" the
registry logs about are internal guards, not the tactical ones.

## Q4 — SITUATIONAL AWARENESS failures

The state summary the model receives (`src/commons/state.py::summarize_state`) is actually
decent and direction-correct: it emits `Your goal at x=-55 | Opponent goal at x=55`,
`distOppGoal=...`, teammate/opponent coordinates, and `hasBall=True/False`. BUT:

- **No explicit ATTACK vs DEFENSE phase label.** The model must infer phase from `held by`
  + `hasBall`. For Nova Micro that inference is unreliable, and with the prompt broken the
  model isn't reasoning over the state at all — it copies the example. This matches the
  user's complaint that agents don't know when it's attack vs defense.
- **`aim_location` semantics are undefined** relative to which goal the player attacks (see
  Q2) — the clearest "aiming the wrong way" risk: a HOME and an AWAY forward both shoot
  "TR" even though their target goals are on opposite touchlines.
- **MY vs OPP / teammate-vs-opponent confusion risk in the prompt, not the fallback.** The
  fallback resolves identity correctly (`holder_is_me`, `_is_my_team`, per-team goal via
  `get_goal_positions`), so fallback passes/marks target the right team. The exposure is in
  the LLM path: the DEF emitted `CARRY_FORWARD` and MARK with raw ids, and the prompt
  examples use bare `target_player_id` values (`1`, `2`) with no "these indices are YOUR
  teammates / those are opponents" framing. Because `agentId_N` is not unique across teams,
  any LLM pass/mark that reaches the pitch can hit the wrong same-index player.
- **Note on evidence limits:** the per-tick state summary is passed to the agent but is NOT
  logged (0 matches for score/possession/zone text in the streams), so I cannot quote the
  exact user-prompt the model saw per tick. The awareness gaps above are inferred from the
  prompt files, the state-summary code, and the model's echoed outputs — not from a logged
  prompt/response pair. That is the one question I could only answer from code + echoes
  rather than a logged state-vs-decision pair.

## Q5 — COMMAND MIX vs the match report (Press 36 / Move 34 / Pass 7 / Shoot 4)

The per-agent logs corroborate the report's shape:

- **Move dominates** (MOVE_TO is the most common logged command for GK/DEF/FWD1/FWD2) and
  **Press is heavy** — consistent with Move 34% + Press 36%. The aggressive prompt
  (*"PRESS_BALL at maximum intensity"*) and the fallback's press rule
  (`press_distance=20, press_intensity=0.7`) both push pressing; whenever an opponent is
  within 20 units and we don't have the ball, the fallback presses. With an always-
  aggressive `1-0-3` and bodies forward, that produces the over-pressing the report flags.
- **Pass is starved** (7%). Only the GK/DEF fallback and `SHOOT_OR_PASS` (MID) emit PASS,
  and only when they already hold the ball; forwards almost never pass (FWD1 PASS=1 all
  match). This matches the coach note: *"increase PASS volume to build possession."*
- **Shoot ~4%** — FWD1/FWD2/MID SHOOT counts (10-12 each) line up with 17 total shoot
  commands / 455.

Agents over-pressing: both FWDs and the MID (aggressive press rules + forward formation).
Agents under-passing: the FWDs (SHOOT_OR_ADVANCE never passes unless blocked) and the team
as a whole (no tool-assisted pass selection because `calculate_pass_options` is never
called).

## Q6 — LATENCY / health

**No crashes, timeouts, or hard errors in either match.** Every "error-ish" line
(440-460/agent HOME, 315-325/agent AWAY) is the single benign Strands warning
`unrecognized tool specification` for the internal `_TimeoutTool` — there are **0**
tracebacks, 0 `TimeoutError`, 0 `ExpiredToken`, 0 `tick exceeded Ns` fallbacks. The only
"fallback" firing is the **parse** fallback (`LLM parse failed`), which is a correctness
bug, not a health failure — the process answered every tick on time, which is exactly why
the report shows 100% success with 600-1500ms latencies. (The earlier init crash the user
pasted — `FileNotFoundError: /governance/guardrails.md` — is NOT present in these v5
streams; initialization now succeeds.)

---

## Per-position summary (right / wrong)

- **GK (player 0):** Right — stays home, distributes, intercepts; direction-correct
  fallback; MVP-level reliability. Wrong — almost never runs an LLM decision (94-98%
  fallback); no tool use.
- **DEF (player 1):** Right — marks the most dangerous opponent and passes out via a
  sound fallback. Wrong — emitted invalid `CARRY_FORWARD` (dropped); 100% fallback in HOME;
  always-aggressive formation left the back line thin for the early counter we conceded.
- **MID (player 2):** Right — most LLM successes of any agent (12-16), does PASS and SHOOT.
  Wrong — still ~90% fallback; shoots to fixed `TR`; no `calculate_pass_options`.
- **FWD1 (player 3):** Right — does get forward and shoot. Wrong — every shot `TR`/power
  1.0 regardless of keeper/angle/attack direction; speculative long shots; essentially
  never passes; 98% fallback; no `evaluate_shot`.
- **FWD2 (player 4):** Right — gets forward and shoots. Wrong — every shot `BL`/power 1.0
  (the mirror constant); same no-pass, no-tool, 97% fallback issues.

---

## Prioritized fixes for the markdown / config tuning

**P0 — Make the prompt actually parse (prerequisite; without this, nothing below matters).**
The example line in every `src/plugins/<pos>/<strategy>.md` is written for `str.format` but
the loader uses `str.replace`. Two equivalent fixes, pick one and keep it consistent across
all 15 prompt files:
  - Rewrite the `Example:` lines to use SINGLE braces (`[{"commandType":...,"parameters":{...}}]`)
    so plain `str.replace` leaves valid JSON; OR
  - (code change, out of scope for md tuning) switch `load_skill_prompt` to `.format()`.
  Recommended for the md-tuning workflow: single-brace examples. Also add 1-2 **correct**
  worked examples per position showing the exact JSON the parser accepts.

**P1 — Fix shooting (the 0-on-target problem).**
  - Make `aim_location` situational and define its meaning relative to the attacking goal
    in the prompt (e.g. "aim to the far post away from the keeper; your target goal is the
    opponent goal shown in state as 'Opponent goal at x=...'"). Stop hardcoding `TR`/`BL`.
  - Require `evaluate_shot` before any shot beyond close range, and only SHOOT when it says
    the chance is worth it; otherwise pass or carry. Add explicit distance gating in prose
    (shoot inside ~18-22 units, not "within ~40").
  - Drop "always power 1.0 / speculative shots from any distance" from `fwd*/aggressive.md`.
  - Align the fallback defaults too (`FWD1_CONFIG.shoot_aim`, `FWD2_CONFIG.shoot_aim`,
    `MID_CONFIG.shoot_aim`) so the fallback doesn't re-introduce the fixed corner — ideally
    make aim a function of attacking direction rather than a constant.

**P2 — Add explicit ATTACK vs DEFENSE phase + identity discipline to prompts/guardrails.**
  - Give the model a clear phase rule: "If `hasBall=True` or a teammate holds the ball →
    ATTACK; if an opponent holds it or the ball is near YOUR goal (x≈your_goal_x) → DEFEND."
    Consider surfacing an explicit `Phase: ATTACK/DEFEND` line in `summarize_state`.
  - State plainly in the prompt that teammate ids are YOUR team's 0-4 and opponents are the
    other team's 0-4 with the same numbers, and that `agentId_N` is per-team — never pass to
    or mark a player without confirming team. Encourage `get_defensive_assignment` /
    `calculate_pass_options` to pick targets instead of guessing ids.

**P3 — Rebalance the command mix: less press, more pass.**
  - Soften the aggressive press language ("maximum intensity, immediately") and add a
    possession-first directive: when we hold the ball, prefer PASS to keep possession;
    press only when close to the ball AND out of possession.
  - Require `calculate_pass_options` before passing so passes go to open teammates.

**P4 — Fix the strategy/formation mix so we don't sit back then get countered.**
  - Tune the planner strategy descriptions (and the planner logic, separately) so a level
    or early scoreline uses `balanced` (1-2-1), not a constant aggressive `1-0-3` that left
    us exposed for the 4th-minute goal. Ensure `gameTime` is read as SECONDS.

**P5 — Housekeeping.** Remove the invalid `CARRY_FORWARD` from any prompt text/examples so
the model stops emitting a command the parser drops.

### Fix order rationale
P0 unblocks everything (the prompts are currently inert). P1 and P2 directly address the
two user complaints (FWDs not scoring; agents not knowing attack/defense, friend/foe). P3
addresses the coach note (less press, more pass). P4 addresses the "sat in our zone until we
conceded" observation. P5 is cleanup.
