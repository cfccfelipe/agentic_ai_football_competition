# Observability

Does the same as:
```
This is a one-time setup. Transaction Search enables trace and span visualization in CloudWatch. After enabling, it can take up to ten minutes for spans to become available.

Open the Amazon CloudWatch console 
In the left navigation pane, under Setup, choose Settings
Select the Account tab, then choose the X-Ray traces tab
In the Transaction Search section, choose View settings
On the page that opens, choose Edit
Choose Enable Transaction Search
Select For X-Ray users and set the indexing percentage (1% is free)
Choose Save — wait until Ingest OpenTelemetry spans shows Enabled
```

Run:
```
pip install boto3

AWS_PROFILE=my-profile \
AWS_REGION=us-east-1 \
python observability.py
```
Or using existing environment credentials:
```
AWS_REGION=us-east-1 python enable_transaction_search.py
```
