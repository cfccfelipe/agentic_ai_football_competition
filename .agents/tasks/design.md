# Design — Static/Dynamic Prompt Split with Controlled ReAct Flow

## Status

**Revision 2** — a `.agents/tasks/design-review.json`
(`verdict: CHANGES_REQUESTED`, 1 HIGH / 3 MEDIUM / 3 NIT) exists and has been
resolved. Every finding is addressed in the body below and summarized in §12
(Review responses). Re-grounded against the real worktree code at
`c:\Users\FelipeCortes\agentic_ai_football_competition\.worktrees\static-dynamic-prompt`.

Pinned stack confirmed from the worktree: `strands-agents>=1.13.0`,
`strands-agents-tools>=0.1.0`, `bedrock-agentcore>=1.0.3`
(`src/agents/players/requirements.txt` and each `ai-*/pyproject.toml`). Model is Nova
Micro everywhere (`constants.MODEL_ID`). Python, Windows, `uv`.

Facts re-verified in source this revision (cited where used):
- `guardrails.md` **§8 "Decision Priority (Every Tick)" exists** and item 4 already reads
  "On the ball — you have possession → **consult the tactical tools**, then PASS or SHOOT."
  (resolves Finding 4; see §3/§8).
- `plugin_loader.strategy_names()` → `registry.strategies()` with **no argument** (uses
  module-level `registry.PLUGINS_DIR`), and `load_skill_prompt` resolves bodies from the
  module-level `plugin_loader._PLUGINS_ROOT`. Neither takes a dir override (resolves
  Finding 1; see §9 T-DROP).
- `invoke()` wraps its whole body in `except Exception` → fallback, and `constants.DEFAULT_STRATEGY
  = "balanced"` exists (resolves Finding 2; see §4).
- All five OUR agents pin the correct id in `src/agents/players/ai-<pos>/src/main.py`:
  `gk=0, def=1, mid=2, fwd1=3, fwd2=4`, each calling `unified_agent.register(app, MY_PLAYER_ID)`
  (AC-B1).
- `deploy_all.py` stages `("commons", "plugins", "governance", "requirements.txt",
  *SHARED_MODULES)`; `SHARED_MODULES = ["constants.py","planner.py","plugin_loader.py",
  "unified_agent.py","runtime_guards.py"]` — a new `governance/*.md` ships automatically,
  no module change (AC-R5).
- `docs/per-tick-workflow.md` exists and currently shows the OLD single-step
  `build_system_prompt` with no static/dynamic split and no phase gate → UPDATE (AC-C1).

---

## 1. Summary

Today `unified_agent.invoke()` re-composes the whole per-tick system prompt as one
string every tick: `plugin_loader.build_system_prompt(strategy, pos, pid)` =
`guardrails.md` + `plugins/<position>/<strategy>.md`, injected as the Strands
`system_prompt`, with MCP tools passed via `tools=`. CloudWatch traces showed two
problems the user wants fixed:

1. The tools are **invisible in the prompt** — they go through Strands native
   tool-calling, and the skill `.md` bodies **never mention them**, so Nova Micro decides
   blind (e.g. `fwd1/aggressive.md` says "SHOOT at every possible opportunity" / "Power
   shots at 1.0 — always shoot with maximum power" and never names `evaluate_shot`).
2. There is **no stable static layer**: guardrails + a tool catalog are not presented as
   a cached base; everything is rebuilt each tick.

This design separates the prompt into:

- **STATIC base** (built once per agent process, cached, never recomposed per tick):
  the game **guardrails** (`src/governance/guardrails.md`, rules unchanged) **plus a tool
  catalog / when-to-use section** naming the four tactical MCP tools and the situation
  that triggers each. Tools still execute via Strands `tools=` native tool-calling; the
  static text only makes the model **aware** they exist and **when** to call them.
- **DYNAMIC strategy content** (varies per tick): once the planner has settled the team
  strategy for the tick, the agent consults **that strategy's body for its OWN resolved
  position** (`plugins/<position>/<strategy>.md`) and appends it to the cached static base.

A **step-controlled ReAct flow** gates the order: PHASE 1 confirm the strategy is chosen,
PHASE 2 consult the position+strategy skill content, PHASE 3 (within the 2-iteration
tool cap and 3.5s budget) consult the tactical MCP tools to "decide with facts", then emit
exactly one validated command. The gate forbids reaching skill content or tools before the
strategy is confirmed, and the gate is an **explicit logged guard, not an `assert`**
(Finding 2).

The **north-star promise is preserved and strengthened**: tactics live entirely in
markdown. Adding a strategy stays a drop-a-folder operation (registry discovery, zero code
change); improving tactics stays markdown-only. Crucially, **tool-awareness is driven by
the STATIC `tool_catalog.md` alone** — it is the *sufficient* driver of "decide with
facts", so a brand-new strategy dropped in with plain bodies (no tool wording) still
decides with facts (Finding 3). Per-body tool wording is *optional reinforcement*, not a
requirement.

No `cdk/` edit, no `Makefile`/`.env` edit, no change to the guardrail rules, and no new
dependency or code-execution surface are required (verified in §10).

---

## 2. Requirements (as acceptance criteria)

Numbered, testable. "AC" = acceptance criterion.

### North-star markdown-only promises

- **AC-N1 (add a strategy, zero code).** Dropping a new strategy folder set
  (`src/plugins/strategies/<name>.md` metadata + `src/plugins/<pos>/<name>.md` bodies for
  all five positions) makes `<name>` (a) selectable by the planner and (b) loadable by
  every one of the five positions, with **no Python edit**. REQUIRED TEST (§9, T-DROP).
- **AC-N2 (improve a strategy, markdown-only).** Changing a skill body or a
  `strategies/<name>.md` description changes agent behavior / planner selection with no
  Python edit. The `.md` files remain the single tuning surface for tactics.
- **AC-N3 (decide-with-facts is markdown-driven AND needs no per-body wording).** The
  behavior that makes the agent call a tool before a risky action is produced by the
  STATIC `tool_catalog.md` text — **not** by new Python control logic and **not**
  requiring tool wording in the 15 skill bodies. A new strategy dropped in with plain
  bodies inherits decide-with-facts from the static catalog. Tuning *which* tool is
  suggested when stays a single-file `.md` edit (the catalog). REQUIRED TEST (§9, T-TOOL
  using a body with NO tool mention).

### Static / dynamic split

- **AC-S1.** The STATIC base system prompt = guardrails text + the tool-catalog/when-to-use
  section. It is built **once** per agent process at `register()` time and reused every
  tick. It is NOT recomposed inside `invoke()`.
- **AC-S2.** The tool catalog names **exactly the four deployed tactical tools**
  (`evaluate_shot`, `calculate_pass_options`, `find_open_space`,
  `get_defensive_assignment`) and no others, states a trigger for each, and is
  **self-contained and non-contradictory with `guardrails.md`** (it restates no rule that
  conflicts with guardrails; see §3 for the verified reconciliation with guardrails §8).
  The catalog text is sourced from a markdown file, not hard-coded as a Python tactics
  string. REQUIRED TEST (§9, T-CAT).
- **AC-S3.** The DYNAMIC layer is the chosen strategy's position body only, appended to
  the cached static base after the strategy is confirmed. The per-tick composition cost is
  a single string concatenation plus the existing `{player_id}`/`{formation}` substitution
  — no network for the strategy content (see Option decision §5).

### Additive A — controlled step-by-step ReAct

- **AC-A1 (PHASE 1 gate, no `assert`).** `invoke()` resolves position and confirms a
  concrete strategy BEFORE any skill content is loaded or any tool is made consultable.
  The gate is an explicit **logged guard that coerces an unknown strategy to
  `constants.DEFAULT_STRATEGY`**, never an `assert` (so it survives `python -O` and is not
  swallowed by the broad `except`). The strategy value handed to PHASE 2 is always one of
  the known strategy names.
- **AC-A2 (PHASE 2 after confirmation).** Skill content for the agent's OWN position is
  consulted only after PHASE 1 confirms the strategy.
- **AC-A3 (PHASE 3 within caps).** Within `MAX_TOOL_ITERATIONS=2` and
  `TICK_TIMEOUT_SECONDS=3.5`, the agent may call the tactical MCP tools, then emits exactly
  one validated command. No unbounded loop is introduced; the existing `limits={"turns":2}`
  cap and `asyncio.wait_for` wall-clock budget remain the enforcement.
- **AC-A4 (ordering is testable).** A test proves that no skill content is composed and no
  tool is offered until a concrete strategy is present, and that an unknown strategy is
  **coerced (not raised)** to the default (§9, T-ORDER).

### Additive B — routing by agentId + position

- **AC-B1.** The id→position map is single-source (`constants.PLAYER_POSITIONS`:
  0=GK,1=DEF,2=MID,3=FWD1,4=FWD2) and each deployed agent pins the correct `MY_PLAYER_ID`
  in its `ai-<pos>/src/main.py` (verified: gk=0, def=1, mid=2, fwd1=3, fwd2=4).
- **AC-B2.** The dynamic skill lookup routes to `plugins/<resolved-position>/<strategy>.md`
  for the agent's OWN resolved position, with no cross-wiring (GK loads `gk/…`, FWD1 loads
  `fwd1/…`, etc.).
- **AC-B3.** `teamId` and `myPlayers` are handled for both teams: team 0 HOME attacking +x
  / team 1 AWAY attacking -x, with the effective player id taken from `myPlayers[0]` when
  present. A team-1 / AWAY payload is summarized from the AWAY perspective.
- **AC-B4 (testable, both resolution branches).** A parametrized test proves every
  agentId 0..4 routes to its correct position label AND loads the correct skill file, for
  BOTH teams, **covering BOTH the `myPlayers`-supplied branch AND the pinned-`MY_PLAYER_ID`
  (myPlayers-absent) production branch** (§9, T-ROUTE).

### Additive C — per-tick flow document

- **AC-C1.** `docs/per-tick-workflow.md` (confirmed to exist, currently shows the OLD
  single-step build) is UPDATED (not duplicated) to describe: receive state → resolve
  position from agentId → PHASE 1 confirm strategy → PHASE 2 consult skill content →
  PHASE 3 controlled ReAct with tactical tools → single validated command; the static vs
  dynamic split (guardrails + tool catalog cached once, strategy body appended per tick);
  the settled calculation decision (the four MCP tools only, explicitly no code
  interpreter); the markdown-only tuning promise; and where the 3.5s timeout / 2-iteration
  cap apply.
- **AC-C2.** The document states it must be kept accurate to the implemented code.

### Settled scope

- **AC-X1.** All probability/advantage math is done by the existing four MCP tactical
  tools. No code-interpreter / code-agent / code-execution surface is designed or added.
  This is recorded as a settled decision in the per-tick doc.

### Non-functional / do-not-regress

- **AC-R1.** `TICK_TIMEOUT_SECONDS=3.5` wall-clock enforcement via
  `asyncio.wait_for` over an executor stays intact; on timeout → deterministic fallback.
- **AC-R2.** `MAX_TOOL_ITERATIONS=2` (`limits={"turns":2}`), `PER_TOOL_TIMEOUT_SECONDS=1.0`,
  and retries-off (`max_attempts=1`) stay intact.
- **AC-R3.** The 3-layer fallback (LLM → rule-based → last-resort) keeps working.
- **AC-R4.** `tests/test_e2e_tick.py` stays green, with all five guarantees intact, and is
  updated to the new prompt structure. The `build_system_prompt` wrapper it calls MUST
  keep the full verbatim guardrails text and `{formation}` so its `"JSON array"`,
  `"Formation"`, and formation-string assertions stay green (Finding 5).
- **AC-R5.** The deploy contract holds: any new runtime module under `players/` is added to
  `deploy_all.py` `SHARED_MODULES` in the same change. This design introduces **no new
  `players/` module** (see §4, §10).

### Out of scope

- Planner enrichment beyond score+clock (team-coordinated selection stays as-is).
- Any code interpreter / code execution (future enhancement only).
- Changing the guardrail rules themselves.
- Editing `cdk/`, `node_modules/`, `agentcore.json`, `Makefile`, `.env`,
  `ai-team-strands-balanced/`, `sample-ai-possibilities/`.
- `discover_strategy.py` (offline library-growth tool, never in the tick path) — unchanged.

---

## 3. The static / dynamic boundary (what goes where, and how static is built once)

### Static base (cached, built once at `register()`)

Contents, in order:

1. **Guardrails** — the verbatim text of `src/governance/guardrails.md` (rules unchanged).
2. **Tool catalog / when-to-use** — a short markdown section listing the four tactical
   tools and the trigger for each, and the controlled-flow contract.

#### Reconciliation with `guardrails.md §8` (Finding 4 — read and verified this revision)

`guardrails.md` was read in full. It **does** contain a `## 8. Decision Priority (Every
Tick)` section with a fixed order, and item 4 already reads:

> 4. On the ball — you have possession → **consult the tactical tools**, then PASS or SHOOT.

So the SHOOT/PASS-before-acting intent is already endorsed by the guardrails text; the
catalog does not contradict it, it *operationalizes* it by naming which tool matches which
action. However, §8 names **no tool for MOVE_TO or for MARK/PRESS_BALL** (items 1, 2, 3, 5
describe the action priority but not a tool). Therefore the earlier "catalog mirrors §8
verbatim for all four tools" claim is **dropped**. Instead:

- The catalog is defined as the **authoritative, self-contained source** for the
  tool→situation mapping. It stands alone (guardrails stays unedited — out of scope).
- The catalog MUST be **consistent with §8** and restate **no rule that contradicts
  guardrails** (it is concatenated with guardrails on every tick; a contradiction would be
  the highest-blast-radius text in the system). Concretely, the catalog's SHOOT/PASS
  guidance tracks §8 item 4 ("consult the tactical tools, then PASS or SHOOT"); its MOVE_TO
  and MARK/PRESS_BALL guidance is additive and consistent with §8's defensive-first /
  support ordering, naming a tool where §8 only names an action.

The catalog's content (markdown):

```
## Tactical Tools — call one before a risky action, then decide with facts

You are given four deterministic tools. They are NOT optional flavor — they replace a
guess with real math. Before a risky action, call the matching tool ONCE, read its result,
then return exactly one command (guardrails §8: "consult the tactical tools, then PASS or
SHOOT").

- evaluate_shot            — before any SHOOT (especially long attempts): is this shot worth it?
- calculate_pass_options   — before a PASS: which lanes are open and valuable?
- find_open_space          — when off the ball and choosing where to MOVE_TO.
- get_defensive_assignment — when defending: who to MARK / PRESS_BALL / cover.

A team strategy is ALREADY chosen for this tick and appears below. Follow it. You have at
most a couple of tool calls this tick — spend them on the decision that matters, then emit
one JSON-array command for your player only.
```

This is what converts tool *availability* into tool *usage*, and it is the **sufficient**
driver of decide-with-facts for every position and every strategy (AC-N3) — including a
brand-new strategy whose bodies never mention a tool.

#### Where the tool-catalog text lives (markdown, to honor AC-N3/AC-S2)

A new markdown file `src/governance/tool_catalog.md`, read by `plugin_loader` exactly like
`guardrails.md`. Rationale: putting it in governance (a) keeps it a single markdown tuning
surface shared by all five positions and all strategies (DRY — one place, not repeated in
15 bodies), and (b) keeps "decide with facts" markdown-driven rather than a Python string
literal, satisfying AC-N3. It is a SEPARATE file from the guardrail *rules*, so adding it
does not touch guardrails (AC-R, §10). Rejected alternative — embedding the catalog in each
skill body — would duplicate the guidance 15 times, make a tool-wording change a 15-file
edit, and (worse) make a newly dropped-in strategy fail decide-with-facts until its author
remembered to replicate the wording five times (the exact north-star regression Finding 3
flagged).

**Built once, reused.** `register()` already runs once per agent process (it wires the
`@app.entrypoint` closure that captures `skill_descriptions`, `known_strategies`,
`cached_tools`). The static base is computed there into a local captured by the `invoke`
closure. `invoke()` never recomputes it. Guardrails + catalog never change at runtime, so
caching is a plain local variable — no TTL, no invalidation path, YAGNI.

### Dynamic layer (per tick, after PHASE 1)

- The chosen strategy's body for the agent's OWN resolved position:
  `plugins/<position>/<strategy>.md`, with `{player_id}` and `{formation}` substituted
  (existing behavior in `load_skill_prompt`).
- Composed per tick as `static_base + "\n\n---\n\n" + skill_body`. One concatenation, no
  network.

### Why this split is correct

The guardrails + tool catalog are invariant across ticks and across strategies — they are
the agent's identity. The strategy body is the only thing that varies once the planner has
decided. The split cleanly matches "constant = cached" vs "varies = per-tick", and the
per-tick cost drops to a single string join over an already-loaded skill file.

---

## 4. Redesign of `plugin_loader.py` and `unified_agent.py`

### New / changed functions in `plugin_loader.py`

`plugin_loader.py` stays the only module that "reads and composes text". Changes:

- **New `load_tool_catalog() -> str`** — reads `src/governance/tool_catalog.md`
  (mirrors `load_guardrails()`), resolved from `_SRC_ROOT / "governance" / "tool_catalog.md"`
  so it works in both the local checkout and the deployed bundle (governance is staged as a
  sibling, same as today).
- **New `build_static_base() -> str`** — returns `guardrails + "\n\n---\n\n" + tool_catalog`.
  Pure, deterministic, no strategy/position inputs. This is the cached base.
- **Keep `load_skill_prompt(strategy, position_label, player_id) -> str`** unchanged (its
  unknown-strategy → `DEFAULT_STRATEGY` and unknown-position → `mid/<strategy>.md` fallbacks
  stay — belt-and-suspenders behind the PHASE-1 gate).
- **New `compose_tick_prompt(static_base, strategy, position_label, player_id) -> str`** —
  returns `static_base + "\n\n---\n\n" + load_skill_prompt(...)`. This is the per-tick join.
- **Keep `build_system_prompt(strategy, position, player_id)` as a thin wrapper** =
  `compose_tick_prompt(build_static_base(), strategy, position, player_id)`. It is retired
  from the hot path (which calls `compose_tick_prompt` against the register-time base) but
  stays for tests / one-shot callers. **The wrapper MUST still include the full verbatim
  guardrails text (it does, via `build_static_base`) and the `{formation}` substitution
  (it does, via `load_skill_prompt`)** so the existing `test_e2e_tick.py` assertions
  `"JSON array"`, `"Formation"`, and the formation string stay green (Finding 5).
- **Keep** `strategy_descriptions()` and `strategy_names()` unchanged — registry-backed
  discovery untouched → AC-N1 preserved. (Note: both read module-level
  `registry.PLUGINS_DIR` / `plugin_loader._PLUGINS_ROOT`; the T-DROP test monkeypatches
  those — see §9.)

No new runtime module under `players/` is introduced; the tool-catalog markdown ships
inside the already-staged `governance/` folder, so `SHARED_MODULES` is unchanged.

### Changes in `unified_agent.py`

The static/dynamic split and the phase gate wire here.

**At `register()` (once):**
- Add `static_base = plugin_loader.build_static_base()` and capture it in the closure
  (alongside the existing `skill_descriptions`, `known_strategies`, `cached_tools`).

**Inside `invoke()` (per tick), three explicit phases with a hard, logged gate between 1
and 2 (no `assert` — Finding 2):**

```python
# PHASE 1 — RESOLVE + CONFIRM STRATEGY (gate)
prompt_data   = parse_prompt(payload)
team_id       = team_id_from(prompt_data, log, position_label)
game_state    = prompt_data.get("gameState", {})
my_players    = prompt_data.get("myPlayers", [my_player_id])
effective_pid = my_players[0] if my_players else my_player_id
pos           = constants.position_for(effective_pid)          # AC-B1/B2

hint     = prompt_data.get("strategy", "auto")
strategy = planner.select_strategy(game_state, team_id, skill_descriptions,
                                   hint=hint, known=known_strategies)

# GATE: coerce (never raise) an unknown strategy to the default. An `assert`
# here is wrong: it is swallowed by the broad `except Exception` below (silent
# fallback) and is stripped entirely under `python -O`. An explicit logged
# guard survives -O and keeps a known name flowing to PHASE 2.
if strategy not in known_strategies:
    log.warn(f"{pos}: planner returned unknown strategy {strategy!r}; using default")
    strategy = constants.DEFAULT_STRATEGY

# PHASE 2 — DRILL DOWN (only now) INTO THIS POSITION'S SKILL CONTENT
system_prompt = plugin_loader.compose_tick_prompt(static_base, strategy, pos, effective_pid)
state_summary = summarize_state(game_state, team_id, effective_pid, pos)
log.info(f"{pos} agent: team {team_id}, player {effective_pid}, strategy {strategy}")

# PHASE 3 — CONTROLLED ReAct WITHIN THE CAPS
agent  = agent_factory(system_prompt=system_prompt, tools=cached_tools)
limits = {"turns": constants.MAX_TOOL_ITERATIONS}
# ... existing asyncio.wait_for over executor, timeout=TICK_TIMEOUT_SECONDS ...
# ... parse_commands -> yield; else fallback; on timeout -> fallback ...
```

**Why the gate is real and testable.** PHASE 2 (`compose_tick_prompt`) and PHASE 3 (agent
build with `tools=`) are *lexically after* the strategy is resolved and coerced to a known
name. The only way to reach skill content or tools is through a known `strategy`. The
planner already guarantees a concrete value (non-auto hints validated against `known`;
auto → LLM choice or `rule_based_strategy`, which returns one of
aggressive/defensive/balanced), and the explicit guard is the belt-and-suspenders that also
holds if `known_strategies` ever drifts. A test spies on `compose_tick_prompt` and
`agent_factory` and confirms neither fires until `select_strategy` returns, and that an
unknown strategy is coerced (not raised) to the default (§9, T-ORDER).

**No new `players/` runtime module.** All changes edit existing modules
(`plugin_loader.py`, `unified_agent.py`), both already in `SHARED_MODULES`. Therefore **no
`SHARED_MODULES` change is required** — see §10 for the binding rule that still applies if a
future edit adds a module.

**Strands version note (strands-agents>=1.13.0).** The controlled flow uses the primitives
already in use and valid on 1.13.0: a single `Agent(model, system_prompt, tools)` call
bounded by the per-invocation `limits={"turns": 2}` cap. We do NOT depend on newer 1.45+
APIs (the teammate's `ai-team-strands-balanced/` pins 1.45; OUR runtimes pin 1.13.0 and
must stay buildable on it). The phase control is ordered Python in `invoke()` plus prompt
text, not a new Strands graph/hook API — loop-safe and version-stable (the control lives in
our code; Strands stays a consumed library). NB: whether `limits={"turns": 2}` is enforced
by the real Strands `Agent.__call__` on 1.13.0 is **pre-existing behavior** this design
relies on but does not re-verify against the installed library; it is not introduced here.

---

## 5. Option X vs Option Y (dynamic strategy consultation) — decision

**Budget facts (`constants.py`):** `TICK_TIMEOUT_SECONDS = 3.5s`; `MAX_TOOL_ITERATIONS = 2`
turns; `PER_TOOL_TIMEOUT_SECONDS = 1.0s`; retries off (`max_attempts=1`).

**Option X (navigable):** expose each strategy's position body as an MCP resource/tool
(e.g. `get_strategy_playbook(strategy, position)`) the agent calls in-tick once the
strategy is known.

- **cdk/ blocker (DECISIVE, non-estimated).** Exposing a new MCP tool on the deployed
  gateway `teamunified-tactical-tools` requires registering the tool with the gateway. That
  gateway/runtime wiring lives under the OFF-LIMITS `src/agents/players/agentcore/cdk/`
  vended package. We may add pure functions in `plugins/general/scripts/` and thin wrappers
  in `gateway_tools/`, but **standing the tool up as a callable MCP endpoint without editing
  `cdk/` is not supported by any OUR-code deploy path this design can rely on.** Per the
  hard rule ("if Option X requires editing `cdk/`, prefer Option Y"), Option X is
  **disqualified on this ground alone**, independent of latency.
- **Latency (corroborating, observed/approximate — Finding 7).** The user's CloudWatch
  traces show each MCP round-trip ≈ **1s** (connect + `200` negotiate + `202` call). These
  are **observed-in-traces, approximate** figures, not a benchmark. On that basis an extra
  playbook fetch would consume ≈1s **and** one of only two turns, leaving a single turn for
  the tactical tool that actually produces decide-with-facts, with the two MCP calls alone
  ≈2s of a 3.5s budget before any model reasoning. This corroborates the decision but is
  **not** the decisive reason — the cdk/ constraint is.

**Option Y (cheap):** inject the chosen strategy's `.md` into the tick prompt after the
strategy is decided (no network); keep the static base cached and append the dynamic body.

- Latency: **0 extra network** — one local file read (OS-warm after first read) + one
  concat. Both tool turns remain for PHASE 3 tactical calls. Comfortably inside 3.5s.
- No `cdk/` touch, no new gateway tool. Markdown-only promise fully intact (strategy body
  is still a plain `.md`).

**Decision: Option Y.** The decisive, non-estimated reason is the OFF-LIMITS `cdk/` rule —
Option X cannot be built without editing `cdk/`. Latency (observed/approximate) corroborates
but does not drive the choice. Option Y honors the 3.5s timeout, the 2-iteration cap (both
turns stay for real tactical facts), and the 0-retry policy.

The "navigation" intent ("vamos y consultamos el contenido de la estrategia") is still
honored: the agent consults the *content of the already-chosen strategy* in PHASE 2 — served
from a local markdown read instead of an in-tick network hop. The genuine "decide with
facts" navigation happens in PHASE 3 via the existing tactical tools, which is where the
budget should be spent.

---

## 6. Making the agent actually call the right tool before a risky action (PHASE 3)

No Python branching decides tools (that would break AC-N3). The behavior is driven by text,
and the **STATIC `tool_catalog.md` is the SUFFICIENT driver** (Finding 3):

1. **Static tool catalog** (§3) names each tool + its trigger and states the contract
   ("before a risky action, call the matching tool once, then return one command"). This
   alone makes a tool-aware agent for every position and every strategy — including a
   brand-new strategy whose bodies never mention a tool.
2. **Per-body wording is OPTIONAL reinforcement, not required.** Existing bodies MAY be
   softened at their risky-action point (e.g. `fwd1/aggressive.md` could change "always
   shoot with maximum power" toward "call `evaluate_shot` first, then shoot if it's worth
   it") as a markdown-only tuning pass, but a NEW strategy needs **no tool wording in its
   bodies** to decide with facts. This resolves the §3-vs-§6 tension the review raised: the
   single shared tuning surface for tool-awareness is the catalog, not 15 bodies.
3. **Tools remain provided** to the Strands Agent via `tools=cached_tools` (native
   tool-calling), bounded by `limits={"turns": 2}` and `PER_TOOL_TIMEOUT_SECONDS`.

Explicitly **no code interpreter / code execution** is added (AC-X1). The four MCP tactical
tools are the only calculation surface. `discover_strategy.py`'s web-research path stays out
of the tick (never imported by `unified_agent`).

A test (§9, T-TOOL) proves the catalog alone is sufficient: with a possession state, the
tool-aware static base, and a strategy body that contains **NO tool mention**, the fake
model calls the tactical tool before emitting a SHOOT — asserted via the fake tool's call
count. Using a tool-free body keeps T-DROP honest (a dropped-in strategy with plain bodies
still decides with facts).

---

## 7. Routing by agentId + position (Additive B)

Routing is already correct in principle; this design makes it **explicitly tested** rather
than re-implemented:

- `effective_pid = myPlayers[0] if myPlayers else my_player_id` → `pos =
  constants.position_for(effective_pid)` (single-source map). The `else` branch is the real
  production wiring — in deployment the server payload typically omits `myPlayers`, so the
  agent resolves its own position from the **pinned `MY_PLAYER_ID`** passed to
  `register(app, MY_PLAYER_ID)`.
- Dynamic lookup `plugins/<pos>/<strategy>.md` uses that resolved `pos` — no cross-wiring.
- `summarize_state(game_state, team_id, effective_pid, pos)` already handles HOME/AWAY via
  `_is_my_team` (case-insensitive `teamCode`) and `get_goal_positions(team_id)`, so a team-1
  payload is summarized from the AWAY perspective (verified in `src/commons/state.py`).

Known fragile spot, so §9 T-ROUTE covers **both** resolution branches and **both** teams
(Finding 6): the `myPlayers`-supplied branch AND the pinned-id (myPlayers-absent) branch.

---

## 8. Edge cases & error handling (concrete, per operation)

- **`tool_catalog.md` missing at build time** — `load_tool_catalog()` raises
  `FileNotFoundError`. This is a *deploy packaging* error (the file ships inside the staged
  `governance/` folder); it is fatal at `register()` and loud by design — it surfaces at
  process init, never mid-match, so a missing catalog can never silently degrade a live
  tick. Recovery: none at runtime (packaging bug caught by §9 T-PKG). Not swallowed —
  failing init is correct (same philosophy as a missing `guardrails.md` today).
- **Unknown / malformed strategy from the planner** — handled by the explicit PHASE-1 guard
  (coerce to `DEFAULT_STRATEGY`, logged at warn). Independently, `load_skill_prompt` also
  falls back to `DEFAULT_STRATEGY` then `mid/<strategy>.md`. Never raises; never silently
  dropped to the broad `except`.
- **Missing position file** — `load_skill_prompt` falls back to `mid/<strategy>.md`
  (existing). Recoverable, no raise.
- **MCP gateway unreachable at startup** — existing behavior preserved: `cached_tools=[]`,
  the agent runs with LLM + deterministic fallback, logged at warn. The static tool catalog
  still names the tools (harmless; the model simply has none to call that tick).
- **Model hangs / slow** — existing `asyncio.wait_for(timeout=3.5)` → deterministic
  `fallback_fn`, logged at warn (AC-R1).
- **Model loops on tools** — `limits={"turns": 2}` caps it; per-tool 1.0s bound prevents a
  single slow tool eating the budget (AC-R2).
- **Parse failure of model output** — existing `parse_commands` → empty → `fallback_fn`,
  logged at warn; then last-resort on fallback failure (AC-R3).
- **Payload old vs new format / `teamCode` case** — handled in `state.py` already;
  unchanged. T-ROUTE exercises the AWAY (team 1) path.

**Input validation summary (each external input):**
- `payload.prompt.myPlayers` — optional list; default `[my_player_id]`; `[0]` taken as
  effective pid; an id outside 0..4 falls to `MID` via `position_for` (existing, safe).
- `payload.prompt.strategy` — optional; default `"auto"`; non-auto validated against
  `known` by the planner; unknown → `DEFAULT_STRATEGY` (planner) and re-guarded in `invoke`.
- `payload.prompt.teamId` — resolved by `team_id_from` (existing); drives perspective.
- `gameState` — optional dict; `summarize_state` tolerates missing fields (existing).

**Invariant ownership.**
- PHASE-1-before-PHASE-2 ordering → owned by `unified_agent.invoke()` (only composition
  site), enforced by lexical order + the explicit logged guard.
- "strategy is always a known name entering PHASE 2" → owned jointly by
  `planner.select_strategy` (primary) and the `invoke()` logged guard (belt-and-suspenders,
  `-O`-safe).
- "static base is immutable for the process" → owned by `register()` (built once, never
  reassigned).
- id→position single-source → owned by `constants`.

---

## 9. Test plan (TDD, `uv run pytest`, pure/offline)

All tests live under `tests/`, reuse `tests/test_helpers.py` fixtures
(`GAME_STATE`, `mock_agentcore_gateway`, DI via `agent_factory`), and run with no AWS/network.

- **T-E2E (update `tests/test_e2e_tick.py`, keep green, AC-R4, Finding 5).** Keep all five
  guarantees. Update only the prompt-structure assertions so the composed prompt now
  contains (a) a guardrails marker (`"JSON array"`), (b) a tool-catalog marker (e.g.
  `"evaluate_shot"`), and (c) a formation from `ALLOWED_FORMATIONS`. The existing
  `test_planner_is_state_aware_and_formation_resolves` calls `build_system_prompt(...)`
  directly; keep it — the wrapper routes through `build_static_base`, so verify its output
  still contains `"JSON array"`, `"Formation"`, and `"1-0-3"` (the aggressive formation).
  Tool-used, single-valid-command, cap-stops-loop, and timeout-fallback assertions unchanged.
- **T-STATIC (AC-S1).** `build_static_base()` returns a string containing both the
  guardrails text and all four tool names; calling it twice yields identical text; and a
  spy proves `invoke()` composes the tick prompt from a base built at `register()` time, not
  rebuilt per tick — e.g. after `register()`, monkeypatch `plugin_loader.build_static_base`
  (and `load_guardrails`) to raise, then run a tick and assert it still succeeds (the base
  was captured in the closure and is not recomputed in the hot path).
- **T-CAT (AC-S2, Finding 4).** Assert `plugin_loader.load_tool_catalog()` names **exactly**
  the four deployed tool names `{evaluate_shot, calculate_pass_options, find_open_space,
  get_defensive_assignment}` and no other `*_* ` tool-looking token; and assert it does NOT
  restate a rule that contradicts guardrails (spot-check: it must not tell the agent to
  return prose, emit more than one command, or shoot toward its own goal — all guardrail
  rules). Keeps the always-present static layer internally consistent.
- **T-DYNAMIC (AC-A2/AC-S3).** The strategy body is appended only after a strategy is
  chosen: spy on `compose_tick_prompt`, assert it receives the resolved (known) strategy and
  the correct position, and that the appended text is the position body (position-unique
  marker present).
- **T-ORDER (AC-A1/AC-A4, Finding 2).** Spy/counter on `select_strategy`,
  `compose_tick_prompt`, and `agent_factory`. Assert call order: `select_strategy` returns
  BEFORE `compose_tick_prompt`, which is BEFORE `agent_factory`. Then force
  `select_strategy` to return an **unknown** name and assert the PHASE-1 guard **coerces it
  to `constants.DEFAULT_STRATEGY` without raising** (the tick still produces a valid command
  via a normal compose, NOT via the `except`→fallback path) — this proves the gate does not
  depend on `assert`. Separately force `select_strategy` to **raise** and assert neither
  `compose_tick_prompt` nor `agent_factory` fires (→ except → deterministic fallback).
- **T-ROUTE (AC-B1..B4, Finding 6).** Two parametrizations over `player_id ∈ {0,1,2,3,4}`
  × `team_id ∈ {0,1}`:
  (a) **payload branch** — payload carries `myPlayers=[pid]`; assert the composed prompt
  contains that position's body marker (GK text for 0, DEF for 1, …), for HOME and for an
  AWAY (`teamCode:"away"`, team 1) payload;
  (b) **pinned-id branch** — `myPlayers` OMITTED, agent registered with `my_player_id=pid`;
  assert it resolves to position `pid`'s body. Confirms no cross-wiring, correct perspective,
  and both resolution paths.
- **T-TOOL (AC-N3 / §6, Finding 3).** With a possession state, the tool-aware static base,
  and a strategy body that contains **NO tool mention**, a fake model that follows the
  catalog calls the tactical tool (fake `evaluate_shot`) at least once before returning a
  SHOOT; assert `tool.calls >= 1` and the final command is valid. The tool-free body proves
  the catalog alone drives decide-with-facts (and keeps T-DROP honest).
- **T-DROP (AC-N1, the north-star test, Finding 1).** In `tmp_path`, create a minimal copy
  of the real plugins tree (the `strategies/` folder + the five position folders), then
  `monkeypatch.setattr` **both** `registry.PLUGINS_DIR` **and** `plugin_loader._PLUGINS_ROOT`
  to that tmp tree (and clear any registry cache if one is added later). Drop a brand-new
  strategy `strategies/<new>.md` (valid frontmatter) + `<pos>/<new>.md` for all five
  positions, with **zero code edit**. Then assert, **through the loader entry points the
  runtime actually uses** (not `registry.discover(dir)` directly):
  (a) `plugin_loader.strategy_names()` includes `<new>` (planner-selectable), and
  (b) `load_skill_prompt("<new>", label, pid)` loads the new body for every one of the five
  position labels. This exercises the exact module-level-constant path `unified_agent` uses,
  so "add a strategy is markdown-only" is proven end to end without touching the real tree.
- **T-PKG (AC-R5 / §8 packaging).** Assert `src/governance/tool_catalog.md` exists and that
  `deploy_all.py` stages the `governance/` folder (so the new file ships) — i.e. `"governance"`
  is in the staged set. Also assert `SHARED_MODULES` still lists every module
  `unified_agent` imports at runtime (`constants, planner, plugin_loader, unified_agent,
  runtime_guards`) so a future new `players/` module is caught.

---

## 10. Explicit non-regression confirmations

- **No `cdk/` edit.** Option Y needs no new MCP tool, so nothing under
  `src/agents/players/agentcore/cdk/` is touched. This is the **decisive** reason Option X
  was rejected (§5).
- **No `Makefile` / `.env` edit.** The gateway URL already arrives via
  `AGENTCORE_GATEWAY_TACTICAL_TOOLS_URL`; no new env var. The static base is built from
  files already in the repo/bundle.
- **No change to the guardrail rules.** `guardrails.md` text is reused verbatim. The tool
  catalog is a SEPARATE new markdown file (`src/governance/tool_catalog.md`), not an edit to
  the guardrail rules; it is verified consistent with guardrails §8 (§3) and non-contradictory
  (T-CAT).
- **No new dependency / no code-execution surface.** Only `strands-agents>=1.13.0` and the
  existing four MCP tools are used. No code interpreter (AC-X1).
- **Deploy contract (AC-R5).** This change introduces **no new runtime module** under
  `src/agents/players/` — it edits only `plugin_loader.py` and `unified_agent.py`, both
  already in `SHARED_MODULES`. The new asset is `src/governance/tool_catalog.md`, shipped
  inside the already-staged `governance/` folder (`deploy_all.py`:
  `("commons", "plugins", "governance", "requirements.txt", *SHARED_MODULES)`). **BINDING
  RULE:** if implementation ever adds a new module under `players/` that `unified_agent`
  imports at runtime, it MUST be added to `SHARED_MODULES` in the same change (T-PKG guards).

---

## 11. Files to touch (implementer's map)

- `src/governance/tool_catalog.md` — NEW markdown: tool catalog + when-to-use + flow
  contract, consistent with guardrails §8, self-contained (ships via staged `governance/`).
- `src/agents/players/plugin_loader.py` — add `load_tool_catalog`, `build_static_base`,
  `compose_tick_prompt`; re-express `build_system_prompt` as the thin wrapper (keeping full
  guardrails + `{formation}`); registry discovery untouched.
- `src/agents/players/unified_agent.py` — build `static_base` once in `register()`; wire the
  three explicit phases in `invoke()` with the **logged** PHASE-1 guard (no `assert`); keep
  timeout/cap/fallback intact.
- `src/plugins/<gk|def|mid|fwd1|fwd2>/<aggressive|balanced|defensive>.md` — **OPTIONAL**
  markdown-only reinforcement edits (soften blind-action wording toward tool-first). NOT
  required for decide-with-facts; the static catalog is sufficient. A new strategy needs no
  tool wording in its bodies.
- `docs/per-tick-workflow.md` — UPDATE the mermaid flow + prose (PHASE 1/2/3 with the gate,
  static/dynamic split = cached guardrails+catalog then per-tick strategy body, settled calc
  decision = four MCP tools only / no code interpreter, markdown-only tuning promise, where
  the 3.5s / 2-turn caps apply); note it must stay accurate to the code.
- `tests/` — update `test_e2e_tick.py`; add T-STATIC, T-CAT, T-DYNAMIC, T-ORDER, T-ROUTE,
  T-TOOL, T-DROP, T-PKG.
- `src/agents/players/deploy_all.py` — NO change required (governance already staged; no new
  module). Listed only to record the verified no-op.

---

## 12. Review responses (resolving `design-review.json`, verdict CHANGES_REQUESTED)

- **Finding 1 (MEDIUM — T-DROP not feasible as written): ADDRESSED.** §9 T-DROP now
  monkeypatches BOTH `registry.PLUGINS_DIR` and `plugin_loader._PLUGINS_ROOT` to a
  `tmp_path` copy of the plugins tree and asserts through the real loader entry points
  (`plugin_loader.strategy_names()` and `load_skill_prompt(...)`), not `registry.discover(dir)`.
  The "point `registry.discover(plugins_dir=…)` at a fixture" wording is removed.
- **Finding 2 (MEDIUM — PHASE-1 gate relied on `assert`): ADDRESSED.** §4 and §8 replace the
  `assert` with an explicit logged guard that coerces an unknown strategy to
  `constants.DEFAULT_STRATEGY` (verified to exist). §9 T-ORDER asserts coercion-without-raise
  and is stated to be `-O`-safe. The gate no longer depends on `assert`.
- **Finding 3 (MEDIUM — AC-N3 vs 15-body edits): ADDRESSED.** §3, §6, and AC-N3 now make
  `tool_catalog.md` the SUFFICIENT driver of decide-with-facts; per-body edits are downgraded
  to OPTIONAL reinforcement and a new strategy needs no tool wording in its bodies. §9 T-TOOL
  proves the catalog alone works using a body with NO tool mention.
- **Finding 4 (HIGH — catalog pinned to unverified guardrails §8): ADDRESSED.**
  `guardrails.md` was read; §8 "Decision Priority" exists and item 4 already says "consult
  the tactical tools, then PASS or SHOOT". §3 drops the "mirrors §8 verbatim for all four
  tools" claim (§8 names no tool for MOVE_TO or MARK/PRESS_BALL), defines the catalog as the
  authoritative self-contained source that is consistent-with and non-contradictory-to
  guardrails, and §9 adds T-CAT asserting exactly the four tool names and no contradictory
  rule.
- **Finding 5 (NIT — wrapper must keep guardrails for e2e markers): ADDRESSED.** §4 and AC-R4
  state the `build_system_prompt` wrapper MUST include the full verbatim guardrails text and
  `{formation}` so `"JSON array"`, `"Formation"`, and the formation string stay green.
- **Finding 6 (NIT — T-ROUTE missing pinned-id branch): ADDRESSED.** §7 and §9 T-ROUTE now
  cover BOTH the `myPlayers`-supplied branch AND the pinned-`MY_PLAYER_ID` (myPlayers-absent)
  production branch, for both teams.
- **Finding 7 (NIT — Option X latency presented as hard numbers): ADDRESSED.** §5 labels the
  ≈1s/round-trip and ≈2s-of-3.5s figures as observed-in-traces/approximate and states the
  cdk/ constraint is the decisive, non-estimated reason, with latency corroborating.
