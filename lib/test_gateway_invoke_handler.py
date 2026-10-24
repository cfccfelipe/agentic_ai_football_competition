import asyncio
import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).parent))

from fallback import DEF_CONFIG
from gateway_invoke_handler import (
    GOALKEEPER_EXCLUSION_RADIUS,
    _protect_goalkeeper_space,
    create_gateway_invoke_handler,
)
from test_helpers import GAME_STATE


class _Logger:
    def __init__(self):
        self.messages = []

    def info(self, message):
        self.messages.append(message)

    def warn(self, message):
        self.messages.append(message)

    def error(self, message):
        self.messages.append(message)


class _App:
    def __init__(self):
        self.logger = _Logger()

    def entrypoint(self, handler):
        self.handler = handler
        return handler


class _MCPClient:
    def __init__(self):
        self.active = False

    def __enter__(self):
        self.active = True
        return self

    def __exit__(self, *args):
        self.active = False
        return False


class GatewayInvokeHandlerTests(unittest.TestCase):
    def test_agent_runs_inside_mcp_context_with_raw_state(self):
        app = _App()
        mcp_client = _MCPClient()
        received_prompt = []

        def agent(prompt):
            self.assertTrue(mcp_client.active)
            received_prompt.append(prompt)
            return (
                '[{"commandType":"MOVE_TO","playerId":1,'
                '"parameters":{"target_x":-50,"target_y":0,"sprint":true}}]'
            )

        create_gateway_invoke_handler(
            app, agent, mcp_client, 1, "DEF",
            lambda *_: [], fallback_cfg=DEF_CONFIG,
        )
        payload = {"prompt": {"teamId": 0, "gameState": GAME_STATE}}

        async def invoke():
            return [item async for item in app.handler(payload, None)]

        output = json.loads(asyncio.run(invoke())[0])
        self.assertFalse(mcp_client.active)
        self.assertIn("Raw game state for tactical tools", received_prompt[0])
        command = output[0]
        keeper = GAME_STATE["players"][0]["position"]
        target = command["parameters"]
        distance = ((target["target_x"] - keeper["x"]) ** 2 +
                    (target["target_y"] - keeper["y"]) ** 2) ** 0.5
        self.assertAlmostEqual(distance, GOALKEEPER_EXCLUSION_RADIUS, places=2)

    def test_goalkeeper_space_guard_does_not_change_other_players(self):
        commands = [{
            "commandType": "MOVE_TO",
            "parameters": {"target_x": -50, "target_y": 0},
        }]
        result = _protect_goalkeeper_space(commands, GAME_STATE, 0, 2, _Logger())
        self.assertEqual(result[0]["parameters"]["target_x"], -50)


if __name__ == "__main__":
    unittest.main()
