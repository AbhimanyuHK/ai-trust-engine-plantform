# Application Implementation

The Python application layer is under `src/trust_engine`; Snowflake objects are under `snowflake/`. Business capabilities are separated into Contract Intelligence, Forecasting and Workflows.

## Domain packages

- `contract_intelligence/`: PDF extraction/OCR, normalization, page-aware chunking, Snowflake persistence, Cortex Search and grounded Q&A.
- `forecasting/`: daily revenue features, chronological validation, XGBoost and optional TensorFlow LSTM.
- `workflows/`: LangGraph orchestration, human interrupt and reviewer resume.

## Application — `application/`

- `api.py`: FastAPI endpoints for contract questions, analytics, approvals and workflows.
- `cli.py`: configuration validation, PDF ingestion, forecasting and approval operations.
- `streamlit_app.py`: interactive contract, analytics/chart and approval review screens.
- `services/analytics.py`: Cortex SQL generation, read-only validation and semantic object allowlist.
- `services/governance.py`: deterministic approval thresholds, reviewer-role checks and transactional decision/audit writes.

## Common — `common/`

- `config/settings.py`: environment/YAML configuration and Snowflake settings.
- `infrastructure/db.py`: shared Snowflake DB-API connection, query and execute helpers.

## Setup

```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# macOS/Linux: source .venv/bin/activate
pip install -e ".[dev,agent,ui]"
pip install -e ".[lstm]"  # optional TensorFlow model
pip install -e ".[ocr]"   # optional scanned-PDF OCR dependencies
copy .env.example .env
```

Set Snowflake account, user, authentication and role values in `.env`. Never commit credentials.

## Snowflake deployment order

1. `snowflake/database/databases.sql`
2. `snowflake/database/schemas.sql`
3. `snowflake/stages/*.sql`
4. `snowflake/tables/*.sql`
5. `snowflake/migrations/*.sql`
6. `snowflake/procedures/*.sql`
7. `snowflake/cortex/*.sql`
8. `snowflake/tasks/*.sql`

Deploy all table DDL before running the API or CLI against Snowflake.

## CLI and API

```bash
trust-engine validate-config
trust-engine ingest-contract ./contract.pdf --contract-id CONTRACT_101 --partner-id CONTRACTOR_101
trust-engine forecast --horizon-days 60
uvicorn trust_engine.application.api:app --host 127.0.0.1 --port 8000
streamlit run src/trust_engine/application/streamlit_app.py
```

REST endpoints include `GET /health`, contract Q&A, governed analytics, approval create/read/decision and resumable contract workflow start/resume.

## Production boundaries

- Cortex Search owns retrieval; no external vector database is used.
- Transaction amounts must be normalized to signed values upstream.
- Royalty is calculated only with an authoritative decimal rate.
- SQLite checkpoints are local-development only; production multi-instance use requires a shared durable checkpointer and authenticated reviewer identity.
- OCR requires the optional Python extra plus system Tesseract and Poppler.
- Contract activation requires verified signature/acceptance and effective-date controls.
- Run unit tests and validate Snowflake DDL/API calls in a non-production account before deployment.
