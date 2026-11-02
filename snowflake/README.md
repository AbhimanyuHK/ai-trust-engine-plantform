# Snowflake Deployment

Snowflake is the system of record for structured transactions, contracts, chunks, forecasts, recommendations and approval audit state.

## Deployment order

1. `database/databases.sql`
2. `database/schemas.sql`
3. `stages/*.sql`
4. `tables/*.sql` (includes governance approvals and recommendations)
5. `procedures/*.sql`
6. `cortex/*.sql`
7. `tasks/*.sql`

Configure `TRUST_WH`, database/stage names and Snowflake roles for each environment before deployment. Do not commit credentials.

## Responsibilities

- `RAW`: landed retail and wholesale transaction data.
- `CORE`: canonical signed transaction values and contract metadata.
- `AI`: contract chunks, recommendations and AI run metadata.
- `FORECAST`: daily revenue forecast results.
- `GOVERNANCE`: approval requests and append-only decision audit events.
- `METADATA`: lineage and pipeline run metadata.

Cortex Search owns its managed retrieval index over `AI.DOCUMENT_CHUNKS`; the platform does not persist a second vector database. Verify supported Cortex models, service syntax, privileges and warehouse sizing in the target Snowflake account.

The Python application layer is under `src/trust_engine`. See [application setup](../docs/IMPLEMENTATION.md).
