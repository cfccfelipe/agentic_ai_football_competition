# Gameplay Findings — What We Learned From Real Matches

Behavioral diagnosis of the AI team across deployed matches, from CloudWatch traces + the
game-platform match reports. This is the gameplay/tactics counterpart to the technical
`docs/learnings.md`. Use it to know what's already understood before tuning strategies.

> Tuning note: from the dynamic-roles consolidation onward, tactics are changed by editing
> strategy markdown only (`src/plugins/strategies/*.md` + `src/plugins/<role>/*.md`, roles =
> gk/def/mid/fwd). The runtime machinery is wired in code and should not need edits to adjust
> play.

---

## Match record (v6, Nova Micro execution)

| Opponent | Result | How it went |
|---|---|---|
| The Benchmark FC | L 1-2 | 65% possession but lost; two opponent FWD goals at min 2; we pulled one back (MID). |
| The Benchmark FC (earlier) | L 0-1 | conceded min 4; 6 shots, 0 on target; over-pressed, under-passed. |
| Gork 'n' Mork Boyz | W 2-1 | DEF (min 1) + MID (min 2) goals; won on possession/passing control (Pass 13%). |
| Amber Crests 2 | W 1-0 | early FWD goal (min 4) + heavy press; opponent 59% possession but 0 shots on target. |
| (defensive opponent, Intercept 59%) | L | Move 65%, Shoot 1% (3), Pass 6% — couldn't break a defensive side. |

Net: winning more than losing, but on a FRAGILE style — early goals + defense + a heroic GK,
not sustained attacking football.

---

## The two-level lens (how we diagnose every issue)

1. **STRATEGY level** — did the planner pick the right strategy/formation for the situation?
   Fix layer = `strategies/*.md` descriptions and/or `planner.py`.
2. **EXECUTION level** — given the chosen strategy, was the per-tick command/target/zone/aim/
   phase correct? Fix layer = position `*.md` bodies, `fallback.py`, tool usage.
3. **Attribution** — LLM decision vs deterministic fallback. (Post-P0, it's almost always the
   LLM, because the fallback barely fires now.)

---

## Root causes found (and the fix each gets)

### CODE bugs (execution layer) — these gate everything
1. **P0 — prompt templating (FIXED).** Few-shot `Example:` lines used doubled braces `{{ }}`
   (for `str.format`) but `plugin_loader` fills with `str.replace`, so the model saw invalid
   JSON and `parse_commands` rejected its output → the rule-based FALLBACK ran on 85-100% of
   ticks in v5. Fix: single-brace examples. v6 result: LLM now drives ~95-100% of ticks.
2. **Tool-registration bug (in progress).** The per-tool timeout wrapper
   `runtime_guards._TimeoutTool` is not a Strands `AgentTool`, so Strands' registry DROPS all
   four tactical tools ("unrecognized tool specification" ×5/tick, `tools/call=0`). Result:
   evaluate_shot / calculate_pass_options / find_open_space / get_defensive_assignment are
   NEVER called — every decision is an unassisted guess. Fix: make the wrapper a valid
   `AgentTool` (keep the 1s per-tool + 3.5s tick caps). PREREQUISITE for any "decide with
   facts" tool use.
3. **Parameter-schema drift (in progress).** Nova Micro invents param keys the parser doesn't
   read: `PASS` with `targetId/target/passType/power/target_x` (should be `target_player_id`
   + `type`), `MOVE_TO` with `x/y` (should be `target_x/target_y`), `GK_DISTRIBUTE` with
   `method:"PASS"` (should be `THROW`/`KICK`). Missing `target_player_id` makes `parsing.py`
   default the pass to a forward → blind forced passes = the pass-starvation. Fix: show the
   EXACT accepted schema with a worked example per command in every body; forbid invented keys.

### TACTICAL / behavioral issues
4. **Aimless movement — the #1 recurring symptom.** `MOVE_TO` is 47-68% of our commands in
   EVERY match. Players wander without intent. Fix: every MOVE_TO must have purpose — in
   ATTACK advance toward the opponent goal / `find_open_space`; in DEFEND hold zone / track
   mark. Cut raw wandering.
5. **Shooting broken — 0 shots on target repeatedly.** Forwards never reach close range
   (FWD1 MOVE_TO avg x ≈ -1, never nears the +55 opponent goal), so the only shots are
   long/centre ones. `evaluate_shot` is never called (see bug #2). Fix: forwards must advance
   to close range; REQUIRE `evaluate_shot` before SHOOT; situational aim (not fixed
   CENTER/max-power long blasts); shoot inside ~18-22 units. ANY player (DEF/MID included) may
   shoot a clear close chance.
6. **Forward/back disorientation.** Forwards don't derive their attacking direction from
   teamId (HOME attacks +x, AWAY attacks -x) — they hover near centre or move the wrong way,
   and get "stuck." Fix: spell out numerically in every body + the orient block: "FORWARD =
   move your x toward the opponent goal at x=X; BACK = toward your own goal; never move toward
   your own goal to attack." Plus a hard ATTACK/DEFEND phase rule (we-hold → forward;
   they-hold → drop to zone).
7. **Reactive pressing / no structure.** Expressed as INTERCEPT spam (one match: AWAY GK
   INTERCEPT on 154/158 ticks) and later as Press creep + Move; MARK is ~1%. Multiple players
   chase the same ball (anti-ball-magnet failure). Fix: only the single closest player
   PRESS_BALL/INTERCEPT; everyone else MARK the nearest unmarked opponent or hold zone; no
   per-tick reflexive INTERCEPT.
8. **Early concessions from a thin shape.** Planner picks `aggressive` (formation 1-0-3, one
   defender) ~85-95% of ticks, including at kickoff 0-0 → goals conceded at min 2-4 on
   counters. The DEF and even the GK drift into the opponent half (DEF MOVE_TO avg +13, GK
   avg +0.8 for HOME) leaving our third empty. Fix: default to `2-1-1` (two real defenders);
   `aggressive` → `1-1-2` not `1-0-3`; rewrite strategy descriptions so the planner starts
   structured and only goes aggressive when genuinely chasing. gameTime is SECONDS — don't
   treat ~120 as "late."
9. **GK over-involved + drifts upfield.** The GK is repeatedly MVP + Most Tactical with the
   MOST commands (81, 104) — a flag that the OUTFIELD under-contributes, AND the aggressive
   gk body literally sends the keeper to "the halfway line or beyond as an extra attacker,"
   contradicting guardrail §5. It also distributes under pressure (no proximity gate). Fix:
   keep the GK in the defensive third (never midfield); proximity gate — if an opponent is
   within ~8-10u, don't `GK_DISTRIBUTE`, hold/shield or only distribute to a clearly open
   teammate; `method` only THROW/KICK. Preserve the GK's speed/reliability — the real lift is
   raising DEF/MID/FWD decision quality so impact shifts to the outfield.
10. **Erratic passing.** Pass swings 0% → 6% → 13% across matches. Fix: schema discipline (#3)
    + require `calculate_pass_options` and pass to the MOST OPEN teammate advancing toward the
    opponent goal → reliable possession build-up.
11. **Players get stuck (anti-stuck).** The FWD pins near a corner/centre and repeats the same
    ineffective command because the prompt never showed it its own `lastAction`. Fix
    (lightweight, in-budget, no external memory): surface the agent's `lastAction` (and
    whether position barely changed) in `summarize_state`, and add a prompt rule: "if your
    situation hasn't improved since last tick, DO SOMETHING DIFFERENT — don't repeat a command
    that isn't working."

---

## Design decisions locked in

- **Always 5 players, 5v5.** You cannot remove an agent. You change ROLES via formation, not
  the player count.
- **Fixed vs flexible roles:** player 0 = GK and player 1 = DEF are HARD-PINNED always
  (guarantees ≥1 GK + ≥1 DEF). Players 2/3/4 are FLEXIBLE, controlled by a flag; when on, the
  agent may adapt its role within the formation ("let the agent think").
- **Role folders, not player folders:** `plugins/{gk,def,mid,fwd}/<strategy>.md` (fwd1+fwd2
  collapsed into one `fwd`). Any player in the FWD role loads the single `fwd` body.
- **Formations** arrange the 4 outfield players as DEF-MID-FWD (GK not counted). Default
  non-chasing shape = `2-1-1`.
- **Model split:** a STRONGER model for the PLANNER (strategy/formation decision,
  `PLANNER_MODEL_ID`, env-overridable, default-safe); Nova Micro for per-tick EXECUTION.
- **Tools do the math:** the 4 MCP tactical tools are the only calculation layer — NO code
  interpreter (deliberate; revisit later). Using them well (once bug #2 is fixed) is the
  biggest competitive lever.
- **Caps (never regress):** 3.5s hard per-tick timeout, MAX 2 tool iterations, 0 model
  retries, 3-layer deterministic fallback.
- **Markdown-only tuning going forward:** add a strategy = drop `strategies/<name>.md` +
  `plugins/<role>/<name>.md` for gk/def/mid/fwd; the registry discovers it, no code change.

## Phase-2 (deliberately deferred)
- **AgentCore Memory** (`AgentCoreMemorySessionManager`) for cross-tick/cross-match learning —
  not added now: it adds a per-tick network read that risks the 3.5s budget, and Nova Micro
  gets limited value from it. Revisit once the base is solid and a stronger execution model is
  available. The lightweight `lastAction` anti-stuck (#11) covers the near-term "don't repeat
  the error" need without external memory.
- **AgentCore Evaluations** (LLM-as-judge + code-based custom evaluators, domain criteria) —
  the LLM judge must run inside AgentCore (direct Bedrock from local is connection-refused).
  Build after the base is winning consistently. NOT the generic fairness/helpfulness metrics
  (they don't apply to football commands) — use domain-specific tactical criteria.
- **Local simulator** with a deterministic decider (no LLM, since local Bedrock is blocked) to
  cuadrar the engine/flow/command-mix offline and iterate fast before deploying.

## Observability
- `make observability` (filters to our `TeamUnified_ai_*` runtimes only — the shared account
  has other teams' `ai_*` runtimes). Transaction Search is enabled account-wide; spans flow
  once an agent is invoked (tracing "enables" itself on first span).
- Logs should carry a clear per-line flag: team id + team NAME + position + role
  (e.g. `[team0 'Lightning Cloud' pos0 GK]`).
