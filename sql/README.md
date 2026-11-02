# Snowflake SQL

All Contract Intelligence SQL is organized by operation:

- `ddl/ai/`: schema objects and additive schema upgrades.
- `dml/ai/`: repeatable operational DML templates for document registration,
  ingestion-stage status, and effective-dated contract terms.

## Execution

1. New environment: run `ddl/ai/001_create_contract_intelligence_tables.sql`.
2. Existing older chunk table: run `ddl/ai/002_upgrade_document_chunks.sql`.
3. Review and parameterize the DML templates before running them. They contain
   placeholders and must not be executed unchanged.
4. Keep extracted terms in PENDING until an authorized reviewer approves them.
   Do not treat OCR/LLM extraction as an approval.
5. Validate that approved effective-date ranges do not overlap before enabling
   downstream royalty calculations.

Snowflake standard-table primary/unique constraints are informational; stable IDs,
MERGE idempotency and application-level validation are required.


## Workflow and Cortex Search deployment

After the base Contract Intelligence tables are present, run:

1. `ddl/ai/003_contract_intelligence_workflow.sql` for Snowflake workflow-run status and append-only events.
2. `ddl/ai/004_create_contract_search_service.sql` for managed embeddings and Cortex Search indexing over `AI.DOCUMENT_CHUNKS`.
3. `ddl/ai/005_contract_term_candidates.sql` for the PENDING extraction/review queue.

The Cortex Search script expects the `TRUST_WH` warehouse and a role with the required schema, table, warehouse, Cortex Search, and Cortex embedding privileges. It uses `snowflake-arctic-embed-l-v2.0` and a one-hour target lag. Index refresh is asynchronous; successful chunk persistence is not proof that new rows are already searchable.

The Cortex Search service creator also needs the `SNOWFLAKE.CORTEX_USER` or `SNOWFLAKE.CORTEX_EMBED_USER` database role in addition to schema/table/warehouse privileges. The workflow execution role needs `OPERATE` on the service to issue the manual refresh. Confirm the role grants in the target account before running the workflow.

Contract term extraction is exposed by `extract_contract_terms(document_id)`. It validates model-proposed evidence quotes against persisted source chunks and stores candidates as PENDING. `validate_amendment_precedence(document_id)` checks parent-document lineage, version ordering, explicit effective dates, and overlaps with approved terms. It is a review gate, not automatic legal approval. Deploy migration 005 before running extraction with persistence enabled.
