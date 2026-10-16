# MR Optimum agent

This directory is the agent-facing layer for MR Optimum.  It does **not** run
MR calculations and it does not replace the Mode 2 worker.  Its responsibility
is to turn a user's request into a small, validated, auditable CloudMR Brain
job.

```text
AgentCore Runtime / LLM
        -> typed tool request
AgentCore Gateway Lambda (tool_adapter/handler.py)
        -> CloudMR Brain queue API
MR Optimum Mode 2 worker (../worker/main.py)
        -> calculation (../calculation/src/app.py)
```

## Boundaries

- The runtime can see only tool schemas and safe tool responses.  It must not
  receive Brain credentials, worker API keys, presigned URLs, or raw S3 keys.
- `tool_adapter/` is the trusted boundary.  In AWS it should run as the Lambda
  target behind an AgentCore Gateway and obtain configuration from an IAM
  protected secret.
- Only registered `dataset_id` values are accepted.  The LLM cannot submit an
  arbitrary CloudMR task JSON.
- A plan is created before submission.  A user-facing application should ask
  for explicit confirmation before calling `submit_mro_run`.
- Diagnostics are technical workflow diagnostics, not clinical interpretation.

## Initial supported profiles

| Profile | Required registered inputs | Purpose |
| --- | --- | --- |
| `ac_rss` | signal, noise | Analytical/Kellman SNR with RSS reconstruction |
| `ac_rss_fa90` | signal, noise, flip-angle map | AC/RSS plus SNR-at-90-degree correction |
| `mr_rss` | repeated signal acquisition | Multiple-replica SNR with RSS reconstruction |

The profile catalogue deliberately starts small.  B1, SENSE, GRAPPA, PMR, and
CR should be added only after their input metadata and validation requirements
are represented in the dataset registry.

## Local setup

```bash
cd agent
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
PYTHONPATH=src pytest
```

`data/datasets.example.json` is documentation only.  Copy it to a protected
runtime location, populate it through the ingestion/registration workflow, and
point `MRO_DATASET_REGISTRY_PATH` at it.  Do not commit production S3 metadata,
credentials, or participant data.

## Lambda environment contract

The deployment layer must supply these values from AWS Secrets Manager or an
equivalent protected configuration mechanism:

```text
CLOUDMR_BRAIN_ROOT=https://brain.aws.cloudmrhub.com/Prod
CLOUDMR_EMAIL=service-account-email
CLOUDMR_PASSWORD=service-account-password
MRO_DATASET_REGISTRY_PATH=/var/task/data/datasets.json
```

The agent runtime role should only be able to invoke the Gateway/tool Lambda.
The tool Lambda role, rather than the runtime role, receives permission to read
the CloudMR credentials.

## Tool adapter event

For local development, invoke `tool_adapter.handler.lambda_handler` with:

```json
{
  "tool": "plan_mro_run",
  "arguments": {
    "profile_id": "ac_rss",
    "signal_dataset_id": "signal-example",
    "noise_dataset_id": "noise-example"
  }
}
```

The `tool_schemas.json` file is the source contract to register as AgentCore
Gateway tool definitions.  Production plan storage must be DynamoDB (or another
durable store); the included memory store is strictly for local development and
tests.
