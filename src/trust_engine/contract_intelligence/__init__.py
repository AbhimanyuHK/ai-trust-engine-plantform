"""Contract PDF ingestion, versioned artifacts, Cortex retrieval and grounded Q&A."""
from .ingestion import (
    DocumentChunk,
    chunk_pages,
    extract_pdf,
    ingest_pdf,
    local_document,
    normalize_text,
    parse_s3_uri,
    persist_chunks,
    record_ingestion_status,
    register_document,
    retry_ingest_pdf,
    sha256_file,
    write_artifacts,
)
from .cortex import complete, grounded_contract_answer, search_contracts
from .terms import (
    ContractTermCandidate,
    extract_contract_terms,
    persist_term_candidates,
    validate_amendment_precedence,
)

__all__ = [
    "DocumentChunk", "chunk_pages", "extract_pdf", "ingest_pdf", "local_document",
    "normalize_text", "parse_s3_uri", "persist_chunks", "record_ingestion_status", "register_document", "retry_ingest_pdf", "sha256_file", "write_artifacts",
    "complete", "grounded_contract_answer", "search_contracts",
    "ContractTermCandidate", "extract_contract_terms", "persist_term_candidates",
    "validate_amendment_precedence",
]
