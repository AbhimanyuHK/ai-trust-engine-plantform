# Snowflake Deployment

This directory contains the Snowflake objects required by the AI TRUST Engine.

## Design goals

- Snowflake is the system of record for structured transactions and contract data.
- Snowflake stages hold incoming contract documents.
- SQL handles deterministic ingestion, transformations, validation, and serving tables.
- Snowpark Python can be used for complex data/document processing and ML workloads.
- Snowflake Cortex provides embeddings, Cortex Search, and LLM inference.
- LangGraph remains the external Python orchestration layer when stateful agent workflows are enabled.
- Streamlit can provide the HITL and analytics UI.

## Directory layout

```text
snowflake/
├── README.md
├── 00_setup.sql
├── 01_file_formats.sql
├── 02_stages.sql
├── 03_raw_tables.sql
├── 04_core_tables.sql
├── 05_ai_tables.sql
├── 06_forecast_tables.sql
├── 07_governance_tables.sql
├── 08_metadata_tables.sql
├── 09_validation_views.sql
├── 10_cortex_search.sql
├── 11_tasks.sql
└── 12_seed_data.sql
```

## Data flow

```text
Retail / Wholesale
        |
        v
      RAW
        |
        v
   CORE.TRANSACTIONS
        |
   +----+----------------+
   |                     |
   v                     v
Forecasting          Analytics

Contract PDF
    |
    v
CONTRACT_STAGE
    |
    v
Document processing / Snowpark
    |
    v
AI.DOCUMENTS
    |
    v
AI.DOCUMENT_CHUNKS
    |
    v
Cortex embeddings / Cortex Search
    |
    v
LangGraph + Cortex LLM
    |
    v
Recommendation -> HITL -> Audit
```

## Execution order

Run scripts in numeric order after replacing environment placeholders such as `${TRUST_DB}` and `${TRUST_WH}` with your own Snowflake objects.

For the free-trial POC, use a small warehouse and avoid creating unnecessary compute. Start with one database and one warehouse, then scale only when the workload requires it.

## Important Cortex note

`10_cortex_search.sql` contains a **deployment template** for Cortex Search. Cortex features and SQL syntax can evolve; verify the exact syntax and supported embedding/model options in the Snowflake account before production deployment. Model names are intentionally parameterized rather than hard-coded as a permanent guarantee.

The scripts do not require Pinecone or another external vector database. Document chunks and AI metadata remain in Snowflake.

## What is configuration vs execution?

The YAML under `config/` defines source/target mappings, validation rules, chunking parameters, AI settings, workflow settings, and environment values. These SQL files create and operate Snowflake objects. YAML itself does not execute SQL, OCR, embeddings, or LLM calls.

## Production separation

```text
DEV -> QA -> UAT -> PROD
```

Use separate environment configuration and Snowflake databases/schemas or equivalent controlled namespaces. Never commit credentials, passwords, private keys, or access tokens to this repository.
