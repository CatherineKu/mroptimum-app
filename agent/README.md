# MR Optimum agent

This directory is the agent-facing layer for MR Optimum.  It does **not** run
MR calculations and it does not replace the Mode 2 worker.  Its responsibility
is to turn a user's request into a small, validated, auditable CloudMR Brain
job.

```text
AgentCore Runtime / LLM
        -> typed tool request
AgentCore Gateway Lambda (tool_adapter/handler.py)
        -> CloudMR Brain data + queue APIs
CloudMR Brain data catalogue / S3
        -> authorised MR Optimum input references
MR Optimum Mode 2 worker (../worker/main.py)
        -> calculation (../calculation/src/app.py)
        -> CloudWatch Logs (read-only technical diagnostics)
```

## Boundaries

- The runtime can see only tool schemas and safe tool responses.  It must not
  receive Brain credentials, worker API keys, presigned URLs, or raw S3 keys.
- `tool_adapter/` is the trusted boundary.  In AWS it should run as the Lambda
  target behind an AgentCore Gateway and obtain configuration from an IAM
  protected secret.
- The user-facing interface works with CloudMR Brain `file_id` values, never
  arbitrary bucket/key pairs or arbitrary task JSON. A trusted adapter resolves
  a selected ID only after checking that the file belongs to the caller or is
  approved CloudMR demo data.
- A plan is created before submission.  A user-facing application should ask
  for explicit confirmation before calling `submit_mro_run`.
- Diagnostics are technical workflow diagnostics, not clinical interpretation.

## Worker-log diagnostics

`get_mro_run_logs(pipeline_id)` is the read-only bridge between a CloudMR
pipeline and the worker's CloudWatch log stream. It looks for the exact
pipeline ID that the worker logs before calculation, reads only the matched
stream within a bounded window around the pipeline's last update, and removes
credentials, presigned URLs, storage locations, and temporary paths. This is
the evidence source for a later LLM diagnosis; it does not itself claim a
scientific cause or repair a run.

The deployed AgentCore runtime should use its IAM role. For local development
only, add these non-secret settings to your shell or local `.env` file:

```text
MRO_CLOUDWATCH_AWS_PROFILE=mroptimum
MRO_CLOUDWATCH_REGION=us-east-1
MRO_CLOUDWATCH_LOG_GROUP=/ecs/mroptimum-worker-mode2
```

The identity requires only `logs:DescribeLogStreams`, `logs:GetLogEvents`, and
`logs:FilterLogEvents` on that worker's log group. It must not receive write,
worker-management, or broad account-log permissions.

## Initial supported profiles

| Profile | Required selected inputs | Purpose |
| --- | --- | --- |
| `ac_rss` | signal, noise | Analytical/Kellman SNR with RSS reconstruction |
| `ac_rss_fa90` | signal, noise, flip-angle map | AC/RSS plus SNR-at-90-degree correction |
| `mr_rss` | repeated signal acquisition | Multiple-replica SNR with RSS reconstruction |

The profile catalogue deliberately starts small. B1, SENSE, GRAPPA, PMR, and
CR should be added only after their input metadata and validation requirements
are represented in CloudMR's dataset metadata catalogue.

## Data ingestion flow

CloudMR Brain is the authoritative catalogue and storage system. The agent
does **not** maintain a second input bucket or a parallel production registry.
It presents only files that CloudMR Brain authorizes for the signed-in user:

```text
signed-in user
  -> list CloudMR files for "MR Optimum"
     -> user's own files + explicitly shared demo files
  -> select a signal file and, where required, a noise file
  -> validate file IDs, ownership/sharing, upload completion, and compatibility
  -> read or create derived MR metadata
       (vendor, multiraid, coils, geometry, replicas, checksum)
  -> build the approved MR Optimum task JSON
  -> submit through CloudMR Brain to the user's Mode 2 computing unit
  -> Brain creates short-lived worker download URLs internally
```

For a new upload, the UI calls Brain's existing upload-initiate/finalize APIs
and uploads directly to Brain-managed S3. The resulting CloudMR `file_id` is
then selectable like any other file. For large `.dat` inputs, use Brain's
multipart upload path. The agent should never proxy raw imaging data through
the LLM, AgentCore runtime, or an agent-owned bucket.

The earlier agent-owned storage, upload-registration, and JSON-registry flow
has been removed. `list_mro_files` now reads the live MR Optimum catalogue
directly through CloudMR Brain using the shared agent identity. A later trusted
file resolver will add scientific role and compatibility checks for planning.

`select_mro_files` is the next read-only step: it rechecks that a user-chosen
signal ID and noise ID are still available to the shared agent. It does not
classify those files scientifically, construct a task, or submit a job.

For one controlled end-to-end integration test only,
`submit_brain_multislice_demo_ac_rss(confirm=true)` queues the curated
`BrainMultiSliceSignal.dat` / `BrainMultiSliceNoise.dat` pair with the verified
AC/RSS settings. It obtains the current Brain locations at call time and lets
Brain issue worker download URLs. It is not a general selected-file submission
tool and must not be extended to arbitrary files before the metadata layer is
implemented.

Immediately before any Mode 2 submission, the trusted adapter resolves the
single active MR Optimum Mode 2 computing unit and pins its
`computing_unit_id` into the queue request. It deliberately removes the
optional `mode` selector once the exact ID is known, because the current Brain
queue implementation can otherwise treat `mode` as a fallback and overwrite an
API-based unit that has no Step Functions ARN. It reports a submission as
verified only when Brain's response confirms that same ID.

### Catalogue rules

- Query Brain with `cloudapp_name=MR Optimum`; `/api/data` otherwise defaults
  to `TESS`.
- A normal user sees files they own plus records explicitly marked as
  `is_demo_data: true`. Admin-owned example files must be marked demo data to
  appear for other users.
- The LLM receives safe metadata such as `file_id`, filename, size, role, and
  inventory summary. It must not receive S3 keys, presigned URLs, CloudMR
  credentials, or raw file bytes.
- During the shared-agent MVP, the file-list tool returns only `file_id`,
  filename, size, upload status, and whether the entry is shared demo data or
  belongs to the shared agent account.
- Inventory metadata is derived data keyed by CloudMR `file_id` (and ideally a
  checksum/version). It is not a second file-storage system.
- Validate that uploaded objects exist and are complete before allowing a
  submission: Brain creates a file record before a multipart upload finalizes.

## Local setup

```bash
cd agent
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
PYTHONPATH=src pytest
```

Raw `.dat` files and derived inventory artifacts are local development data
only. Do not commit participant data, production S3 metadata, or credentials.
Production file selection starts from the Brain catalogue and resolves each
selected CloudMR `file_id` server-side.

## Target production environment contract

After the CloudMR-Brain catalogue adapter is implemented, the deployment layer
will supply these values from AWS Secrets Manager or an equivalent protected
configuration mechanism:

```text
CLOUDMR_BRAIN_ROOT=https://brain.aws.cloudmrhub.com/Prod
MRO_DAT_INVENTORY_SCRIPT=/opt/app/tools/dat_inventory.py  # inventory worker only
MRO_INVENTORY_ROOT=/tmp/mro-inventory                       # ephemeral workspace only
```

The agent runtime role should only invoke the Gateway/tool Lambda. The tool
adapter must preserve the end user's CloudMR/Cognito identity when it calls
Brain, so Brain can enforce ownership. It should not use a shared account to
list or submit a user's files. Any inventory component receives only the least
privilege needed to read the selected Brain-managed object; the Mode 2 worker
receives the short-lived download URL that Brain creates at submission time.

## Tool adapter event

For local development, invoke `tool_adapter.handler.lambda_handler` with:

```json
{
  "tool": "plan_mro_run",
  "arguments": {
    "profile_id": "ac_rss",
    "signal_file_id": "cloudmr-signal-file-id",
    "noise_file_id": "cloudmr-noise-file-id"
  }
}
```

The final block shows the **target production contract**. The checked-in tool
schemas now use `*_file_id` names, but do not register the catalogue-dependent
tools until the authenticated Brain catalogue adapter is implemented.
Production plan storage must be DynamoDB (or another durable store); the
included memory store is strictly for local development and tests.
