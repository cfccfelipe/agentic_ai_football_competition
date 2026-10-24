import asyncio
import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).parent))

from fallback import DEF_CONFIG
from gateway_invoke_handler import (
    DEFENSIVE_ASSIGNMENT_TOOL,
    DEFENDER_X_LIMIT,
    DEFENDER_Y_LIMIT,
    GOALKEEPER_EXCLUSION_RADIUS,
    MAX_TOOL_CALLS_PER_TICK,
    MAX_TOOL_TURNS,
    PASS_OPTIONS_TOOL,
    _keep_defender_off_boundaries,
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
        self.calls = []

    def __enter__(self):
        self.active = True
        return self

    def __exit__(self, *args):
        self.active = False
        return False

    def call_tool_sync(self, tool_use_id, name, arguments, read_timeout_seconds=None):
        self.calls.append((name, arguments))
        result = {
            "defensive_assignment": {
                "threats": [{"player_id": 3, "threat_score": 0.9}],
                "recommended_mark": {"player_id": 3, "threat_score": 0.9},
            },
            "pass_options": {"pass_options": [{"target_player_id": 2}]},
        }
        response = {
            "statusCode": 200,
            "body": json.dumps(result[
                "defensive_assignment" if name == DEFENSIVE_ASSIGNMENT_TOOL
                else "pass_options"
            ]),
        }
        return {
            "status": "success",
            "content": [{"text": json.dumps(response)}],
        }


class GatewayInvokeHandlerTests(unittest.TestCase):
    def test_tools_run_directly_and_agent_gets_fresh_state_and_history(self):
        app = _App()
        mcp_client = _MCPClient()
        received_prompt = []

        def agent(prompt, *, limits):
            self.assertTrue(mcp_client.active)
            self.assertEqual(agent.messages, [])
            self.assertEqual(limits, {"turns": MAX_TOOL_TURNS})
            received_prompt.append(prompt)
            agent.messages.append({"role": "user", "content": prompt})
            return (
                '[{"commandType":"MOVE_TO","playerId":1,'
                '"parameters":{"target_x":-50,"target_y":0,"sprint":true}}]'
            )

        agent.messages = []
        create_gateway_invoke_handler(
            app, agent, mcp_client, 1, "DEF",
            lambda *_: [], fallback_cfg=DEF_CONFIG,
        )

        async def invoke():
            payload = {"prompt": {"teamId": 0, "gameState": GAME_STATE}}
            return [item async for item in app.handler(payload, None)]

        output = json.loads(asyncio.run(invoke())[0])
        self.assertFalse(mcp_client.active)
        self.assertIn(
            "Tactical analysis (already computed; use these results, do not call tools)",
            received_prompt[0],
        )
        self.assertIn("recommended opponent player 3", received_prompt[0])
        self.assertEqual(len(mcp_client.calls), 1)
        self.assertEqual(mcp_client.calls[0][0], DEFENSIVE_ASSIGNMENT_TOOL)
        self.assertLessEqual(len(mcp_client.calls), MAX_TOOL_CALLS_PER_TICK)
        self.assertEqual(len(agent.messages), 1)
        second_output = json.loads(asyncio.run(invoke())[0])
        self.assertEqual(len(agent.messages), 1)
        self.assertEqual(second_output, output)
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

    def test_defender_move_target_stays_inside_field_boundaries(self):
        commands = [{
            "commandType": "MOVE_TO",
            "parameters": {"target_x": 55, "target_y": -35},
        }]
        result = _keep_defender_off_boundaries(commands, 1, _Logger())
        self.assertEqual(result[0]["parameters"]["target_x"], DEFENDER_X_LIMIT)
        self.assertEqual(result[0]["parameters"]["target_y"], -DEFENDER_Y_LIMIT)

    def test_pass_options_are_called_only_when_defender_has_ball(self):
        app = _App()
        mcp_client = _MCPClient()

        def agent(prompt, *, limits):
            return '[{"commandType":"MARK","playerId":1,"parameters":{"target_player_id":3,"tightness":"TIGHT"}}]'

        agent.messages = []
        create_gateway_invoke_handler(
            app, agent, mcp_client, 1, "DEF",
            lambda *_: [], fallback_cfg=DEF_CONFIG,
        )
        state = json.loads(json.dumps(GAME_STATE))
        state["ball"]["possessionAgentId"] = "agent_1"
        state["players"][1]["agentId"] = "agent_1"

        async def invoke():
            payload = {"prompt": {"teamId": 0, "gameState": state}}
            return [item async for item in app.handler(payload, None)]

        asyncio.run(invoke())
        self.assertEqual(
            [name for name, _ in mcp_client.calls],
            [DEFENSIVE_ASSIGNMENT_TOOL, PASS_OPTIONS_TOOL],
        )
        self.assertLessEqual(len(mcp_client.calls), MAX_TOOL_CALLS_PER_TICK)

    def test_model_pass_is_not_replaced_by_safe_forward_recommendation(self):
        app = _App()
        mcp_client = _MCPClient()
        mcp_client.call_tool_sync = lambda _, name, __, **___: {
            "status": "success",
            "content": [{
                "text": json.dumps({
                    "statusCode": 200,
                    "body": json.dumps(
                        {"pass_options": [{
                            "target_player_id": 3,
                            "type": "THROUGH",
                            "safe_forward": True,
                            "progress": 12,
                        }]}
                        if name == PASS_OPTIONS_TOOL
                        else {"recommended_mark": None, "threats": []}
                    ),
                }),
            }],
        }

        def agent(prompt, *, limits):
            return (
                '[{"commandType":"PASS","playerId":1,'
                '"parameters":{"target_player_id":0,"type":"GROUND"}}]'
            )

        agent.messages = []
        create_gateway_invoke_handler(
            app, agent, mcp_client, 1, "DEF",
            lambda *_: [], fallback_cfg=DEF_CONFIG,
        )
        state = json.loads(json.dumps(GAME_STATE))
        state["ball"]["possessionAgentId"] = "agentId_1"
        state["ball"]["possessionTeamCode"] = "HOME"
        state["players"][1]["agentId"] = "agentId_1"

        async def invoke():
            payload = {"prompt": {"teamId": 0, "gameState": state}}
            return [item async for item in app.handler(payload, None)]

        output = json.loads(asyncio.run(invoke())[0])
        self.assertEqual(output[0]["commandType"], "PASS")
        self.assertEqual(output[0]["parameters"]["target_player_id"], 0)
        self.assertEqual(output[0]["parameters"]["type"], "GROUND")

    def test_model_mark_is_not_replaced_by_defensive_assignment(self):
        app = _App()
        mcp_client = _MCPClient()
        received_prompt = []
        mcp_client.call_tool_sync = lambda _, name, __, **___: {
            "status": "success",
            "content": [{
                "text": json.dumps({
                    "statusCode": 200,
                    "body": json.dumps(
                        {
                            "recommended_mark": {"player_id": 4},
                            "threats": [{"player_id": 4, "threat_score": 0.9}],
                        }
                        if name == DEFENSIVE_ASSIGNMENT_TOOL
                        else {"pass_options": []}
                    ),
                }),
            }],
        }

        def agent(prompt, *, limits):
            received_prompt.append(prompt)
            return (
                '[{"commandType":"MARK","playerId":1,'
                '"parameters":{"target_player_id":3,"tightness":"TIGHT"}}]'
            )

        agent.messages = []
        create_gateway_invoke_handler(
            app, agent, mcp_client, 1, "DEF",
            lambda *_: [], fallback_cfg=DEF_CONFIG,
        )

        async def invoke():
            payload = {"prompt": {"teamId": 0, "gameState": GAME_STATE}}
            return [item async for item in app.handler(payload, None)]

        output = json.loads(asyncio.run(invoke())[0])
        self.assertEqual(output[0]["parameters"]["target_player_id"], 3)
        self.assertIn('"recommended_mark":{"player_id":4', received_prompt[0])

    def test_covered_model_mark_is_preserved_with_mcp_result_in_context(self):
        app = _App()
        mcp_client = _MCPClient()
        mcp_client.call_tool_sync = lambda _, name, __, **___: {
            "status": "success",
            "content": [{
                "text": json.dumps({
                    "statusCode": 200,
                    "body": json.dumps(
                        {
                            "recommended_mark": None,
                            "action": "HOLD_SHAPE",
                            "threats": [
                                {"player_id": 0, "threat_score": 0.2},
                            ],
                        }
                        if name == DEFENSIVE_ASSIGNMENT_TOOL
                        else {"pass_options": []}
                    ),
                }),
            }],
        }
        fallback_calls = []
        received_prompt = []

        def agent(prompt, *, limits):
            received_prompt.append(prompt)
            return (
                '[{"commandType":"MARK","playerId":1,'
                '"parameters":{"target_player_id":0,"tightness":"LOOSE"},'
                '"duration":5}]'
            )

        def fallback(*_):
            fallback_calls.append(True)
            return []

        agent.messages = []
        create_gateway_invoke_handler(
            app, agent, mcp_client, 1, "DEF",
            fallback, fallback_cfg=DEF_CONFIG,
        )
        state = json.loads(json.dumps(GAME_STATE))
        state["players"][2]["position"] = {"x": 50, "y": 0}

        async def invoke():
            payload = {"prompt": {"teamId": 0, "gameState": state}}
            return [item async for item in app.handler(payload, None)]

        output = json.loads(asyncio.run(invoke())[0])
        self.assertEqual(fallback_calls, [])
        self.assertIn('"action":"HOLD_SHAPE"', received_prompt[0])
        self.assertEqual(output[0]["commandType"], "MARK")
        self.assertEqual(output[0]["parameters"]["target_player_id"], 0)

    def test_model_press_is_not_replaced_when_ball_is_free(self):
        app = _App()
        mcp_client = _MCPClient()
        state = json.loads(json.dumps(GAME_STATE))
        state["ball"]["isFree"] = True
        state["ball"]["possessionAgentId"] = None
        fallback_calls = []

        def agent(prompt, *, limits):
            return (
                '[{"commandType":"PRESS_BALL","playerId":1,'
                '"parameters":{"intensity":0.8}}]'
            )

        def fallback(*_):
            fallback_calls.append(True)
            return [{
                "commandType": "MOVE_TO",
                "playerId": 1,
                "parameters": {"target_x": -20, "target_y": 0, "sprint": False},
            }]

        agent.messages = []
        create_gateway_invoke_handler(
            app, agent, mcp_client, 1, "DEF", fallback, fallback_cfg=DEF_CONFIG,
        )

        async def invoke():
            payload = {"prompt": {"teamId": 0, "gameState": state}}
            return [item async for item in app.handler(payload, None)]

        output = json.loads(asyncio.run(invoke())[0])
        self.assertEqual(fallback_calls, [])
        self.assertEqual(output[0]["commandType"], "PRESS_BALL")

    def test_invalid_stamina_does_not_discard_model_move(self):
        app = _App()
        mcp_client = _MCPClient()
        state = json.loads(json.dumps(GAME_STATE))
        state["players"][1]["stamina"] = None

        def agent(prompt, *, limits):
            return (
                '[{"commandType":"MOVE_TO","playerId":1,'
                '"parameters":{"target_x":-22,"target_y":0,"sprint":true}}]'
            )

        agent.messages = []
        create_gateway_invoke_handler(
            app, agent, mcp_client, 1, "DEF",
            lambda *_: [], fallback_cfg=DEF_CONFIG,
        )

        async def invoke():
            payload = {"prompt": {"teamId": 0, "gameState": state}}
            return [item async for item in app.handler(payload, None)]

        output = json.loads(asyncio.run(invoke())[0])
        self.assertEqual(output[0]["commandType"], "MOVE_TO")
        self.assertTrue(output[0]["parameters"]["sprint"])

    def test_defensive_tool_failure_is_reported_but_agent_still_runs(self):
        app = _App()
        mcp_client = _MCPClient()
        mcp_client.call_tool_sync = lambda *args, **kwargs: {
            "status": "error",
            "content": [],
        }
        fallback_calls = []

        def agent(prompt, *, limits):
            self.assertIn("defensive_assignment_error", prompt)
            return (
                '[{"commandType":"MOVE_TO","playerId":1,'
                '"parameters":{"target_x":-22,"target_y":0,"sprint":false}}]'
            )

        def fallback(*_):
            fallback_calls.append(True)
            return []

        agent.messages = []
        create_gateway_invoke_handler(
            app, agent, mcp_client, 1, "DEF",
            fallback, fallback_cfg=DEF_CONFIG,
        )

        async def invoke():
            payload = {"prompt": {"teamId": 0, "gameState": GAME_STATE}}
            return [item async for item in app.handler(payload, None)]

        output = json.loads(asyncio.run(invoke())[0])
        self.assertEqual(output[0]["commandType"], "MOVE_TO")
        self.assertEqual(fallback_calls, [])
        self.assertTrue(any(
            "get_defensive_assignment failed" in message
            for message in app.logger.messages
        ))


if __name__ == "__main__":
    unittest.main()
