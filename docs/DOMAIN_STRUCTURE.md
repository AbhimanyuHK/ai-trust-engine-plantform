# Domain-Oriented Application Structure

```text
src/trust_engine/
├── application/
│   ├── api.py                         # FastAPI composition and REST endpoints
│   ├── cli.py                         # operational CLI entry point
│   ├── streamlit_app.py               # business-user UI
│   └── services/
│       ├── analytics.py               # governed natural-language analytics
│       └── governance.py              # approval policy and audit operations
├── common/
│   ├── config/settings.py             # environment and YAML configuration
│   └── infrastructure/db.py           # shared Snowflake DB-API adapter
├── contract_intelligence/             # PDF/OCR, chunking, Cortex Search and grounded RAG
├── forecasting/                       # XGBoost and optional LSTM prediction
└── workflows/                         # LangGraph cross-domain orchestration and HITL
```

## Ownership

**Application** owns delivery adapters and application-level use cases. API, CLI and Streamlit compose domain capabilities; analytics and approval services coordinate user-facing operations.

**Common** owns only domain-agnostic concerns: configuration and shared database connectivity. Domain packages depend on these shared adapters, never on application entry points.

**Contract Intelligence owns PDFs.** It validates PDFs, extracts/OCRs text, preserves page/section metadata, chunks and stores text in Snowflake, retrieves clauses with Cortex Search, and generates grounded answers with citations. OCR is a document-processing component inside this domain, not a second LLM.

**Forecasting owns numeric prediction.** It consumes structured, source-normalized transaction history and owns feature engineering, model training, validation, prediction and forecast persistence.

**Workflows owns orchestration.** It invokes Contract Intelligence and Forecasting, combines sourced evidence, generates recommendations, pauses for human approval and resumes from a checkpoint.

Snowflake remains the governed source of truth; Cortex Search remains the retrieval service. No external vector database is introduced.
