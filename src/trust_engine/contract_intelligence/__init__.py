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
    sha256_file,
    write_artifacts,
)
from .cortex import complete, grounded_contract_answer, search_contracts

__all__ = [
    "DocumentChunk", "chunk_pages", "extract_pdf", "ingest_pdf", "local_document",
    "normalize_text", "parse_s3_uri", "persist_chunks", "sha256_file", "write_artifacts",
    "complete", "grounded_contract_answer", "search_contracts",
]
