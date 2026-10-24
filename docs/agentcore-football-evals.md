# AgentCore football evaluations

The `TeamStrandsBalanced` AgentCore project defines online evaluation
configurations for the deployed MID and GK runtimes. Each samples 5% of sessions
from that player's CloudWatch log group. MID has three session-level
LLM-as-a-judge evaluators:

| Evaluator | What it measures |
| --- | --- |
| `mid_role_discipline` | Central support, phase-aware attack/defense, pressure handoffs, and role discipline. |
| `midfield_progression` | Safe forward progression, sensible shots/passes when in possession, and purposeful off-ball movement. |
| `shape_5v5_feasibility` | Separation and central support while respecting the five-player roster and fixed player roles. |
| `gk_safe_distribution` | Distributes to open FWDs first, then MID; never DEF; holds possession if the keeper or all eligible receivers are pressured. |

Each evaluator scores 0-4. A score of 2 is mixed/uncertain; 3-4 is generally
good. Scores are evidence from traces, not match results or proof that a tactic
caused a goal. Inspect the evaluator explanation and the underlying trace before
changing prompts or formations. MID and GK are monitored separately; don't
attribute one player's commands to another. Team-wide match breakdowns can
motivate an investigation, but their aggregate PRESS/PASS/MOVE counts do not
identify which role produced each command.

## Formation constraint

This project runs five players total: GK (0), DEF (1), MID (2), FWD1 (3), and
FWD2 (4). The current outfield role allocation is 1 DEF + 1 MID + 2 FWD. A
1-2-1-2 totals six players even if the goalkeeper is counted, so it cannot be
applied to this 5v5 runtime as written. The evaluator does not silently change
the formation; it flags that roster mismatch and scores whether the deployed
five-player structure remains coherent. Evaluate a revised 5-player candidate
formation separately before changing agent roles.

## Deploy and inspect

After confirming the target account and region, deploy the project resources
from `ai-team-strands-balanced/`:

```bash
agentcore deploy --yes
agentcore eval evaluator list
agentcore eval online-eval list
```

Online evaluation is enabled at a 5% sampling rate. This adds Bedrock judge
invocations and associated charges for sampled MID and GK sessions. To pause collection:

```bash
agentcore eval online-eval pause <online-evaluation-config-id>
```

To inspect results and recent evaluation logs:

```bash
agentcore eval online-eval logs <online-evaluation-config-id>
```

After running a scrimmage, allow the configured five-minute session-idle timeout
and trace ingestion time before expecting a complete session score. Compare
scores across multiple matches and review sample traces; don't infer a formation
winner from one match or one LLM-judge score.
