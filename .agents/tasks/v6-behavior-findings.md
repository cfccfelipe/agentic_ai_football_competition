# v6 Behavior Findings — Real CloudWatch Trace Diagnostic (READ-ONLY)

Investigation of the deployed v6 `TeamUnified_ai_*` runtimes (region us-east-1, account
937592087229), after the P0 prompt-templating fix. No code or AWS resources were changed.
All evidence below is quoted from real CloudWatch `runtime-logs-*` streams.

---

## 0. CRITICAL CAVEAT ON WHAT v6 TRACES EXIST

There is **no full 90+ tick scheduled v6 MATCH in CloudWatch**. The "2-1" / "0-1" scoreline
aggregates described in the task came from the game-platform UI, but the deployed v6
runtimes only produced **warm-up / continuous-invocation streams** after the deploy (16:22–
16:35 UTC on 2026-10-23). `describe-log-streams` reports a tiny `firstEvent→lastEvent` span
(0–0.9s) for these, but each stream actually contains **134–160 real per-tick LLM
decisions** (the events were ingested in a burst). They are therefore a genuine, tick-dense
sample of **v6 LLM behavior** and are what this report analyzes for execution.

v6 streams analyzed (one representative full stream per position; all `TeamUnified_ai_*`):

| Tag | Position/Team | Session | Decisions |
|---|---|---|---|
| v6_gk_eab  | GK team0 (HOME)  | `eab3677b…-team0-pos0` | 160 |
| v6_gk_a6d  | GK team1 (AWAY)  | `a6db3463…-team1-pos0` | 158 |
| v6_def_eab | DEF team0 (HOME) | `eab3677b…-team0-pos1` | 156 |
| v6_mid_eab | MID team0 (HOME) | `eab3677b…-team0-pos2` | 150 |
| v6_fwd1_dcc| FWD1 team0 (HOME)| `dcc63f78…-team0-pos3` | 134 |
| v6_fwd2_a6d| FWD2 team1 (AWAY)| `a6db3463…-team1-pos4` | 160 |

The only tick-dense **full matches** in CloudWatch are the two **v5** sessions already
covered in `match-trace-findings.md`: `effbb829` (team0/HOME, 14:43–14:48) and `a016c546`
(team1/AWAY, 14:51–14:55). Those ran the FALLBACK on 85–100% of ticks, so they reflect
`fallback.py`, not the current v6 LLM. Where a behavior is only observable in a full match
(e.g. possession-dependent pressing), I flag that it is v5/fallback evidence.

---

## (a) P0 VERIFICATION — IS THE LLM IN CONTROL NOW?

**YES. The P0 fix works. The LLM path now drives ~95–100% of ticks; the rule-based
fallback is no longer firing on nearly every tick.** Complete reversal of v5.

Per-agent v6 counts (`LLM returned N commands` = success vs `LLM parse failed, using
fallback`):

| Agent (v6) | LLM success | parse→fallback | LLM share |
|---|---|---|---|
| GK team0   | 160 | 0 | 100% |
| GK team1   | 158 | 0 | 100% |
| DEF team0  | 156 | 0 | 100% |
| MID team0  | 150 | 2 | ~99% |
| FWD1 team0 | 134 | 8 | ~94% |
| FWD2 team1 | 160 | 2 | ~99% |

Compare the v5 full matches (same agents, prior deploy): FWD1 180 fallback / 4 LLM, FWD2
176/6, GK 166/10, DEF 182/0, MID 160/16 — i.e. **85–100% fallback**. The single P0 fix
(single-brace `Example:` lines so `str.replace` yields valid JSON) flipped this.

Evidence the braces now collapse and parse (GK team0, real echo):
> `aggressive[{"commandType":"INTERCEPT","playerId":0,"parameters":{},"duration":0}]`

followed by `{"message": "LLM returned 1 commands: ['INTERCEPT']"}`. The strategy-name
prefix (`aggressive`/`balanced`) still leaks into the raw output, but the tolerant scanner
now finds the valid `[{…}]` span inside it, so it parses. (Cosmetic; see item (h) NIT.)

### Tools — are the tactical MCP tools actually CALLED?
**No. Still zero real tool calls — and the root cause is now CONFIRMED to be a code bug that
drops every tactical tool from the Strands registry (see item (a2) below).** Every v6 stream
shows `tools/call POSTs = 0`. The only tool-name mentions are `evaluate_shot` appearing 1–2×
as the tool **spec/catalog listing**, never a `tools/call`. `calculate_pass_options`,
`find_open_space`, `get_defensive_assignment` appear **0 times** as calls. **So every shoot/
pass/move is an un-assisted model guess** — "decide with facts" is currently impossible. This
is the single biggest competitive lever and it is dead; it underlies the shooting-inversion
and pass-starvation findings.

---

## (a2) CONFIRMED CODE BUG — the per-tool timeout wrapper drops EVERY tactical tool  *(HIGH PRIORITY)*

**This is why 0 tactical tools are ever called. It is a LEVEL-2 EXECUTION defect in CODE
(`runtime_guards.py` + `unified_agent.py`), not a prompt problem, and it disables the entire
tactical-tools advantage regardless of how the prompts are tuned.**

**Log evidence (GK team0, v6), fires per tick, 5× (once per wrapped tool):**
> `WARNING [strands.tools.registry] [registry.py:150] tool=<runtime_guards._TimeoutTool object at 0x…> | unrecognized tool specification`

**Root cause (confirmed by reading the deployed Strands source + our code):**
- `unified_agent.py::register` wraps **every** fetched MCP tool:
  `cached_tools = [wrap_tool_with_timeout(t, PER_TOOL_TIMEOUT_SECONDS) for t in cached_tools]`,
  and passes that list as `tools=` to the Strands `Agent`.
- `wrap_tool_with_timeout` returns a `runtime_guards._TimeoutTool`, which is a **plain
  `object`** that merely copies `tool_name`/`tool_spec` attributes and delegates via
  `__getattr__`.
- Strands' registry (`strands/tools/registry.py`, the staged deployed copy) decides what a
  tool is by **`isinstance` checks**, not duck-typing. Its `add_tool` matches: dict spec,
  module, **`isinstance(tool, AgentTool)` (Case 5, which covers `@tool`)**, nested iterable,
  `ToolProvider`, or `AgentBase.as_tool()`. Anything else hits the final
  `else: logger.warning("tool=<%s> | unrecognized tool specification", tool)` and is
  **silently dropped**.
- The raw MCP tactical tools are `class MCPAgentTool(AgentTool)` — so **unwrapped they WOULD
  register** via Case 5. But `_TimeoutTool` is **not** an `AgentTool` subclass, so
  `isinstance(_TimeoutTool, AgentTool)` is False → it falls through to the `else` → dropped.

**Scope — is it every tool or some?** **Every** tactical tool. The wrapper is applied to the
whole `cached_tools` list unconditionally, the warning fires **5× per tick** (the GK's five
`unrecognized tool specification` lines each tick), and `tools/call POSTs = 0` across every
agent and both teams. No `tools/call` ever succeeds. (The "5" is the four tactical tools plus
one extra entry; all are wrapped and all are rejected.)

**Is the wrapper the cause, or does Strands reject for another reason?** The wrapper is the
sole cause. The identical tools without the wrapper are `AgentTool` instances that Strands
accepts; the only thing changed between "accepted" and "unrecognized" is the `_TimeoutTool`
box. Attribute mirroring (`tool_name`/`tool_spec`) does not help because the gate is
`isinstance`, not attribute presence.

**Fix direction (CODE, in scope for the follow-up — LEVEL 2):** make the per-tool timeout
preserve a VALID Strands tool spec that the registry accepts, WITHOUT losing the 3.5s tick
timeout or the 2-iteration cap. Two viable approaches:
1. **Subclass `AgentTool`** (or re-wrap with Strands' `@tool`/`AgentTool` API) so the wrapper
   IS an `AgentTool` with the same `tool_name`/`tool_spec` and an overridden invoke/stream
   path that applies `call_with_timeout`. Registry then accepts it via Case 5.
2. **Do not wrap for registration at all** — register the raw `MCPAgentTool`s so Strands sees
   valid specs, and enforce the 1s per-tool budget inside the call path (e.g. wrap the MCP
   client transport/invoke, or rely on the existing 3.5s tick wall-clock in `invoke()` which
   already bounds the whole tool+model turn).
Approach 1 is the most surgical and keeps the per-tool budget explicit.

**Test to add (follow-up):** assert that `wrap_tool_with_timeout(raw_mcp_tool, 1.0)` returns
an object for which `isinstance(result, AgentTool)` is True and that exposes the same
`tool_name` and a `tool_spec` the registry's `validate_tool_spec`/`normalize_tool_spec`
accepts — i.e. a wrapped tool still registers. Also assert the timeout still triggers the
benign error result on a slow tool.

**Dependency note:** items (c) pass-to-most-open, (c-shoot) require-evaluate_shot, and P5 all
depend on THIS fix landing first — requiring a tool in the prompt is useless while the tool is
dropped from the registry. Fix (a2) is the prerequisite for any tool-assisted play.

---

## Two-level lens used for every item below
- **LEVEL 1 (STRATEGY)** — was the planner's strategy/formation choice right for the
  situation? Fix layer = `src/plugins/strategies/*.md` descriptions and/or `planner.py`.
- **LEVEL 2 (EXECUTION)** — given the chosen strategy, was the per-tick command/target/
  zone/aim/phase correct? Fix layer = position `*.md` bodies, `fallback.py`, tool usage.
- **ATTRIBUTION** — is the bad execution the LLM's decision or the deterministic fallback?
  (In v6 the answer is almost always **the LLM**, because the fallback barely fires now.)

### Over-arching LEVEL-1 finding: the planner picks `aggressive` almost constantly
Strategy picks per v6 stream (`strategy X` log line counts):
- GK team0: **aggressive 134**, balanced 10, defensive 16
- GK team1: **aggressive 156**, balanced 2
- DEF team0: **aggressive 128**, balanced 26, defensive 2
- MID team0: **aggressive 130**, balanced 10, defensive 12
- FWD1 team0: **aggressive 132**, balanced 8, defensive 2
- FWD2 team1: **aggressive 160**, balanced 2

`aggressive` maps to formation **`1-0-3`** (one DEF, zero MID, three FWD — the thinnest
possible back line). Its description (`strategies/aggressive.md`) explicitly licenses the
pick when **"the score is level and we want to go and win it"** — which is true at kickoff
(0-0). So the planner picks the all-out shape at minute 0, which is the Level-1 root cause
of the minute-2–4 concessions (item d). This near-constant-aggressive is the single most
important Level-1 problem and it cascades into GK drift, DEF over-push, and thin defense.

---

## (b) STOP CONSTANT PRESSING / DEFEND WITH STRUCTURE  *(user's TOP goal)*

**LEVEL 1 verdict — WRONG.** The team is in `aggressive` (1-0-3) almost every tick, which
is a press-and-attack posture with no defensive block. There is no distinct "defend with
structure" shape being selected: `defensive` is `3-0-1` (reserved for "clear lead late",
never chosen early) and `balanced` is `1-2-1` (still only one defender). The planner never
settles into a structured mid-block.

**LEVEL 2 verdict — mostly the chase comes from INTERCEPT + MOVE, not PRESS_BALL, and it is
the LLM.** On the v6 LLM ticks, explicit `PRESS_BALL` is actually **low**: GK 0, DEF 2,
MID 4, FWD1 0, FWD2 12. The "constant chase" the match report shows (Press+Intercept ≈
48–54%) is dominated by **INTERCEPT**: AWAY GK emitted `INTERCEPT` on **154 of 158 ticks**,
FWD2 `INTERCEPT 46`. So the ball-magnet reflex is now expressed as INTERCEPT spam, decided
by the **LLM**, not by the fallback press rule.

**Anti-ball-magnet failure (same-tick collapse):** guardrails §5 already says "never have
two teammates press the same opponent," and MARK usage is tiny (DEF MARK 18, others 0–4).
The team does **not** "one presser + rest MARK/cover"; it has multiple players reflexively
INTERCEPTing/pressing. In v5 (fallback) the press came from `FallbackConfig.press_distance=20,
press_intensity≈0.7` firing whenever an opponent was within 20u and we lacked the ball — but
in v6 that fallback path barely runs, so **the fix layer is now the prompt, not fallback.py.**

**Fix layer:** (1) LEVEL-1 — add/clarify a true *defensive-structure* strategy: either remap
`balanced`→`2-1-1` and add a `2-1-1` mid-block, and make the planner pick it when not
chasing; (2) LEVEL-2 — in every position body + guardrail §5/§8, state the rule
explicitly: "When defending (OPP holds the ball), only the single closest player
PRESS_BALL/INTERCEPTs; everyone else MARK the nearest unmarked opponent or hold zone. Never
INTERCEPT as a per-tick reflex." The fallback press rule should also be softened later, but
it is secondary because the fallback rarely runs in v6.

---

## (c) PASS STARVATION (≈5%) — and NEW: passes are MALFORMED  *(Question A)*

**LEVEL 1 verdict — contributes.** `aggressive`/1-0-3 is a shoot-and-run posture; its body
text emphasizes shooting and high pressing over possession, so "pass to keep the ball" is
under-weighted at the strategy level.

**LEVEL 2 verdict — WRONG, and this is the decisive finding: the model DOES try to PASS, but
emits the WRONG PARAMETER KEYS, so the pass is silently defaulted/mis-targeted.** This is an
LLM execution bug, newly visible now that the LLM path runs.

The parser (`parsing.py`) expects `PASS` with `target_player_id` and `type`. The v6 model
instead emits, e.g. (MID team0, real echoes):
> `{"commandType":"PASS","playerId":2,"parameters":{"targetId":3,"passType":"THROUGH","power":0.8}}`
> `{"commandType":"PASS","playerId":2,"parameters":{"target":4,"pass_type":"BACK"}}`
> `{"commandType":"PASS","playerId":2,"parameters":{"targetPlayerId":3,"power":0.8}}`

DEF team0 is worse — it stuffs MOVE-style params into a PASS:
> `{"commandType":"PASS","playerId":1,"parameters":{"target_x":3.8,"target_y":0.1,"sprint":false}}`
> `{"commandType":"PASS","playerId":1,"parameters":{"target_teammate_id":2}}`
> `{"commandType":"PASS","playerId":1,"parameters":{"target_id":2,"sprint":false}}`

Because `target_player_id` is absent, `parsing.py::_tag_commands` **defaults it to a forward
(3, or 4 if the passer is 3)**. So every one of these passes is redirected to a FWD
regardless of who was open — i.e. **blind forced passes**, not possession play. The MID's
intended `target 4 / BACK` and the DEF's intended short outlet are lost.

`calculate_pass_options` is **never called** (tools/call=0), so the target is never chosen
from open lanes.

**Attribution:** LLM (the model picks PASS but with an invalid schema). **Fix layer:**
LEVEL-2 — in every position body, show the EXACT accepted PASS schema with a worked example
(`{"commandType":"PASS","parameters":{"target_player_id":2,"type":"GROUND"}}`) and
explicitly forbid `targetId/target/passType/power/target_x`. Require `calculate_pass_options`
before PASS and pass to the most-open returned teammate. LEVEL-1 — a possession-first
strategy/body so passing is actually wanted.

### Pass-to-most-open  *(item 5 / g)*
Not happening. Targets are either the parser's forced FWD default (above) or a fixed `id:2`/
`id:3`. No `calculate_pass_options` call, no "most unmarked teammate" logic in the LLM path.
Fix = require the tool + state "pass to the most OPEN teammate advancing toward the opponent
goal" in the bodies (LEVEL-2).

---

## (d) EARLY CONCESSIONS / FORMATION  *(Question C)*

**LEVEL 1 verdict — WRONG; this is the primary cause of the minute-2 goals.** At kickoff the
planner picks `aggressive` → `1-0-3` (one DEF, no holding MID). Both reported opponent goals
came at minute ~2 ("insufficient defensive positioning"), exactly what a 1-0-3 invites. The
rule-based fallback would pick `balanced` (1-2-1) at 0-0, but the **LLM planner overrides to
aggressive**, and even balanced has only ONE defender.

**Supporting execution evidence (LEVEL 2):** at HOME (attacks +x, own goal −55), the DEF's
v6 MOVE_TO target_x is **min −20, max +30, avg +13.1** — the lone defender is spending most
of its time in the **opponent half**, leaving nobody in front of our goal. The GK (own goal
−55) MOVE_TO target_x **avg +0.8, max +20** — it too is up around halfway. With a 1-0-3
shape and both the DEF and GK pushed up, the defensive third is empty on a turnover → a
2-minute counter scores.

**Formation recommendation (backed by the above):** default the non-chasing shape to
**`2-1-1` (two real defenders)**. Note a concrete gap: `2-1-1` is in `ALLOWED_FORMATIONS`
(constants.py) but **no strategy maps to it today** (aggressive=1-0-3, balanced=1-2-1,
defensive=3-0-1). So adopting it is a real change: remap `balanced.formation` to `2-1-1`
(or add a `structured`/`counter` strategy at `2-1-1`) and make the planner choose it at
level/early scorelines. Recommended mapping: defensive→`3-0-1` or `2-1-1`, balanced→`2-1-1`,
aggressive→`1-1-2` (not `1-0-3`, which is too thin even when chasing).

---

## (e) GK DISTRIBUTES UNDER PRESSURE  *(user complaint 1)*

**LEVEL 1 verdict — WRONG context.** The GK is almost always running the `aggressive`
sweeper-keeper prompt (GK team0: aggressive 134/160). That prompt's priority #1 is "If you
have the ball in defensive third → GK_DISTRIBUTE … to keep possession" with **no
opponent-proximity gate** — so the GK distributes regardless of pressure.

**LEVEL 2 verdict — WRONG, and it is the LLM.** In v6 the GK emitted `GK_DISTRIBUTE` on 40
of 160 ticks (GK team0), via the LLM path (no parse-fallback on that stream). Real echoes:
> `{"commandType":"GK_DISTRIBUTE","playerId":0,"parameters":{"target_player_id":4,"method":"PASS"}}`
> `{"commandType":"GK_DISTRIBUTE","playerId":0,"parameters":{"target_player_id":2,"method":"KICK"}}`

Two execution defects: (1) it distributes without checking opponent distance; (2) the
`method` is often `"PASS"`/`"SHORT_PASS"` — **not** the documented `THROW`/`KICK`, another
schema error like the PASS bug. Distributing to `target_player_id:4` (a high FWD) under
pressure is exactly the "gives the ball away" the user reports.

**Caveat on direct evidence:** the per-tick state summary (opponent distances) is **not
logged** (`summarize_state` output never appears in any stream), so I cannot quote the exact
opponent-to-GK distance on a specific distribute tick. The conclusion rests on: the prompt
has no pressure gate, the GK distributes frequently via the LLM, and `fallback.py::GK_CONFIG`
also distributes unconditionally (`possession_action="GK_DISTRIBUTE"`, nearest teammate,
`method:"THROW"`), so neither layer ever chooses "hold/shield/wait."

**Fix layer:** LEVEL-2, the `gk/*.md` bodies (all three) + `fallback.py::_on_ball` GK branch.
Add an explicit rule: "If an opponent is within ~8–10 units of you or the ball, do NOT
GK_DISTRIBUTE — hold/shield (SET_STANCE 2 or a short MOVE_TO toward your goal) or only
distribute to a teammate who is CLEARLY open; never distribute to a tightly-marked player or
hoof it to a pressed forward." Use `calculate_pass_options`/`get_defensive_assignment` to
confirm an open target first. Also restrict `method` to `THROW`/`KICK` with a worked example.

---

## (f) GK DRIFTS TO MIDFIELD (zone discipline)  *(new item)*

**LEVEL 1 verdict — WRONG.** Caused by near-constant `aggressive`, whose gk body literally
says "NOT a traditional goalkeeper … pushes far up the pitch … MOVE_TO the halfway line or
beyond to act as an extra attacker."

**LEVEL 2 verdict — WRONG, LLM, and it DIRECTLY CONTRADICTS guardrail §5** ("Player 0 (GK):
Stays in the defensive third / penalty area. Does not roam upfield."). The `aggressive`
gk.md overrides the guardrail. Evidence: GK team0 (own goal x=−55) MOVE_TO target_x **avg
+0.8, max +20** — i.e. the keeper repeatedly targets the halfway line and into the opponent
half. AWAY GK MOVE_TO x=+3.5…+5.9 (own goal +55) — also near center. The user is right: the
GK has no reason to be at midfield.

**Fix layer:** LEVEL-2, `gk/*.md` (especially `aggressive.md`) + optionally harden
`GK_CONFIG`. Remove "halfway line or beyond / extra attacker"; cap the GK's forward MOVE_TO
to the defensive third (roughly x ≤ −35 for HOME / x ≥ +35 for AWAY), leaving the line only
for a very close loose ball. `GK_CONFIG.default_x_factor=0.9` (→ x≈−49.5 for HOME) is already
correct for the fallback, so the fallback keeps the GK home — the drift is purely the
aggressive prompt. LEVEL-1 — stop picking aggressive by default also removes most of the
drift.

---

## (g) FWD STUCK + DOESN'T KNOW FORWARD vs BACK  *(user complaint 2 + items 3 & the new orientation item)*

**This is the same root cause as the "shooting inversion": the forwards never advance toward
the opponent goal, so they are never in a close-range shooting position.**

**LEVEL 2 verdict — WRONG, LLM, directional sense effectively absent.** Measured from MOVE_TO
targets:
- **FWD1 team0 (HOME, opponent goal at x=+55):** 47 MOVE_TO targets, **min −10, max +6.4,
  avg −1.0.** The striker hovers around the centre line / its own half and essentially never
  drives toward +55. It is "stuck" — not literally in a +55/±35 corner (0 corner-targets
  detected) but pinned near centre, failing to push forward.
- **FWD2 team1 (AWAY, opponent goal at x=−55):** 47 MOVE_TO targets, **min −4.8, max +10,
  avg −0.2.** It should be driving toward −55; instead it sits near centre and sometimes
  moves +x (the WRONG way, toward its own goal).

So the user's "striker stuck in the corner / doesn't push on" is, in the v6 LLM data, a
**failure to derive attacking direction from teamId** — the forward does not translate
"Opponent goal at x=±55" into "increase/decrease my x." Nova Micro reads the orient block but
does not act on it.

**LEVEL 1 verdict — partially wrong.** In `aggressive`/1-0-3 the forwards are *supposed* to
stay high, so the strategy is not telling them to sit deep; the failure is execution. But in
a `2-1-1` the single striker should hold high while FWD2 can drop — today there is no shape
that gives that coherent instruction.

**Attack/Defend phase:** the bodies have a one-line "Phase cue" but no hard rule; combined
with the absent directional sense, the FWD neither pushes forward in attack nor tracks a
defined zone in defend — it mills near centre.

**Fix layer:** LEVEL-2 — make the orient block in `tool_catalog.md` **and** every position
body state the direction computation in plain, imperative terms, e.g.: *"You attack the
opponent goal shown as 'Opponent goal at x=X'. FORWARD = move your x toward X. BACK/DEFEND =
move your x toward your own goal at the opposite end. If you have the ball and are not close
to X, MOVE_TO toward X (make a run). NEVER move toward your own goal to attack."* Add a hard
ATTACK/DEFEND phase rule (we-hold → go forward; they-hold → drop to your zone). Spell it out
numerically because Nova Micro is small. LEVEL-1 — pick a shape that assigns the forward a
clear high/low job.

---

## (c-shoot) SHOOTING INVERSION — decline close chances, score from distance  *(Question B / item 3, TOP priority)*

**Root-cause hypothesis (supported): the forwards never reach close range (item g), so the
only shots taken are long/centre ones; close-range SHOOTs are not "declined by evaluate_shot"
— they never arise, because the striker is stuck near midfield. Meanwhile MID, which does sit
centrally, is the one taking (and occasionally scoring) the longer shots.**

Evidence:
- `evaluate_shot` is **never actually called** (tools/call=0; the 1–2 "evaluate_shot"
  mentions are the catalog listing). So the shoot/no-shoot decision is **pure prompt
  heuristic**, not the tool. The "inverted evaluate_shot" theory is ruled out — the tool
  isn't in the loop at all.
- FWD1 SHOOT samples (team0, HOME, opp goal +55): `aim_location":"CENTER","power":0.9` (×2),
  `"TL","power":0.8`. Only 6 SHOOTs in 134 ticks, and the forward's x never approached +55
  (max MOVE target +6.4), so these are **long-range, centre-aimed** attempts — the "score
  from distance" pattern.
- MID SHOOT samples (team0): `aim_location":"BL","power":0.7`, `"TR","power":0.9` — MID sits
  around x avg −0.2 (centre), so any MID shot is a long one; this is the player the report
  credits with the goal "from midfield."
- The prompt gate "shoot only inside ~18–22 units of the opponent goal" is **reasonable**,
  but it is moot because the forwards never get inside it. The distance threshold is not the
  bug; the **failure to advance** is.

**Is distOppGoal read wrong?** Cannot be confirmed from logs (state summary unlogged), but
`state.py` computes `distOppGoal=abs(pos.x - opp_goal_x)` correctly per team, so the
exposure is the model's *use* of it, not the computation.

**LEVEL 1 verdict:** aggressive encourages shooting but the thin shape doesn't manufacture
close chances. **LEVEL 2 verdict:** WRONG — no tool call, no close-range arrival; the model
shoots from range with centre aim. **Fix layer:** LEVEL-2 — (1) fix the forward-advance
(item g) so close chances exist; (2) REQUIRE `evaluate_shot` before any SHOOT and only shoot
on a good result; (3) keep situational aim (already in `fallback.py::pick_shoot_aim`) and
forbid fixed `CENTER`/max-power long blasts in the bodies.

---

## (h) ANY PLAYER MAY SHOOT + DEF PINNED DEEP / NEVER SHOOTS  *(item 4 + new DEF item)*

**DEF never shoots — LEVEL 2, both prompt and fallback.** The v6 DEF command mix is
MOVE_TO 112, PASS 22, MARK 18, INTERCEPT 2, PRESS_BALL 2 — **zero SHOOT**. The `def/*.md`
bodies frame the DEF as defend/build-out only, and `fallback.py::DEF_CONFIG.possession_action
="PASS"` (never shoots). So even if the DEF had a clear chance it would pass.

**DEF "pinned deep" — nuance:** the user's "DEF sits on our goal line" matches the **v5
FALLBACK** (`DEF_CONFIG.default_x_factor=0.6` → x≈−33 for HOME, a deepish line) which ran
85–100% of v5 ticks. In **v6 the LLM** does the opposite — DEF MOVE_TO avg **+13** (opponent
half). So depending on which layer runs, the DEF is either too deep (fallback) or too high
(v6 LLM). Neither holds a disciplined defensive LINE. There is no SHOOT and MARK is light.

**Fix layer:** LEVEL-2 — (1) define the DEF home zone as a real defensive line in `def/*.md`
(e.g. hold around x≈−30…−40 for HOME, step up to support but track back on turnover), not the
goal line and not the opponent half; align `DEF_CONFIG` zone; (2) allow ANY player to SHOOT:
add to guardrails/tool_catalog "any player — including DEF/MID — with a clear close chance
(inside ~18–22u, confirmed by evaluate_shot) SHOULD SHOOT," and give MID/DEF bodies a shoot
branch. LEVEL-1 — a `2-1-1` gives the DEF a coherent line to hold.

---

## (i) OTHER ORIENTATION / SCHEMA ISSUES NOW VISIBLE (post-P0)

1. **Pervasive parameter-schema drift (LLM, LEVEL-2).** Now that the LLM drives play, Nova
   Micro invents parameter keys the parser doesn't read:
   - `MOVE_TO` with `"x"/"y"` instead of `"target_x"/"target_y"` (MID, FWD1, FWD2, GK echoes)
     — the parser only clamps `target_x/target_y`, so `x/y` pass through unclamped and may be
     ignored by the engine.
   - `PASS` with `targetId/target/targetPlayerId/passType/pass_type/power/target_x` (item c).
   - `GK_DISTRIBUTE` with `method:"PASS"/"SHORT_PASS"` instead of `THROW`/`KICK` (item e).
   Fix = every position body must show the EXACT accepted schema per command with a correct
   worked example and an explicit "use these keys only" line. This is the highest-leverage
   LEVEL-2 fix after the forward-direction one.
2. **Strategy-name prefix leak (cosmetic NIT).** Raw output is still
   `aggressive[{…}]`/`balanced[{…}]`. It parses (tolerant scanner), but the prefix means the
   model is echoing the strategy label. Harmless today; worth a one-line "output ONLY the JSON
   array, no strategy name" reinforcement.
3. **Guardrail vs strategy conflict.** Guardrail §5 says the GK stays deep and §8 lists a
   sane decision priority, but `aggressive` gk/def bodies contradict it (sweeper-keeper,
   defenders join attacks). When prompts conflict, the specific strategy body wins and the
   guardrail is ignored — see GK drift (f). Resolve by softening aggressive or strengthening
   the guardrail's "these limits override any strategy" framing.

---

## PRIORITIZED FIX LIST (by layer, with the level each targets)

**P0 — DONE / verify only.** Prompt templating fixed; LLM now drives ~95–100% of ticks.
Keep the single-brace `Example:` convention in all 15 position files.

**P1 — EXECUTION schema discipline (LEVEL 2, position `*.md` bodies).** Highest remaining
leverage. For every command, show the exact accepted JSON with correct keys and a worked
example; forbid invented keys. Fixes malformed PASS (pass-starvation), MOVE_TO `x/y`,
GK_DISTRIBUTE `method`. One consistent edit across `gk/def/mid/fwd1/fwd2 × 3 strategies`.

**P2 — FORWARD/BACK DIRECTION + PHASE (LEVEL 2, `tool_catalog.md` orient block + all bodies).**
Spell out numerically how to turn "Opponent goal at x=X" into forward/back movement, and a
hard ATTACK/DEFEND phase rule. Fixes FWD stuck/wrong-way, the shooting inversion (gets them to
close range), and the attack/defend confusion. Make it blunt — Nova Micro is small.

**P3 — DEFEND WITH STRUCTURE + ANTI-BALL-MAGNET (LEVEL 2 bodies + guardrail §5/§8; LEVEL 1
`balanced`→`2-1-1`).** One presser only; everyone else MARK/hold zone; no reflexive
INTERCEPT. Stops the constant chase (user's top goal).

**P4 — FORMATION DEFAULT 2-1-1 + STRATEGY DESCRIPTIONS (LEVEL 1, `strategies/*.md` +
`planner.py`).** Remap `balanced`→`2-1-1` (two defenders) and make aggressive `1-1-2` not
`1-0-3`; rewrite descriptions so the planner only picks aggressive when genuinely chasing,
and starts kickoff in the structured shape. Fixes the minute-2 concessions. (`2-1-1` is
already in `ALLOWED_FORMATIONS`; no code gate blocks it.)

**P1b — FIX THE TOOL-REGISTRATION BUG (LEVEL 2, CODE: `runtime_guards.py` + `unified_agent.py`).**
PREREQUISITE for all tool use. `_TimeoutTool` is not an `AgentTool`, so Strands drops every
tactical tool ("unrecognized tool specification" ×5/tick, `tools/call=0`). Make the timeout
wrapper subclass/produce a valid `AgentTool` (same `tool_name`/`tool_spec`) or enforce the
per-tool budget without wrapping, keeping the 3.5s tick cap. Add a test that a wrapped tool
still registers (`isinstance … AgentTool` + valid spec). See item (a2). Do this BEFORE P5.

**P5 — REQUIRE TACTICAL TOOLS (LEVEL 2, bodies + consider raising `MAX_TOOL_ITERATIONS`).**
DEPENDS ON P1b. Require `evaluate_shot` before SHOOT, `calculate_pass_options` before PASS
(pass to most-open), `find_open_space` for off-ball MOVE, `get_defensive_assignment` for MARK.
Currently 0 calls (because of P1b). Validate the 3.5s/2-iteration budget leaves room.

**P8 — OBSERVABILITY: unambiguous per-line team/pos/role flag (LEVEL 2, logging; small).**
Today app log lines read `"GK agent: team 0, player 0, strategy defensive"` and the team/pos
is only in the sessionId (`…-team0-pos0`). Add a consistent prefix/flag to EVERY app log line
emitted from `unified_agent.py` (and `agent_base.py` where it logs), e.g. `[team0 pos0 GK]`,
so CloudWatch reads are unambiguous when scanning across the five agents. Tiny change: build
the prefix once in `register()` from `team_id`/`effective_pid`/`position_label` and prepend it
to each `log.info/warn/error`. Recommended, low-risk.

**P6 — GK DISCIPLINE (LEVEL 2, `gk/*.md` + `GK_CONFIG`).** Keep the GK in the defensive third;
no distribute under pressure (hold/shield when an opponent is within ~8–10u); `method`
∈ {THROW,KICK}.

**P7 — ANY PLAYER MAY SHOOT + DEF LINE (LEVEL 2, guardrail/tool_catalog + def/mid bodies +
`DEF_CONFIG`).** Allow DEF/MID to SHOOT a clear close chance; define the DEF's home as a
defensive line, not the goal line or the opponent half.

### Layer summary for the follow-up fix workflow
- **Runtime CODE layer** (`runtime_guards.py`, `unified_agent.py`): **P1b (tool-registration
  bug — do this first; it unblocks all tool use)** and P8 (logging flag). These are Python
  edits with tests, per the TDD/uv conventions.
- **Strategy layer** (`strategies/*.md`, `planner.py`): P4 (formation/descriptions), part of P3.
- **Position-prompt layer** (`plugins/<pos>/*.md`, `governance/tool_catalog.md`,
  `guardrails.md`): P1, P2, P3, P5, P6, P7 — the bulk of the work, because v6 runs the LLM.
- **`fallback.py` layer**: secondary now (fallback rarely fires) — align GK/DEF zones and the
  press rule (P3/P6/P7) so a fallback tick doesn't re-introduce the old behavior, but do not
  prioritize it over the prompt fixes.

### Dependency order at a glance
P0 (done) → **P1b (tools register)** → P1 (schema) / P2 (direction) in parallel → P3 (defend
structure) → P4 (formation/strategy) → P5 (require tools, needs P1b) → P6/P7 (GK/DEF) → P8
(logging, anytime).

---

## Evidence limits (stated honestly)
- No full v6 match exists in CloudWatch; v6 behavior is read from tick-dense warm-up streams
  (134–160 decisions each). Possession-dependent aggregates (exact press %, possession) come
  from the game UI, not the logs.
- The per-tick **state summary is not logged** (`summarize_state` never appears), so exact
  opponent distances / player positions per tick cannot be quoted. Position/zone findings are
  derived from the model's **MOVE_TO target coordinates** (its stated intent) and command
  mix, which is the best available in-log signal, plus the prompt/fallback code paths.
- All command/param quotes are verbatim from the runtime-logs echoes of the model's own
  output. Content was rephrased for compliance where summarizing match-report prose.
