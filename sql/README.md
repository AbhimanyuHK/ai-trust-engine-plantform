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

The Cortex Search script expects the `TRUST_WH` warehouse and a role with the required schema, table, warehouse, Cortex Search, and Cortex embedding privileges. It uses `snowflake-arctic-embed-l-v2.0` and a one-hour target lag. Index refresh is asynchronous; successful chunk persistence is not proof that new rows are already searchable.
