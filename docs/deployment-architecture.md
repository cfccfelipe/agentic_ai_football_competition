# Deployment Architecture

`make deploy` runs the test gate, then stages shared code into each agent bundle
and deploys everything (5 runtimes + gateway + 4 Lambda tools) in one CDK stack.
`deploy_all.py` auto-cleans any failed stack and orphaned log groups first, so
re-running is always safe.

```mermaid
flowchart TD
    subgraph LOCAL["Local repo (source of truth)"]
        MK["make deploy"]
        TESTS["tests/ — 24 tests<br/>(gate: must pass first)"]
        DEP["deploy_all.py<br/>(auto-cleans failed stack + log groups)"]
        subgraph SRC["src/ (single copies)"]
            LIB["lib/"]
            PLUG["plugins/<br/>(skills + general scripts)"]
            GOV["governance/guardrails.md"]
            REQ["requirements.txt"]
            MODS["constants · planner<br/>plugin_loader · unified_agent"]
            GWT["gateway_tools/<br/>(Lambda wrappers)"]
        end
        AJSON["agentcore/agentcore.json<br/>5 runtimes + 1 gateway (PYTHON_3_10)"]
    end

    MK --> TESTS
    TESTS -->|pass| DEP
    TESTS -->|fail| STOP["deploy blocked"]

    DEP -->|"stage copies into<br/>each ai-* bundle"| BUNDLES["ai-gk · ai-def · ai-mid<br/>ai-fwd1 · ai-fwd2<br/>(each gets lib+plugins+governance+reqs+pyproject+mods)"]
    DEP -->|"agentcore deploy"| CDK["CDK synth + CloudFormation"]
    AJSON --> CDK
    BUNDLES --> CDK

    CDK --> AWS

    subgraph AWS["AWS (AgentCore)"]
        direction TB
        R0["Runtime ai_gk_agent (player 0)"]
        R1["Runtime ai_def_agent (player 1)"]
        R2["Runtime ai_mid_agent (player 2)"]
        R3["Runtime ai_fwd1_agent (player 3)"]
        R4["Runtime ai_fwd2_agent (player 4)"]
        subgraph GW["Gateway: tactical-tools (MCP)"]
            L1["lambda calculate_pass_options"]
            L2["lambda evaluate_shot"]
            L3["lambda find_open_space"]
            L4["lambda get_defensive_assignment"]
        end
        CWW["CloudWatch<br/>Transaction Search (traces)"]
    end

    DEP -.->|"on success/failure:<br/>remove staged copies"| SRC

    R0 & R1 & R2 & R3 & R4 -->|"AGENTCORE_GATEWAY_TACTICAL_TOOLS_URL<br/>(injected by CDK)"| GW
    R0 & R1 & R2 & R3 & R4 -.->|traces| CWW

    MON["make monitoring<br/>(one-time, before deploy)"] -->|"enable Transaction Search"| CWW
    DSTROY["make destroy"] -->|"agentcore destroy"| AWS
```
