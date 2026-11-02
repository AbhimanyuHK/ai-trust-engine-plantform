# Application Implementation

The repository contains a Python application layer under `src/trust_engine` and Snowflake deployment SQL under `snowflake/`.

## Implemented modules

| Module | Responsibility |
|---|---|
| `settings.py` | Environment settings and YAML configuration loading |
| `db.py` | Snowflake DB-API connection/query helpers |
| `documents.py` | PDF text extraction, page-aware chunking and idempotent chunk merge |
| `cortex.py` | Cortex Search Preview and Cortex Complete adapters; grounded answer assembly |
| `forecasting.py` | Daily revenue feature engineering, chronological validation, XGBoost forecasting and persistence |
| `governance.py` | Deterministic approval thresholds, role checks and persisted decision operations |
| `analytics.py` | Cortex SQL generation, read-only validation and semantic object allowlist |
| `workflows.py` | Optional LangGraph contract workflow and persistent checkpoint integration |
| `api.py` | FastAPI endpoints for contract questions, analytics and approvals |
| `cli.py` | CLI for configuration validation, document ingestion, forecasting and approval operations |

## Local setup

```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# macOS/Linux: source .venv/bin/activate
pip install -e ".[dev,agent]"
copy .env.example .env
```

Set Snowflake account/user and authentication values in `.env`. Do not commit credentials.

## Snowflake deployment

Run the SQL in this order:

1. `snowflake/database/databases.sql`
2. `snowflake/database/schemas.sql`
3. `snowflake/stages/*.sql`
4. `snowflake/tables/*.sql`
5. `snowflake/procedures/*.sql`
6. `snowflake/cortex/*.sql`
7. `snowflake/tasks/*.sql`

The new governance DDL creates durable approval request and audit tables. The app fails closed for unknown approval types and enforces the configured Finance/Partner Relations role at decision time.

## CLI examples

```bash
trust-engine validate-config
trust-engine ingest-contract ./contract.pdf --contract-id CONTRACT_101 --partner-id CONTRACTOR_101
trust-engine forecast --horizon-days 60
trust-engine approval-status APPROVAL_UUID
trust-engine decide APPROVAL_UUID APPROVED reviewer@example.com finance "Reviewed supporting clauses"
```

## API

Start the API with:

```bash
uvicorn trust_engine.api:app --host 127.0.0.1 --port 8000
```

- `GET /health`
- `POST /v1/contracts/ask`
- `POST /v1/analytics/ask`
- `POST /v1/approvals`
- `GET /v1/approvals/{approval_id}`
- `POST /v1/approvals/{approval_id}/decision`

## Operational boundaries and production hardening

- Cortex Search indexes the searchable text and metadata; the app does not maintain a second vector database.
- PDF text extraction preserves page numbers. Scanned PDFs need a separately configured OCR worker; the base extractor does not pretend to OCR images.
- Forecasting currently persists revenue forecasts. Royalty amounts are written only when an authoritative decimal royalty rate is explicitly supplied; no LLM-generated rate is accepted.
- Forecast evaluation uses a chronological holdout, not a random split. Backtesting across multiple rolling origins should be added before production SLAs are claimed.
- The approval tables are durable business state. LangGraph checkpoints are workflow execution state; they are separate concerns and must not replace approval/audit records.
- The default local LangGraph checkpointer is for development. Use a managed, shared checkpointer/database for multi-instance production deployment.
- Restrict API network access, configure Snowflake least-privilege roles, enforce reviewer identity through enterprise SSO, and add request authentication/rate limits before internet-facing deployment.
- Configure a Snowflake warehouse, Cortex model availability, search service grants and role permissions for the target account before running integrations.
