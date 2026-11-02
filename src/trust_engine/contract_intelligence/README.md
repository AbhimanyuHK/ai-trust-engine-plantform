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
        +--> SHA-256 content hash
        +--> PDF text extraction (OCR fallback for image-only pages)
        +--> page-aware overlapping chunk generation
        +--> optional durable extracted/chunk/manifest artifacts in S3
        +--> idempotent Snowflake chunk persistence
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

For local PDFs, pass a filesystem path. For S3 URIs, install the optional AWS
extra and configure the standard AWS SDK credentials/role:

```bash
pip install -e ".[aws]"
```

S3 upload and canonical source-key creation are owned by the upload/API layer.
The ingestion function reads an existing source object; it does not silently
move or overwrite the original PDF.

## Snowflake schema

Apply `contract_intelligence_schema.sql` before enabling persistence. The
migration adds document/version lineage and processing provenance columns to
`AI.DOCUMENT_CHUNKS`. Keep document metadata and structured, approved contract
terms in separate tables; do not calculate royalties from retrieved chunk text.

Configure Cortex Search to expose the chunk text and useful filter attributes,
including `CONTRACT_ID`, `PARTNER_ID`, `DOCUMENT_ID`, `DOCUMENT_VERSION`,
`CONTRACT_VERSION`, and effective dates where supported. Search results should
return source document, page and clause references for citations.

## Operational requirements

- Make ingestion idempotent using document IDs, version IDs and SHA-256 hashes.
- Record parser/chunking versions so artifacts can be regenerated after code changes.
- Preserve original PDFs and historical versions; do not overwrite chunks on amendment.
- Keep approval state and workflow status in Snowflake/checkpointer, not S3 folders.
- Apply partner-level authorization before returning contract evidence.
- Treat OCR output and LLM-extracted terms as untrusted until validated.
- Test S3, Snowflake and Cortex integration in a non-production environment before deployment.
