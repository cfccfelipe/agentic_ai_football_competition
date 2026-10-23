"""Lambda wrapper for get_defensive_assignment. Thin adapter over the shared pure function."""

import json

from _impl.get_defensive_assignment import get_defensive_assignment


def lambda_handler(event, context):
    body = json.loads(event["body"]) if isinstance(event.get("body"), str) else event
    result = get_defensive_assignment(
        opponents=body["opponents"],
        ball=body["ball"],
        team_side=body.get("team_side", "HOME"),
        my_position=body.get("my_position"),
    )
    return {"statusCode": 200, "body": json.dumps(result)}
