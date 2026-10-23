"""Lambda wrapper for calculate_pass_options.

Thin adapter: unwraps the Lambda event, delegates to the shared pure function,
and wraps the result. No tactical logic lives here (DRY — the math is defined
once in plugins/general/scripts/).

deploy_all.py stages the pure-function module next to this file so the import
below resolves inside the Lambda bundle.
"""

import json

from _impl.calculate_pass_options import calculate_pass_options


def lambda_handler(event, context):
    body = json.loads(event["body"]) if isinstance(event.get("body"), str) else event
    result = calculate_pass_options(
        passer_position=body["passer_position"],
        teammates=body["teammates"],
        opponents=body["opponents"],
    )
    return {"statusCode": 200, "body": json.dumps(result)}
