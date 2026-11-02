# Domain-Oriented Application Structure

```text
src/trust_engine/
├── contract_intelligence/
│   ├── ingestion.py                # PDF, OCR, extraction, chunking, Snowflake writes
│   ├── cortex.py                   # Cortex Search, AI_COMPLETE, grounded RAG
│   └── README.md
├── forecasting/
│   ├── xgboost_model.py            # features, train/evaluate, forecast persistence
│   ├── lstm_model.py               # optional sequence model
│   └── README.md
├── workflows/
│   ├── contract_recommendation.py  # LangGraph cross-domain orchestration
│   └── README.md
├── analytics.py                    # governed NL-to-SQL
├── governance.py                   # approval policy and audit persistence
├── api.py                          # API composition layer
├── cli.py                          # operational entry points
└── streamlit_app.py                # user interface
```

## Ownership

**Contract Intelligence owns PDFs.** It validates PDFs, extracts/OCRs text, preserves page/section metadata, chunks and stores text in Snowflake, retrieves clauses with Cortex Search, and generates grounded answers with citations. OCR is a document-processing component inside this domain, not a second LLM.

**Forecasting owns numeric prediction.** It consumes structured, source-normalized transaction history and owns feature engineering, model training, validation, prediction and forecast persistence. It does not parse PDFs or infer commercial terms.

**Workflows owns orchestration.** It invokes Contract Intelligence and Forecasting, combines sourced evidence, generates recommendations, pauses for human approval and resumes from a checkpoint. It does not reimplement document processing or model training.

The API, CLI and UI are adapters. Snowflake remains the governed source of truth; Cortex Search remains the retrieval service. No external vector database is introduced.
