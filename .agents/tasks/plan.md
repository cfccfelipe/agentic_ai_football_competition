# Implementation Plan — Runtime Hardening (concerns 1–6 + Formations)

All work happens in the worktree `c:\Users\FelipeCortes\agentic_ai_football_competition\.worktrees\runtime-guards`.
Python runs through `uv` only — never bare `python`. Tests: `uv run pytest -q` from the
worktree root (47 passing today; the suite must stay green and grow). TDD: write/adjust the
test first, reuse `tests/test_helpers.py` fixtures (`GAME_STATE`, `TEAM_ID`, `mock_agentcore*`)
and `tests/conftest.py` path wiring. Design authority: `.agents/tasks/design.md` (rev 3) +
`.agents/tasks/design-approval.md`. Do NOT touch `src/governance/guardrails.md`, the `Makefile`,
`.env`, `ai-team-strands-balanced/`, `sample-ai-possibilities/`.

Concern 1 is first — it blocks every deployed agent from starting.

> **MERGE-TARGET CORRECTION (authoritative — supersedes the final merge step below).**
> The base/merge target is `feat/unified-agent-architecture` (commit `0e31f93`), NOT
> `lucero/first-runs`. `fix/runtime-guards` is already based on
> `feat/unified-agent-architecture`. Final merge step MUST:
> 1. Rebase `fix/runtime-guards` onto `feat/unified-agent-architecture`.
> 2. With `feat/unified-agent-architecture` checked out in the main repo, run
>    `git -C c:\Users\FelipeCortes\agentic_ai_football_competition merge --ff-only fix/runtime-guards`.
> 3. Do NOT touch/merge `lucero/first-runs` or `main` (both stale wrt our `src/`).
> 4. Do NOT delete the worktree (the orchestrator removes it).

## Confirmed facts from exploration (ground truth for the steps below)

- `unified_agent.py` lines 19–23: the bootstrap inserts `../commons` and `../../../commons`
  then `from _bootstrap import setup_commons_path`. In the deployed bundle `commons/` is a
  SIBLING of `unified_agent.py` (both end up at the agent dir root via `deploy_all.py` staging),
  so neither `../commons` nor `../../../commons` resolves and the import raises
  `ModuleNotFoundError: No module named '_bootstrap'`.
- `_bootstrap.setup_commons_path()` only checks `../commons` then `../../../commons`.
- `deploy_all.py` `SHARED_MODULES` copies `unified_agent.py` + `commons/` into each agent dir →
  at runtime they are siblings. (`src/main.py` is the entrypoint per `agentcore.json`.)
- `planner.select_strategy` matches the LLM choice only against `constants.STRATEGIES` (the
  3 built-ins); a discovered folder is dropped. It has `agent_factory` DI already. No timeout.
- `unified_agent.invoke()` is `async`, builds `Agent(model, system_prompt, tools)` per tick and
  calls `agent(state_summary)` with no timeout, no iteration cap, default boto retries.
- `registry._parse_frontmatter` supports flat `key: value` and folded `>` scalars; silently
  drops any line without `:`. `SkillMeta` has no `formation` field yet.
- Strands API (confirmed against strandsagents.com): `BedrockModel(**kwargs)` accepts
  `guardrail_id`, `guardrail_version`, and `boto_client_config` (a `botocore.config.Config`).
  Agent loop iterations are bounded by the per-invocation `Limits` TypedDict `turns` cap.
- CDK: `aws-cdk-lib ~2.261.0`; stack class `AgentCoreStack` in `lib/cdk-stack.ts` reuses the
  `isPaymentEligibleAgent` guard + `this.application.environments.values()` +
  `addEnvironmentVariable` pattern. `CfnOutput` already imported. `agentcore.json` = 5 Python
  HTTP CodeZip runtimes. Jest test lives in `cdk/test/cdk.test.ts` (`npm test`).
- `deploy_all.py` `pre_deploy_cleanup()` already gates STACK deletion to FAILED states, but the
  log-group deletion loop runs UNCONDITIONALLY — that is the bug to fix (finding 7).

---

## Concern 1 — Critical startup bug (do first; blocks the whole game)

- [ ] 1. Add a regression test that imports the bootstrap the way the DEPLOYED bundle lays it
      out (commons as a SIBLING of the agent module). Build a temp dir mirroring the bundle:
      `<tmp>/unified_agent_dir/` containing a tiny caller module and `<tmp>/unified_agent_dir/commons/_bootstrap.py`
      (copy the real file), then call `setup_commons_path(caller_file)` and assert the sibling
      `commons/` is now on `sys.path` and `_bootstrap` is importable. Add a second case for the
      local-dev layout (`../../../commons`). Use `tmp_path` (pytest) — never write under the repo.
      Files: `tests/test_bootstrap.py` (new).
      Verify: `uv run pytest -q tests/test_bootstrap.py` — new tests FAIL before the fix.

- [ ] 2. Fix `_bootstrap.setup_commons_path()` to also check a SIBLING `./commons` relative to the
      caller dir, trying candidates in order: `./commons` (deployed bundle), `../commons`
      (intermediate), `../../../commons` (local dev); pick the first existing dir, normpath,
      dedupe onto `sys.path`.
      Files: `src/commons/_bootstrap.py`.
      Verify: `uv run pytest -q tests/test_bootstrap.py` — both layouts pass.

- [ ] 3. Fix the inline bootstrap block in `unified_agent.py` (lines ~19–23): BEFORE the
      `from _bootstrap import ...`, also insert the same-dir path
      `os.path.join(os.path.dirname(__file__), "commons")` in addition to the existing
      `../commons` and `../../../commons`, so `_bootstrap` is importable in the deployed
      sibling layout. Keep the subsequent `setup_commons_path(__file__)` call.
      Files: `src/agents/players/unified_agent.py`.
      Verify: `uv run pytest -q` — full suite stays green (imports resolve under `conftest.py`
      wiring); `tests/test_bootstrap.py` passes.

---

## Concern 2 — Hard per-tick timeout (3.5 s) + Concern 3 — loop/retry protection

These share the invoke/planner surface; implement together. Make the invoke path testable WITHOUT
AWS by injecting the agent factory (same DI style the planner already uses).

- [ ] 4. Add timeout + loop/retry config values to `constants.py`: `TICK_TIMEOUT_SECONDS = 3.5`,
      `MAX_TOOL_ITERATIONS = 2`, `PER_TOOL_TIMEOUT_SECONDS = 1.0`, and a `bedrock_model_kwargs()`
      helper returning `{"model_id": MODEL_ID, "boto_client_config": <Config with
      retries={"max_attempts": 1, "mode": "standard"}>}` (no automatic retries within a tick).
      `bedrock_model_kwargs()` also conditionally adds `guardrail_id`/`guardrail_version` from env
      (see concern 5 step 16 — add the env readers now so both concerns share one helper).
      Import `botocore.config.Config` lazily inside the helper so pure unit tests that only read
      the timeout/iteration constants do not require botocore.
      Files: `src/agents/players/constants.py`.
      Verify: `uv run pytest -q tests/test_constants.py` (new test in step 5) passes.

- [ ] 5. Make `unified_agent.register()` accept an injectable `agent_factory` (default None →
      build `Agent(Bedrock...)` as today) so invoke is testable offline, and wrap the model+tools
      call in a HARD wall-clock timeout. In the async `invoke()`, run `agent(state_summary)` under
      `asyncio.wait_for(..., timeout=constants.TICK_TIMEOUT_SECONDS)`; because the Strands call is
      blocking, execute it via `asyncio.get_running_loop().run_in_executor(None, lambda: agent(...))`
      so `wait_for` can cancel the await. On `asyncio.TimeoutError`, log and fall through to
      `fallback_fn(...)` (then last-resort), returning a deterministic command. Pass the iteration
      cap to the agent call using the Strands per-invocation `Limits` `turns` cap
      (`MAX_TOOL_ITERATIONS`) — confirm the exact call signature against the pinned
      `strands-agents>=1.13.0` (likely `agent(prompt, limits={"turns": 2})`); if the installed
      version exposes it differently, use the real name and note it in the FEAT `findings`. Ensure
      no executor thread leaks across ticks (use the default executor; do not spawn a new one per
      tick that is never joined). Build the model via `constants.bedrock_model_kwargs()` so retries
      are disabled.
      Files: `src/agents/players/unified_agent.py`, `src/agents/players/constants.py`.
      Write first: `tests/test_unified_agent_invoke.py` driving `register()` with a fake app
      (`mock_agentcore_gateway()`), an injected `agent_factory`, and running `invoke` via
      `asyncio.run`, covering: (a) a factory whose agent SLEEPS past 3.5 s → fallback command
      returned well under 5 s (use a small patched timeout or assert the fallback shape and that it
      returns promptly); (b) the normal path returns the LLM command; (c) an agent that raises →
      fallback. Assert the returned JSON is the deterministic fallback for the position.
      Verify: `uv run pytest -q tests/test_unified_agent_invoke.py` passes; full `uv run pytest -q`
      green.

- [ ] 6. Add a per-MCP-tool timeout (~1 s, `constants.PER_TOOL_TIMEOUT_SECONDS`) so one slow tool
      cannot consume the tick budget. Wrap each cached tool in a thin timeout adapter at
      `register()` time (before building the Agent), preserving tool name/schema; on tool timeout
      raise/return a benign error the Strands loop treats as a failed tool call (so the model
      produces a final answer or the tick times out into the fallback). Keep the wrapper generic
      (DRY) and injectable so it is unit-testable without MCP.
      Files: `src/agents/players/unified_agent.py`.
      Write first: a test with a fake tool that blocks > 1 s → the wrapper raises/returns the
      timeout sentinel within ~1 s (patch the timeout small to keep the test fast).
      Verify: `uv run pytest -q tests/test_unified_agent_invoke.py` passes.

- [ ] 7. Apply the SAME timeout to the planner's LLM call (design dependency #7): wrap
      `planner.select_strategy`'s `agent(prompt)` so a slow strategy call cannot block the tick,
      falling back to `rule_based_strategy`. Prefer threading the one timeout from the invoke path
      over a second mechanism — implement a small internal helper so both model calls share it
      (DRY). Build the planner's default agent via `constants.bedrock_model_kwargs()` (retries off).
      Files: `src/agents/players/planner.py`, `src/agents/players/constants.py`.
      Write first: extend `tests/test_planner.py` — an `agent_factory` returning an agent that
      blocks past the (patched-small) timeout → `select_strategy` returns the rule-based strategy.
      Verify: `uv run pytest -q tests/test_planner.py` passes; full suite green.

---

## Concern 4 — Browser strategy discovery (OFFLINE) + Formations + planner selection

Browsing NEVER runs inside `invoke()`. Discovery is an offline script that writes a validated
`src/plugins/<name>/` folder. The planner must be able to SELECT discovered strategies.

- [ ] 8. Add formation support to the registry: give `SkillMeta` a `formation: str` field and read
      it in `_load_meta` as `fm.get("formation", DEFAULT_FORMATION)` (import `DEFAULT_FORMATION`
      from `constants`, avoiding a circular import — read it lazily inside `_load_meta` or define
      the default locally mirrored from constants; prefer a single source in `constants`).
      Files: `src/plugins/registry.py`, `src/agents/players/constants.py` (add
      `ALLOWED_FORMATIONS` tuple from the game-domain list and `DEFAULT_FORMATION = "1-1-1-1"`).
      Write first: extend `tests/test_registry.py` — a `skill.md` with a flat `formation:` yields
      that value; absent/folded/malformed `formation` yields `DEFAULT_FORMATION` (documents parser
      behavior). Use a `tmp_path` plugins dir with `discover(plugins_dir=...)`.
      Verify: `uv run pytest -q tests/test_registry.py` passes.

- [ ] 9. Thread discovered strategy names into the planner so they can be selected (keystone fix).
      Add `plugin_loader.strategy_names()` returning `tuple(registry.strategies().keys())`. Change
      `select_strategy(..., known: tuple[str, ...])` and `_parse_choice(text, known)` to match
      against `known` with LONGEST-MATCH-FIRST (iterate `known` sorted by descending length so
      `defensive_press` wins over `defensive`). Hint path validates `hint if hint in known else
      DEFAULT_STRATEGY`. `rule_based_strategy` stays built-ins only. Default `known` to
      `constants.STRATEGIES` when not passed so existing callers/tests keep working.
      Files: `src/agents/players/planner.py`, `src/agents/players/plugin_loader.py`.
      Write first: extend `tests/test_planner.py` — registry/known set with a 4th name
      `high_press_counter`; a fake `agent_factory` naming it → `select_strategy` returns it; and
      `known=("defensive","defensive_press")` with text naming `defensive_press` → returns
      `defensive_press`, not `defensive`.
      Verify: `uv run pytest -q tests/test_planner.py tests/test_plugin_loader.py` passes.

- [ ] 10. Compute and pass `known_strategies` from `unified_agent.register()`:
      `known_strategies = plugin_loader.strategy_names()` alongside the existing
      `skill_descriptions`, and pass it into `planner.select_strategy(...)` in `invoke()`.
      Files: `src/agents/players/unified_agent.py`.
      Verify: `uv run pytest -q tests/test_unified_agent_invoke.py` passes; full suite green.

- [ ] 11. Render formations in the position prompt (O(1), no model call). In
      `plugin_loader.build_system_prompt(strategy, pos, player_id)` look up the chosen strategy's
      `SkillMeta.formation` and have `load_skill_prompt` substitute a `{formation}` token plus a
      one-line formation-posture string; default to `DEFAULT_FORMATION` when the strategy is
      unknown (reuse the existing default-strategy/`mid.md` fallbacks). Keep `guardrails.md`
      untouched in the composed prompt.
      Files: `src/agents/players/plugin_loader.py`.
      Write first: extend `tests/test_plugin_loader.py` — `build_system_prompt` output contains the
      formation posture line for the strategy's declared formation AND still contains guardrails
      text; `strategy_names()` returns the discovered set.
      Verify: `uv run pytest -q tests/test_plugin_loader.py` passes.

- [ ] 12. Add flat `formation:` frontmatter to each built-in strategy and a one-line "Formation
      posture" section referencing `{formation}` to each position file. Defaults: `defensive →
      3-0-1`, `aggressive → 1-0-3`, `balanced → 1-2-1`. Same pattern across all three strategies'
      `skill.md` + their `gk/def/mid/fwd1/fwd2.md` — one coherent change.
      Files: `src/plugins/{balanced,aggressive,defensive}/skill.md` and each `*/{gk,def,mid,fwd1,fwd2}.md`.
      Verify: `uv run pytest -q tests/test_registry.py tests/test_plugin_loader.py` passes
      (formation parsed + rendered for each built-in).

- [ ] 13. Create the OFFLINE generator + validator script `discover_strategy.py` (never imported
      by the runtime). It asks an INJECTED web-search/Strands agent (default lazily built, injected
      in tests) to propose a strategy spec, VALIDATES it, and only then writes
      `src/plugins/<name>/` (skill.md + 5 position files). Validation (all fatal, nothing written
      on failure): structural (exactly the 6 files); frontmatter parsed via
      `registry._parse_frontmatter` on the ACTUAL bytes to be written (name matches
      `^[a-z][a-z0-9_-]{1,30}$`, `type==skill`, non-empty `description`, `formation` present and in
      `ALLOWED_FORMATIONS`); name non-collision AND substring-disjoint vs `registry.strategies()`;
      path-safety (reject `..`/separators/absolute); content-safety (each position file has the
      mandatory JSON-array response line, only `VALID_COMMANDS`/the 4 tactical tools, no
      system-prompt-override phrasing/URLs/extra code fences). Write to `$env:TEMP` (OS temp),
      validate there, move into `src/plugins/<name>/` only if all pass; exit non-zero on failure.
      Files: `src/agents/players/discover_strategy.py` (new).
      Write first: `tests/test_discover_strategy.py` with a STUBBED research callable — good spec
      accepted and moved; each bad spec (missing file, empty description, bad/folded formation,
      substring-colliding name, injected content, unsafe path) rejected with nothing moved.
      Validator exercises `registry._parse_frontmatter`. Fully offline.
      Verify: `uv run pytest -q tests/test_discover_strategy.py` passes; full suite green.

---

## Concerns 5 & 6 — Bedrock Guardrail (CDK) + incremental deploy (shared surface)

- [ ] 14. Fix `pre_deploy_cleanup()` so orphaned-log-group deletion is GATED on the same
      failed/absent condition as the stack deletion — never run `delete-log-group` when the stack
      is healthy (`CREATE_COMPLETE`/`UPDATE_COMPLETE`). Move the log-group loop inside the
      `if status in (FAILED...)` branch (or the no-stack case). Extract the state-gating into a
      small pure helper (e.g. `_should_cleanup(status)`) so it is testable without live AWS.
      Files: `src/agents/players/deploy_all.py`.
      Write first: `tests/test_deploy_all.py` — mock/inject `aws_cli` (or call `_should_cleanup`):
      a healthy status → zero `delete-log-group` calls and the stack is NOT deleted; a
      `ROLLBACK_COMPLETE`/`*_FAILED` status → stack deleted AND orphan log groups deleted. Guard
      the import so loading `deploy_all.py` in tests does not execute its top-level deploy flow
      (the module runs deploy at import today) — refactor the top-level script body under a
      `main()`/`if __name__ == "__main__":` guard as part of this step so it is importable.
      Verify: `uv run pytest -q tests/test_deploy_all.py` passes; full suite green.

- [ ] 15. Add the content-safety Bedrock Guardrail as an ADDITIONAL resource INSIDE
      `AgentCoreStack` (same stack, incremental UPDATE — NOT a new stack). In `cdk-stack.ts`:
      `import * as bedrock from 'aws-cdk-lib/aws-bedrock'`; read the flag via
      `this.node.tryGetContext('createBedrockGuardrail')` OR
      `process.env.CREATE_BEDROCK_GUARDRAIL === 'true'`; when set, create `CfnGuardrail`
      (content filters HATE/INSULTS/SEXUAL/VIOLENCE/MISCONDUCT at MEDIUM, prompt-attack INPUT HIGH,
      one denied-topic for off-domain/role-override, required `name` +
      `blockedInputMessaging`/`blockedOutputsMessaging`) and `CfnGuardrailVersion`; inject
      `BEDROCK_GUARDRAIL_ID`/`BEDROCK_GUARDRAIL_VERSION` into eligible runtimes reusing the
      `isPaymentEligibleAgent` guard + `environments.values()` + `addEnvironmentVariable` pattern;
      add `CfnOutput`s. CONFIRM the exact L1 class/attr/prop names
      (`CfnGuardrail`/`CfnGuardrailVersion`/`attrGuardrailId`/`attrVersion`/`guardrailIdentifier`)
      and the filter/topic property shapes against `aws-cdk-lib ~2.261.0` before writing — record
      confirmations in FEAT `findings`.
      Files: `src/agents/players/agentcore/cdk/lib/cdk-stack.ts`.
      Write first: extend `cdk/test/cdk.test.ts` (Jest) — with the flag SET the synthesized
      template contains an `AWS::Bedrock::Guardrail` resource and the runtimes get the guardrail
      env vars; with the flag UNSET there is NO guardrail resource and no guardrail env vars (so
      deploy still works without guardrail-create permissions).
      Verify: `npm test` and `npm run build` in `src/agents/players/agentcore/cdk` pass.

- [ ] 16. Wire the `BedrockModel` to use the guardrail CONDITIONALLY via env, through the shared
      `constants.bedrock_model_kwargs()` (env readers added in step 4):
      `GUARDRAIL_ID = os.environ.get("BEDROCK_GUARDRAIL_ID")`,
      `GUARDRAIL_VERSION = os.environ.get("BEDROCK_GUARDRAIL_VERSION", "DRAFT")`; include
      `guardrail_id`/`guardrail_version` only when `GUARDRAIL_ID` is set. `unified_agent.register()`
      and `planner._default_agent()` build via `BedrockModel(**constants.bedrock_model_kwargs())`.
      Unset id ⇒ model built exactly as today (deploy/runtime unchanged). A guardrail block at
      runtime is already caught by invoke's existing fallback — no new hot-path error handling.
      Files: `src/agents/players/constants.py`, `src/agents/players/unified_agent.py`,
      `src/agents/players/planner.py`.
      Write first: `tests/test_constants.py` — no env ⇒ kwargs has `model_id` (+`boto_client_config`)
      and NO guardrail keys; env id set ⇒ kwargs includes `guardrail_id`/`guardrail_version`.
      Env-patched, pure, no AWS.
      Verify: `uv run pytest -q tests/test_constants.py` passes; full suite green.

- [ ] 17. Document the env-var contract and the read-only deploy confirmations. Add
      `CREATE_BEDROCK_GUARDRAIL`, `BEDROCK_GUARDRAIL_ID`, `BEDROCK_GUARDRAIL_VERSION=DRAFT` (blank
      by default) to `.env.example` with a comment that blank = run without a guardrail. Record (in
      the FEAT `findings`, not committed scratch) the read-only pre-redeploy health check
      (`aws cloudformation describe-stacks --stack-name AgentCore-TeamUnified-default --region
      us-east-1 --query "Stacks[0].StackStatus" --output text` → expect `*_COMPLETE`) and the
      runtime-version confirmation (discover the real list-versions verb via
      `aws bedrock-agentcore-control help`; confirm ARN unchanged + new version). Also CONFIRM
      read-only that the `CREATE_BEDROCK_GUARDRAIL` flag reaches CDK synthesis under
      `agentcore deploy` (env or `--context`); if it does NOT, take the committed-config fallback
      (thread the flag through `bin/cdk.ts` + an `AgentCoreStackProps` field) and note it.
      Files: `.env.example` (do NOT touch `.env` or the `Makefile`).
      Verify: `.env.example` documents the three vars; no secrets added. Full `uv run pytest -q`
      green.

---

## Final verification

- [ ] 18. Run the whole suite and the CDK unit tests. Confirm 47 existing + all new Python tests
      pass and the CDK Jest/build pass.
      Verify: `uv run pytest -q` (green, count increased) AND, in
      `src/agents/players/agentcore/cdk`, `npm run build && npm test` (green).

## Notes / assumptions

- The exact Strands call signature for the per-invocation iteration cap (`Limits.turns`) and the
  precise `BedrockModel` guardrail kwarg names are confirmed from the public API docs; the
  implementer must re-confirm against the installed `strands-agents>=1.13.0` and use the real
  names, recording any divergence. `strands` is NOT a local dev dependency (only in each agent's
  `requirements.txt`), so invoke/planner tests MUST inject fakes and never import real Strands.
- `deploy_all.py` executes its deploy flow at import today; step 14 refactors it under a `main()`
  guard so it can be imported in tests — this is a prerequisite for the deploy test and is scoped
  into that step.
- Live AWS actions (guardrail creation, actual redeploy, runtime-version check) are out of unit
  scope and verified read-only per §5.4 of the design; any captured output goes to the OS temp dir
  and is deleted after reading — nothing lands in the repo.
