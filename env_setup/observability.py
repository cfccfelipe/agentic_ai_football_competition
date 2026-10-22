
#!/usr/bin/env python3
"""Enable AWS CloudWatch Transaction Search with 1% indexing."""

import json
import logging
import os
import sys
import time

import boto3
from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

POLICY_NAME = "TransactionSearchXRayAccess"
INDEX_PERCENTAGE = 1.0


def main():
    session = boto3.Session()
    region = session.region_name or os.getenv("AWS_REGION")

    if not region:
        raise ValueError("Set AWS_REGION or AWS_DEFAULT_REGION")

    identity = session.client("sts").get_caller_identity()
    account = identity["Account"]
    partition = identity["Arn"].split(":")[1]

    logs = session.client("logs", region_name=region)
    xray = session.client("xray", region_name=region)

    log.info("Account=%s Region=%s", account, region)

    # 1. Configure resource policy without overwriting existing policies.
    policy = {
        "Version": "2012-10-17",
        "Statement": [{
            "Sid": "TransactionSearchXRayAccess",
            "Effect": "Allow",
            "Principal": {"Service": "xray.amazonaws.com"},
            "Action": "logs:PutLogEvents",
            "Resource": [
                f"arn:{partition}:logs:{region}:{account}:log-group:aws/spans:*",
                f"arn:{partition}:logs:{region}:{account}:log-group:/aws/application-signals/data:*",
            ],
            "Condition": {
                "ArnLike": {
                    "aws:SourceArn": f"arn:{partition}:xray:{region}:{account}:*"
                },
                "StringEquals": {"aws:SourceAccount": account},
            },
        }],
    }

    existing = next(
        (p for p in logs.describe_resource_policies().get("resourcePolicies", [])
         if p["policyName"] == POLICY_NAME),
        None,
    )

    if existing:
        if json.loads(existing["policyDocument"]) != policy:
            raise RuntimeError(
                f"{POLICY_NAME} exists with different permissions; review manually"
            )
        log.info("Resource policy already configured")
    else:
        logs.put_resource_policy(
            policyName=POLICY_NAME,
            policyDocument=json.dumps(policy),
        )
        log.info("Resource policy created")

    # 2. Enable ingestion if necessary.
    destination = xray.get_trace_segment_destination()
    if destination.get("Destination") != "CloudWatchLogs":
        xray.update_trace_segment_destination(Destination="CloudWatchLogs")
        log.info("Enabled CloudWatch Logs ingestion")

    # 3. Configure indexing if necessary.
    rules = xray.get_indexing_rules().get("IndexingRules", [])
    default = next((r for r in rules if r["Name"] == "Default"), {})
    current = default.get("Rule", {}).get("Probabilistic", {}).get(
        "DesiredSamplingPercentage"
    )

    if current != INDEX_PERCENTAGE:
        xray.update_indexing_rule(
            Name="Default",
            Rule={"Probabilistic": {
                "DesiredSamplingPercentage": INDEX_PERCENTAGE
            }},
        )
        log.info("Indexing configured: %s%%", INDEX_PERCENTAGE)

    # 4. Verify ingestion and indexing.
    for _ in range(30):
        destination = xray.get_trace_segment_destination()
        if (destination.get("Destination") == "CloudWatchLogs"
                and destination.get("Status") == "ACTIVE"):
            rules = xray.get_indexing_rules().get("IndexingRules", [])
            default = next((r for r in rules if r["Name"] == "Default"), {})
            actual = default.get("Rule", {}).get("Probabilistic", {}).get(
                "DesiredSamplingPercentage"
            )
            if actual != INDEX_PERCENTAGE:
                raise RuntimeError(f"Indexing verification failed: {actual}%")

            log.info("Transaction Search ACTIVE (%s%% indexing)", actual)
            return

        time.sleep(10)

    raise TimeoutError("Transaction Search activation timed out after 300s")


if __name__ == "__main__":
    try:
        main()
    except (BotoCoreError, ClientError, NoCredentialsError,
            ValueError, RuntimeError, TimeoutError) as exc:
        log.error("%s", exc)
        sys.exit(1)
