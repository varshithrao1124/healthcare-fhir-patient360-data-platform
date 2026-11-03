# Azure deployment

This guide describes a deployment that matches the Bicep and the Databricks bundle. **It was not executed.** No Azure subscription, service principal, or workspace was available. Bicep CLI 0.38.33 compiled `infra/bicep/main.bicep` locally with no errors. That is a compile, not a deployment.

## What the template creates

`infra/bicep/main.bicep` is a resource-group deployment:

| Module | Resource |
| --- | --- |
| storage | ADLS Gen2 account and containers `landing`, `capture`, `conform`, `insight`, `quarantine` |
| eventhubs | Standard namespace with Kafka enabled, hubs `hl7-v2` and `fhir-r4` |
| keyvault | RBAC vault. Secret names to create after deploy: `token-salt`, `eventhub-connection`, `databricks-token` |
| monitor | Log Analytics workspace and an Application Insights component |
| datafactory | Factory with a system-assigned identity |
| databricks | Premium workspace. Its managed resource group name is a parameter and is not the same group as the workspace |
| healthdata | Healthcare APIs workspace and an R4 FHIR service with SMART proxy enabled |

Parameters live in `infra/bicep/parameters.example.json`. Replace `tenantId` and `uniqueSuffix` before any real deployment. Storage and Event Hubs names must be globally unique.

## Suggested order

1. Create a resource group, for example `rg-acn-alderbrook`.
2. `az deployment group create --resource-group rg-acn-alderbrook --template-file infra/bicep/main.bicep --parameters @infra/bicep/parameters.example.json`
3. Store the token salt, the Event Hubs connection string, and a Databricks token in Key Vault. Do not put them in git.
4. Point the FHIR service `$export` at the `landing` container.
5. Create a Databricks secret scope `alderbrook` backed by that vault.
6. From a machine with `DATABRICKS_HOST` and `DATABRICKS_TOKEN`, run `databricks bundle deploy --target prod`.
7. Import `orchestration/adf/pipeline_daily_conform.json` and attach a Databricks linked service whose token is a Key Vault reference.
8. Apply `sql/unity/catalog.sql` and `sql/unity/masking.sql` in a workspace that has a metastore.
9. Publish `reporting/powerbi/measures.dax` against `acn_prod.deidentified`. That file was not opened in the Power BI service.

## Runtime settings

`configs/azure.yml.example` selects `transport: kafka`. The job reads:

- `EVENT_HUBS_BOOTSTRAP`
- `EVENT_HUBS_CONNECTION_STRING`
- `EVENT_HUB_NAME`
- `ACN_TOKEN_SALT`
- `AZURE_STORAGE_ACCOUNT`

The Kafka source uses SASL SSL and PLAIN, which is the Event Hubs Kafka endpoint. `capture/transports.py` raises if those values are missing. The local pipeline never calls it.

Streaming checkpoints belong on ADLS (`checkpoint_uri` in the example config). Deleting a checkpoint replays the hub; the merge on `event_id` keeps capture idempotent. Interpretation is rebuilt from capture, so a replay does not duplicate a visit.

## Continuous capture and the daily conform

`databricks/jobs.yml` defines two jobs on Databricks Runtime 14.3 LTS:

- `alderbrook-capture-stream` is a continuous job, paused until someone unpauses it.
- `alderbrook-daily-conform` is 06:00 America/Los_Angeles and runs the Python entry point.

The Data Factory pipeline waits for a file in the bulk-export dataset and then starts the conform job. The dataset and linked service are names, not embedded credentials.

## GitHub Actions

`.github/workflows/cd-azure.yml` runs on `workflow_dispatch` and on pushes to `main`. If `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, or `AZURE_SUBSCRIPTION_ID` is empty, the deploy job is skipped and the workflow succeeds. When they are present it deploys the Bicep and, only if Databricks secrets are also present, the bundle.

`.github/workflows/ci.yml` does not need Azure. It lints, runs the test suite, and runs the smoke profile.

## Monitoring that stays unwired locally

`platform/telemetry.py` appends JSON lines to `evidence/metrics.jsonl`. If `APPLICATIONINSIGHTS_CONNECTION_STRING` is set, a hosted job would forward those records. This process does not open that connection. Metric names already used:

- `alderbrook.capture.events`
- `alderbrook.capture.late`
- `alderbrook.mpi.review_queue`
- `alderbrook.assure.quarantine`
- `alderbrook.mpi.golden`
