# Snowflake Deployment

This directory contains the Snowflake-native objects required by the AI TRUST Engine.

## Directory layout

```text
snowflake/
├── README.md
├── database/
│   ├── databases.sql
│   └── schemas.sql
├── stages/
│   ├── transaction_stage.sql
│   └── contract_stage.sql
├── tables/
│   ├── raw_transactions.sql
│   ├── transactions.sql
│   ├── contracts.sql
│   ├── document_chunks.sql
│   ├── forecasts.sql
│   └── ai_metadata.sql
├── cortex/
│   ├── search_service.sql
│   └── cortex_objects.sql
├── tasks/
│   ├── forecasting_task.sql
│   └── contract_processing_task.sql
└── procedures/
    └── processing_procedures.sql
```

## Responsibilities

- `database/` creates the TRUST database and schemas.
- `stages/` defines Snowflake stages for transaction files and contracts.
- `tables/` stores raw transactions, canonical transactions, contracts, document chunks, forecasts and AI metadata.
- `cortex/` contains Cortex Search and Cortex AI/embedding configuration.
- `tasks/` contains Snowflake-native schedules.
- `procedures/` contains reusable SQL processing logic.

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

## Deployment order

1. `database/databases.sql`
2. `database/schemas.sql`
3. `stages/*.sql`
4. `tables/*.sql`
5. `procedures/*.sql`
6. `cortex/*.sql`
7. `tasks/*.sql`

Replace environment-specific values such as `TRUST_WH` before deployment. Do not commit credentials or secrets.

## Free-trial POC

The core POC is Snowflake-first: Snowflake tables/stages, SQL/Snowpark processing, Cortex embeddings/search/LLM and Snowflake Tasks. LangGraph is an external Python orchestration layer and Streamlit can provide the UI. AWS services are optional rather than required for the core POC.

## Important notes

- The embedding vector dimension must match the selected Cortex embedding model.
- Review Cortex Search syntax and supported model names against the target Snowflake account before production deployment.
- Tasks are created suspended; resume them only after their dependent procedures/objects are deployed.
- YAML under `config/` defines configuration; these SQL files create and execute Snowflake-native objects.
- Use separate controlled configuration/namespaces for DEV, QA, UAT and PROD.
