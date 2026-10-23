"""AI Soccer Defender — controls player 1. Unified dynamic-skill agent."""

import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..")))

from bedrock_agentcore.runtime import BedrockAgentCoreApp
import unified_agent

app = BedrockAgentCoreApp()

MY_PLAYER_ID = 1

unified_agent.register(app, MY_PLAYER_ID)

if __name__ == "__main__":
    app.run()
