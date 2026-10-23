"""Lambda wrapper for evaluate_shot. Thin adapter over the shared pure function."""

import json

from _impl.evaluate_shot import evaluate_shot


def lambda_handler(event, context):
    body = json.loads(event["body"]) if isinstance(event.get("body"), str) else event
    result = evaluate_shot(
        shooter_position=body["shooter_position"],
        goalkeeper_position=body["goalkeeper_position"],
        team_side=body.get("team_side", "HOME"),
        blocker_positions=body.get("blocker_positions"),
    )
    return {"statusCode": 200, "body": json.dumps(result)}
