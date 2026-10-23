"""AI Soccer Goalkeeper — controls player 0. Unified dynamic-skill agent."""

import os
import sys

# Make the shared unified_agent module (src/agents/players/) importable.
sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..")))

from bedrock_agentcore.runtime import BedrockAgentCoreApp
import unified_agent

app = BedrockAgentCoreApp()

MY_PLAYER_ID = 0

unified_agent.register(app, MY_PLAYER_ID)

if __name__ == "__main__":
    app.run()
