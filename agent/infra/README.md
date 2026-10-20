# AWS deployment boundary

The implementation files under `src/` and `tool_adapter/` are intentionally
cloud-neutral.  This directory is reserved for the AWS deployment assets that
will connect them to Amazon Bedrock AgentCore.

## Target resources

```text
Bedrock AgentCore Runtime (mro-agent)
    -> AgentCore Gateway
        -> Lambda (MR Optimum tool adapter)
            -> caller's authenticated CloudMR/Cognito context
            -> CloudMR Brain shared endpoint

EventBridge / Step Functions
    -> periodic get_mro_run_status polling
    -> final user notification or diagnostic invocation

DynamoDB
    -> plans, approvals, pipeline IDs, and audit state
```

The tool Lambda does not own an input bucket. New data uploads go directly to
CloudMR Brain's existing upload endpoints and Brain-managed S3 storage; Brain
also creates worker-only download URLs at job submission. If inventory runs in
AWS, package `dat_inventory.py` and its `mrotools`/`twixtools` dependencies in
an inventory-capable image. It must use a Brain-authorized temporary download,
not a developer's external-disk path.

## IAM split

| Principal | Required capability |
| --- | --- |
| AgentCore Runtime role | Invoke its Gateway only |
| Gateway/tool Lambda role | Call the HTTPS Brain endpoint with delegated caller identity; read/write its DynamoDB table |
| Monitoring workflow role | Read the same pipeline state and update the run table |

Do not grant the runtime role worker API-key access, unrestricted Secrets
Manager access, or direct access to input/result buckets.

## Required production change before deployment

`InMemoryPlanStore` is provided for local development and unit tests.  Replace
it with a DynamoDB-backed implementation before exposing `plan_mro_run` and
`submit_mro_run` as separate remote tool calls.  Lambda memory is not durable
across cold starts and cannot serve as confirmation/audit state.
