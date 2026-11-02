# Workflows

Workflows own orchestration and execution lifecycle. They call independently
testable business capabilities; they do not implement PDF parsing, OCR,
chunking, embedding generation, or contract-term extraction themselves.

## Contract Intelligence ingestion

Entry point: `trust_engine.workflows.contract_intelligence_workflow`

The graph coordinates the public ingestion API in
`trust_engine.contract_intelligence.ingestion`:

```text
Immutable PDF in S3 / accessible local path
        |
        v
LangGraph: contract_intelligence_workflow
        |
        v
retry_ingest_pdf()
        |
        +--> PDF text extraction / OCR fallback
        +--> page-aware chunking and provenance
        +--> document registry in Snowflake
        +--> chunk MERGE into AI.DOCUMENT_CHUNKS
        +--> per-stage status in AI.DOCUMENT_INGESTION_STATUS
        |
        v
Cortex Search service refreshes asynchronously
```

Contract Intelligence owns the processing. LangGraph invokes it and manages
workflow-level execution. Snowflake owns current workflow status and event
history. Cortex Search owns managed embeddings and search indexing; the
workflow does not generate a duplicate vector column.

### Snowflake workflow state

Apply these scripts in order:

1. `sql/ddl/ai/001_create_contract_intelligence_tables.sql`
2. `sql/ddl/ai/002_upgrade_document_chunks.sql` only for an existing older chunk table
3. `sql/ddl/ai/003_contract_intelligence_workflow.sql`
4. `sql/ddl/ai/004_create_contract_search_service.sql`

The workflow writes:

- `AI.CONTRACT_INTELLIGENCE_WORKFLOW_RUNS`: current status, stage, attempt,
  source identifiers, replayable request payload, chunk count and errors.
- `AI.CONTRACT_INTELLIGENCE_WORKFLOW_EVENTS`: append-only lifecycle events.
- `AI.DOCUMENT_INGESTION_STATUS`: detailed document processing stage status.

Snowflake standard-table primary/unique constraints are informational. Use
stable run/document IDs, application-level duplicate checks and idempotent
MERGE writes. The workflow requires the DDL to be deployed and its execution
role to have the required table and Cortex Search privileges.

### Start and inspect

```python
from trust_engine.workflows import (
    get_contract_intelligence_workflow_status,
    list_contract_intelligence_workflow_events,
    start_contract_intelligence_workflow,
)

result = start_contract_intelligence_workflow(
    "s3://ai-trust-engine-prod/contracts/PARTNER_1001/C1001/"
    "document-versions/v0002/original/DOC002.pdf",
    contract_id="C1001",
    partner_id="PARTNER_1001",
    document_id="DOC002",
    document_version=2,
    contract_version=2,
    document_type="AMENDMENT",
    run_id="CI-C1001-DOC002-INGEST-001",
    max_attempts=3,
)

status = get_contract_intelligence_workflow_status(result["run_id"])
events = list_contract_intelligence_workflow_events(result["run_id"])
```

A stable caller-supplied `document_id` is required. The run ID is generated
when omitted. A duplicate run ID is rejected.

### Resume and idempotency

If a process exits unexpectedly, call
`resume_contract_intelligence_workflow(run_id)`. It reads the stored request
from Snowflake and replays ingestion with the same run/document IDs.
Deterministic chunk IDs and Snowflake MERGE make this at-least-once replay
idempotent. This is replay from the durable request, not restoration of an
in-memory LangGraph node checkpoint. S3 source URIs are preferred for recovery;
a local path can only be resumed where the same file remains accessible.

After PDF extraction and chunk persistence, the workflow issues
`ALTER CORTEX SEARCH SERVICE ... REFRESH` and waits for the corresponding
`CORTEX_SEARCH_REFRESH_HISTORY` record to reach `SUCCEEDED`. The workflow
is marked `COMPLETED` only after that refresh succeeds. The wait is bounded
(default 600 seconds); a refresh failure or timeout marks the run `FAILED`
at `CORTEX_SEARCH_INDEXING`. The manual refresh is in addition to the
service's normal `TARGET_LAG` schedule. The execution role needs the
`OPERATE` privilege on the Cortex Search service. The configured service name defaults to
`TRUST_DB.AI.CONTRACT_SEARCH_SERVICE` and uses
`snowflake-arctic-embed-l-v2.0` for managed embeddings. Snowflake documents
the service's managed embedding and refresh behavior in its
[CREATE CORTEX SEARCH SERVICE reference](https://docs.snowflake.com/en/sql-reference/sql/create-cortex-search).

## Other workflows

`contract_recommendation.py` is a separate recommendation/HITL workflow.
Its earlier implementation still contains a SQLite registry/checkpointer and
has not yet been migrated to the Snowflake-only workflow-state architecture.
Do not treat that legacy implementation as satisfying the Snowflake workflow
status requirement. It must be migrated before production use.
