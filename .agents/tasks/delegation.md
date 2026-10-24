---
inclusion: always
---

# Mandatory: Delegate Code Creation

When a task requires **writing or substantially editing code** (new modules, features,
refactors, multi-file changes), delegate the implementation to a specialized sub-agent
(e.g. `general-task-execution`) with a precise, self-contained prompt: files to touch,
the contract, tests to satisfy, and the conventions (TDD, uv, SOLID/DRY/YAGNI).

Reserve direct inline edits for small surgical fixes (a typo, a one-line change, config).
Always review what the sub-agent produced before moving on. Keep this thread focused on
orchestration and review.
