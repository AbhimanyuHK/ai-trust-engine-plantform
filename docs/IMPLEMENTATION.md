# Application Implementation

The Python application layer is under `src/trust_engine`; Snowflake objects are under `snowflake/`.

## Modules

- `settings.py` and `db.py`: environment/YAML configuration and Snowflake DB-API access.
- `documents.py`: page-aware PDF text extraction, overlapping chunking and idempotent chunk merge.
- `cortex.py`: Cortex Search Python SDK, AI_COMPLETE and grounded evidence assembly.
- `forecasting.py` and `lstm.py`: daily calendarized revenue features, chronological holdout, XGBoost and optional LSTM inference with forecast persistence.
- `governance.py`: deterministic approval thresholds, reviewer-role checks and transactional decision/audit writes.
- `workflows.py`: LangGraph contract workflow: Cortex Search evidence, partner transaction/forecast context, recommendation generation, persisted human interrupt and reviewer resume.
- `analytics.py`: Cortex SQL generation, read-only validation and semantic object allowlist.
- `api.py`: REST endpoints for contract questions, analytics and approvals.
- `streamlit_app.py`: interactive contract, analytics/chart and approval review screens.
- `cli.py`: configuration validation, PDF ingestion, forecasting and approval operations.

## Setup

```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# macOS/Linux: source .venv/bin/activate
pip install -e ".[dev,agent,ui]"
# Optional TensorFlow model: pip install -e ".[lstm]"
# Optional scanned-PDF OCR dependencies: pip install -e ".[ocr]"
copy .env.example .env
```

Set Snowflake account, user, authentication and role values in `.env`. Never commit credentials.

## Snowflake deployment order

1. `snowflake/database/databases.sql`
2. `snowflake/database/schemas.sql`
3. `snowflake/stages/*.sql`
4. `snowflake/tables/*.sql`
5. `snowflake/procedures/*.sql`
6. `snowflake/cortex/*.sql`
7. `snowflake/tasks/*.sql`

Deploy all table DDL before running the API or CLI against Snowflake.

## CLI and API

```bash
trust-engine validate-config
trust-engine ingest-contract ./contract.pdf --contract-id CONTRACT_101 --partner-id CONTRACTOR_101
trust-engine forecast --horizon-days 60
uvicorn trust_engine.api:app --host 127.0.0.1 --port 8000
# Or launch the interactive UI: streamlit run src/trust_engine/streamlit_app.py
```

REST endpoints: `GET /health`, `POST /v1/contracts/ask`, `POST /v1/analytics/ask`,
`POST /v1/approvals`, `GET /v1/approvals/{approval_id}`,
`POST /v1/approvals/{approval_id}/decision`, `POST /v1/workflows/contracts/{thread_id}/start` and `POST /v1/workflows/contracts/{thread_id}/resume`.

## Workflow boundaries

- Cortex Search manages its retrieval index; no external vector database is introduced.
- The PDF parser extracts page text and optionally falls back to Tesseract OCR when the `ocr` extra plus system Tesseract/Poppler are installed; otherwise scanned pages remain empty and must be routed for OCR.
- Forecasting currently predicts revenue (demand remains null until a reliable quantity target is configured). XGBoost is the default; LSTM is an optional sequence-model path. Royalty is calculated only when an authoritative decimal rate is supplied; the LLM never invents a rate.
- Transaction `AMOUNT` must be normalized to a signed financial value upstream. Forecasting does not guess whether returns, credits or adjustments are positive or negative.
- Forecast evaluation uses a chronological holdout, not random splitting. Add rolling-origin backtests and model registry promotion before claiming production SLAs.
- LangGraph checkpoints represent execution state; Snowflake approval and audit tables represent business decisions. They are separate records. A workflow pauses at the reviewer interrupt and resumes with the same thread ID; it does not keep a model process running while a human is away.
- SQLite checkpoints are for local development. Multi-instance production requires a shared durable checkpointer, authenticated reviewer identity, SSO/RBAC, API authentication, rate limits and network controls.
- Verify Cortex model availability, search service syntax, warehouse sizing and grants in the target Snowflake account before deployment.
