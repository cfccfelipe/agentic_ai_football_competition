"""Lambda wrapper for find_open_space. Thin adapter over the shared pure function."""

import json

from _impl.find_open_space import find_open_space


def lambda_handler(event, context):
    body = json.loads(event["body"]) if isinstance(event.get("body"), str) else event
    result = find_open_space(
        opponent_positions=body["opponent_positions"],
        zone=body.get("zone", "attack"),
        team_side=body.get("team_side", "HOME"),
        my_position=body.get("my_position"),
    )
    return {"statusCode": 200, "body": json.dumps(result)}
