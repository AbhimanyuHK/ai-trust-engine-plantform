# Contract Intelligence

Contract Intelligence owns contract-document ingestion, version-aware evidence
preparation, Snowflake persistence, Cortex Search retrieval, and grounded Q&A.

It does **not** own royalty calculations or decide which extracted contractual
terms become legally active. Extracted terms are proposals; verified and approved
terms belong in a structured Snowflake contract-terms model and are used by
downstream royalty calculations.

## Architecture and storage boundaries

| Concern | System of record | Responsibility |
|---|---|---|
| Original PDFs and amendments | Amazon S3 (or governed Snowflake stage) | Immutable source documents |
| Extracted JSON / chunk JSONL / manifests | S3, when durable replay/audit artifacts are required | Reprocessing and traceability |
| Document metadata, versions, chunks, approval/audit status | Snowflake | Governed relational records |
| Semantic and keyword retrieval | Snowflake Cortex Search | Search over approved/indexable chunk rows |
| Workflow execution and HITL | LangGraph + durable checkpointer | Orchestration, pause/resume |
| Validated royalty terms | Snowflake contract-terms tables | Authoritative values for calculations |

S3 is the source-artifact store; Snowflake is the governed metadata, chunk,
business-data and workflow-status store. Cortex Search is an index, not the
authoritative contract store.

## S3 key layout

Use separate AWS accounts/buckets for production and non-production where
required by the security model. Environment prefixes are useful organization,
but are not a substitute for IAM/bucket-policy isolation.

Example:

```text
s3://ai-trust-engine-prod/
├── incoming/YYYY/MM/DD/<upload-id>/<original-filename>
└── contracts/<partner_id>/<contract_id>/
    └── document-versions/
        ├── v0001/
        │   ├── original/<document-id>.pdf
        │   ├── extracted/extracted.json
        │   ├── chunks/chunks.jsonl
        │   └── manifests/manifest.json
        └── v0002/
            ├── original/<document-id>.pdf
            ├── extracted/extracted.json
            ├── chunks/chunks.jsonl
            └── manifests/manifest.json
```

The upload service should place each source PDF at an immutable, unique key.
Do not overwrite a prior original. Enable S3 Versioning, encryption (preferably
SSE-KMS), least-privilege access, retention/lifecycle policies, and optionally
S3 Object Lock when required by legal/compliance policy.

### No permanent processing folder

A permanent `processing/` tree is intentionally **not** part of the design.
Execution state (stage, attempts, errors, timestamps, retry/resume information)
belongs in the workflow-status store/checkpointer. During parsing, an S3 object
may be downloaded to an OS temporary directory and removed automatically.
Persist extracted JSON, chunks and manifests under the durable document-version
prefix only when replay, audit, or debugging requirements justify keeping them.
For short-lived diagnostics, use logs/metrics or a lifecycle-managed temporary
prefix rather than creating a permanent per-stage directory.

## Amendment and version handling

Never edit Version 1 chunks in place when an amendment arrives.

Example: the original contract has a 10% royalty effective 2026-01-01 through
2026-06-30; an approved amendment changes it to 12% effective 2026-07-01.

1. Upload the amendment as a new immutable source document.
2. Assign a new `DOCUMENT_ID` and increment `DOCUMENT_VERSION` /
   `CONTRACT_VERSION` according to the contract's versioning policy.
3. Extract and chunk the amendment independently; preserve document, page,
   clause, source URI, content hash, parser version and chunking version.
4. Compare the amendment with the previous applicable clauses.
5. Route proposed changes to Finance / Partner Relations for review.
6. On approval and required signature/acceptance verification, write a new
   effective-dated row to the structured contract-terms history.
7. Retain old chunks and terms for historical questions and audit. Refresh the
   Cortex Search index and filter by contract/version/effective date as needed.

Do not rely on a folder name, an LLM answer, or a mutable `IS_CURRENT` flag alone
to determine the applicable royalty rate. Enforce non-overlapping effective
periods and select terms using the transaction's business date. Retroactive
amendments must trigger an auditable impact assessment and adjustment workflow.

## Ingestion flow

```text
S3 original PDF / amendment
        |
        v
ingest_pdf() -- download S3 object to OS temp directory when needed
        |
        +--> SHA-256 content hash + immutable document ID
        +--> register AI.DOCUMENTS (reject ID/hash conflicts)
        +--> record DOCUMENT_REGISTRATION status
        +--> PDF_EXTRACTION: RUNNING -> SUCCEEDED / FAILED
        +--> page-aware overlapping chunk generation
        +--> CHUNK_PERSISTENCE: RUNNING -> SUCCEEDED / FAILED
        +--> optional ARTIFACT_PERSISTENCE status + versioned S3 artifacts
        +--> finalize AI.DOCUMENTS.INGESTION_STATUS
                         |
                         v
                Cortex Search service
                         |
                         v
                grounded retrieval / Q&A
```

Chunking is page-aware and overlapping. The current implementation uses
whitespace-token (word) counts for `chunk_size` and `overlap`; these are **not
model-token counts**. Tune chunk size against actual Cortex Search retrieval
quality and embedding-model limits. Preserve clause boundaries where possible;
for large clauses, split recursively while retaining the clause/page metadata.

## Python API

```python
from trust_engine.contract_intelligence import ingest_pdf

chunks = ingest_pdf(
    "s3://ai-trust-engine-prod/contracts/PARTNER_1001/C1001/"
    "document-versions/v0002/original/DOC002.pdf",
    contract_id="C1001",
    partner_id="PARTNER_1001",
    document_id="DOC002",
    document_version=2,
    contract_version=2,
    document_type="AMENDMENT",
    effective_date="2026-07-01",
    artifact_bucket="ai-trust-engine-prod",  # optional durable JSON artifacts
)
```

For transient failures, use the bounded retry wrapper with a stable
`document_id` and `run_id`. It retries only the exception classes explicitly
listed by the caller (the default is `TimeoutError` and `ConnectionError`),
records `INGESTION_RETRY` as `RETRYING` / `SUCCEEDED` / `FAILED`, and applies
exponential backoff. Add the Snowflake connector's transient exception classes
to `retryable_exceptions` only after validating the exception taxonomy for the
installed connector version.

```python
from snowflake.connector.errors import OperationalError
from trust_engine.contract_intelligence import retry_ingest_pdf

chunks = retry_ingest_pdf(
    "s3://ai-trust-engine-prod/contracts/PARTNER_1001/C1001/"
    "document-versions/v0002/original/DOC002.pdf",
    contract_id="C1001",
    partner_id="PARTNER_1001",
    document_id="DOC002",
    run_id="INGEST-RUN-2026-00042",
    document_version=2,
    contract_version=2,
    document_type="AMENDMENT",
    max_attempts=3,
    retryable_exceptions=(TimeoutError, ConnectionError, OperationalError),
    base_delay_seconds=2,
)
```

A replay uses the same document/run identifiers and deterministic chunk IDs;
chunk persistence is implemented with Snowflake `MERGE`, so a retry can safely
reprocess a stage that completed before a later stage failed. This is at-least-
once execution with idempotent writes, not a distributed transaction across S3
and Snowflake. Keep retry limits bounded and do not classify validation,
authorization, malformed-PDF, or other deterministic errors as transient.

For local PDFs, pass a filesystem path. For S3 URIs, install the optional AWS
extra and configure the standard AWS SDK credentials/role:

```bash
pip install -e ".[aws]"
```

S3 upload and canonical source-key creation are owned by the upload/API layer.
The ingestion function reads an existing source object; it does not silently
move or overwrite the original PDF.

## Snowflake schema

Apply the canonical scripts under `sql/ddl/ai/` before enabling persistence.
For a new environment, run the create script; for an existing environment,
review and run the additive upgrade script as appropriate. Keep document
metadata and structured, approved contract terms in separate tables; do not
calculate royalties from retrieved chunk text.

Configure Cortex Search to expose the chunk text and useful filter attributes,
including `CONTRACT_ID`, `PARTNER_ID`, `DOCUMENT_ID`, `DOCUMENT_VERSION`,
`CONTRACT_VERSION`, and effective dates where supported. Search results should
return source document, page and clause references for citations.

## Snowflake SQL layout and deployment

Snowflake DDL and DML are maintained separately at the repository root:

```text
sql/
├── ddl/ai/
│   ├── 001_create_contract_intelligence_tables.sql
│   └── 002_upgrade_document_chunks.sql
└── dml/ai/
    ├── 001_document_registry_and_status.sql
    └── 002_contract_terms.sql
```

### Deployment order

1. For a new environment, run `sql/ddl/ai/001_create_contract_intelligence_tables.sql`.
   It creates schema `AI` and the `DOCUMENTS`, `DOCUMENT_CHUNKS`,
   `CONTRACT_TERMS`, `DOCUMENT_INGESTION_STATUS` tables plus the
   `APPROVED_CONTRACT_TERMS` view.
2. For an existing environment with an older `AI.DOCUMENT_CHUNKS` table, run
   `sql/ddl/ai/002_upgrade_document_chunks.sql` to add lineage/provenance columns.
   The upgrade is additive; it does not fabricate document IDs or version values.
3. Use the scripts under `sql/dml/ai/` as operational templates. Replace every
   `replace-with-...` value and review the SQL before execution. Do not run the
   templates unchanged.
4. Register each immutable source document before/alongside ingestion, record
   each processing stage in `DOCUMENT_INGESTION_STATUS`, and mark the document
   complete only after all required stages succeed.
5. Add a row to `CONTRACT_TERMS` only after human review and required legal /
   signature verification. Preserve historical terms and use effective dates
   when selecting the term for a transaction.

Snowflake standard-table primary-key and unique constraints are informational
rather than enforced. The application must preserve uniqueness through stable
IDs, idempotent MERGE operations, and validation queries. The SQL DML examples
are templates; the Python ingestion implementation currently persists chunks,
while document-registry/status writes must be wired into the orchestration layer
before treating those tables as automatically maintained.

## Operational requirements

- Make ingestion idempotent using document IDs, version IDs and SHA-256 hashes.
- Retry only classified transient failures with a stable run/document ID, bounded attempts and observable retry status.
- Record parser/chunking versions so artifacts can be regenerated after code changes.
- Preserve original PDFs and historical versions; do not overwrite chunks on amendment.
- Keep approval state and workflow status in Snowflake/checkpointer, not S3 folders.
- Apply partner-level authorization before returning contract evidence.
- Treat OCR output and LLM-extracted terms as untrusted until validated.
- Test S3, Snowflake and Cortex integration in a non-production environment before deployment.

## Contract Intelligence workflow orchestration

The LangGraph orchestration entry point is
\`trust_engine.workflows.contract_intelligence_workflow\`. It calls the public
Contract Intelligence ingestion API; it does not implement PDF parsing, OCR,
chunking, embedding generation, or Snowflake chunk persistence itself.

Usage:

    from trust_engine.workflows import (
        get_contract_intelligence_workflow_status,
        list_contract_intelligence_workflow_events,
        start_contract_intelligence_workflow,
    )

    result = start_contract_intelligence_workflow(
        "s3://ai-trust-engine-prod/contracts/PARTNER_1001/C1001/document-versions/v0002/original/DOC002.pdf",
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

The workflow requires a stable caller-supplied document_id and stores its
replayable request payload in AI.CONTRACT_INTELLIGENCE_WORKFLOW_RUNS.
Current status is maintained in that table; append-only lifecycle events are
written to AI.CONTRACT_INTELLIGENCE_WORKFLOW_EVENTS. Fine-grained document
processing stages remain in AI.DOCUMENT_INGESTION_STATUS.

If a process exits unexpectedly, call
resume_contract_intelligence_workflow(run_id). Resume replays ingestion using
the same run/document identifiers. Deterministic chunk IDs and Snowflake MERGE
writes make this at-least-once replay idempotent; it is not a restoration of an
in-memory LangGraph node checkpoint. Local file sources can only be resumed
where the same file path remains accessible; immutable S3 source URIs are
preferred for durable recovery.

After extraction and chunk persistence, the workflow issues a manual Cortex
Search refresh and waits for the matching row in
INFORMATION_SCHEMA.CORTEX_SEARCH_REFRESH_HISTORY to reach SUCCEEDED. Workflow
status becomes COMPLETED only after the refresh succeeds. The wait is bounded
(default 600 seconds); failure or timeout is recorded as FAILED at
CORTEX_SEARCH_INDEXING. The execution role needs OPERATE on the Cortex Search
service. Cortex Search owns embedding generation/indexing, so the workflow does
not create a duplicate embedding vector column. The service must select from
AI.DOCUMENT_CHUNKS and expose the metadata columns used by search_contracts().

Apply sql/ddl/ai/003_contract_intelligence_workflow.sql after the base
Contract Intelligence DDL. Snowflake standard-table key constraints are
informational; use stable run IDs, application-level duplicate checks and
idempotent writes. Do not start the workflow before the DDL is deployed and
the Snowflake role has the required table privileges.


### Workflow deployment additions

The contract-intelligence orchestration requires two additional Snowflake scripts:

- `sql/ddl/ai/003_contract_intelligence_workflow.sql` creates the workflow run and event tables.
- `sql/ddl/ai/004_create_contract_search_service.sql` creates the managed Cortex Search service over `AI.DOCUMENT_CHUNKS`.

Run both after the base document/chunk DDL. Confirm `TRUST_WH` exists and the deployment role has Cortex Search creation and embedding privileges. Cortex Search manages embeddings and refreshes asynchronously; workflow completion means chunk persistence succeeded, not that every chunk is already searchable.


## Contract clause and royalty-term extraction

After document ingestion, call the extraction API:

```python
from trust_engine.contract_intelligence import (
    extract_contract_terms,
    validate_amendment_precedence,
)

candidates = extract_contract_terms("DOC002")
validation = validate_amendment_precedence("DOC002")
```

Extraction uses Cortex LLM output only as an untrusted proposal. Each candidate
must include a verbatim evidence quote found in its source chunk. Unsupported
quotes, invalid percentages and invalid date ranges are rejected. Document,
contract-version, page and clause lineage are copied from Snowflake chunk
metadata, not invented by the model. Overlapping chunks are de-duplicated by
stable candidate IDs. Candidates are persisted to
`AI.CONTRACT_TERM_CANDIDATES` with `PENDING` status; extraction never approves
or activates contractual terms. Pass `persist=False` to return candidates
without writing them.

`validate_amendment_precedence(document_id)` checks amendment parent lineage,
contract identity, monotonically increasing contract version, explicit
amendment effective date, and date overlaps between proposals and approved
terms. It returns `VALID`, `REVIEW_REQUIRED`, or `INVALID` with findings.
Overlaps require authorized review; the function never silently changes
historical approved terms or determines legal precedence from version number
alone.

Deploy `sql/ddl/ai/005_contract_term_candidates.sql` after the base Contract
Intelligence DDL. The extraction process requires Cortex LLM access and
Snowflake read/write privileges. The candidate table is a review queue, not
the authoritative terms table. Only an authorized approval process should
promote a reviewed proposal into `AI.CONTRACT_TERMS`; downstream calculations
must continue to read `AI.APPROVED_CONTRACT_TERMS` using the transaction's
business date.
