"""Contract PDF ingestion, Cortex retrieval and grounded Q&A."""
from .ingestion import DocumentChunk, chunk_pages, extract_pdf, normalize_text, persist_chunks
from .cortex import complete, grounded_contract_answer, search_contracts
__all__ = ["DocumentChunk","chunk_pages","extract_pdf","normalize_text","persist_chunks",
           "complete","grounded_contract_answer","search_contracts"]
