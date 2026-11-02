# Workflows

Owns cross-domain orchestration, not underlying business capabilities. Coordinates Contract Intelligence retrieval, requests structured transaction/forecast context, generates recommendations, pauses at a LangGraph human approval interrupt, and resumes the same thread from a durable checkpoint.

Workflows call Contract Intelligence and Forecasting through public interfaces. They do not parse PDFs, create embeddings, train forecasting models, or duplicate approval/audit storage.
