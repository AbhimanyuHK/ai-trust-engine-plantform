"""Contract PDF extraction, section-aware chunking and Snowflake persistence."""
from __future__ import annotations
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from pypdf import PdfReader
from trust_engine.db import connection

@dataclass(frozen=True)
class DocumentChunk:
    chunk_id: str
    contract_id: str
    document_name: str
    chunk_text: str
    chunk_index: int
    page_number: int
    section: str | None = None
    partner_id: str | None = None
    effective_date: str | None = None
    expiry_date: str | None = None

def normalize_text(text: str) -> str:
    text = text.replace("\x00", " ")
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()

def extract_pdf(path: str | Path, ocr_fallback: bool = True) -> list[dict[str, object]]:
    """Extract page text and optionally OCR scanned pages when OCR extras are installed."""
    reader = PdfReader(str(path))
    pages: list[dict[str, object]] = []
    for page_number, page in enumerate(reader.pages, start=1):
        text = normalize_text(page.extract_text() or "")
        if not text and ocr_fallback:
            try:
                from pdf2image import convert_from_path
                import pytesseract
            except ImportError:
                # Keep an empty page; callers must not mistake it for successful extraction.
                pass
            else:
                try:
                    image = convert_from_path(str(path), first_page=page_number,
                                              last_page=page_number, dpi=220)[0]
                    text = normalize_text(pytesseract.image_to_string(image))
                except Exception as exc:
                    raise RuntimeError(
                        "OCR fallback failed; install Tesseract and Poppler and verify PATH."
                    ) from exc
        pages.append({"page_number": page_number, "text": text})
    return pages

def _section_for(text: str) -> str | None:
    match = re.search(r"(?im)^\s*((?:section\s+)?\d+(?:\.\d+)*\.?\s+.{2,100})$", text)
    return match.group(1).strip() if match else None

def chunk_pages(pages: Iterable[dict[str, object]], contract_id: str, document_name: str,
                partner_id: str | None = None, effective_date: str | None = None,
                expiry_date: str | None = None, chunk_size: int = 800,
                overlap: int = 100) -> list[DocumentChunk]:
    """Chunk by words while preserving page and best-effort section metadata."""
    if chunk_size <= 0 or overlap < 0 or overlap >= chunk_size:
        raise ValueError("Require chunk_size > overlap >= 0")
    chunks: list[DocumentChunk] = []
    index, step = 0, chunk_size - overlap
    for page in pages:
        page_number = int(page["page_number"])
        words = normalize_text(str(page["text"])).split()
        for start in range(0, len(words), step):
            body = " ".join(words[start:start + chunk_size]).strip()
            if not body:
                continue
            digest = hashlib.sha256(
                f"{contract_id}|{document_name}|{page_number}|{index}|{body}".encode()
            ).hexdigest()[:32]
            chunks.append(DocumentChunk(digest, contract_id, document_name, body, index,
                page_number, _section_for(body), partner_id, effective_date, expiry_date))
            index += 1
            if start + chunk_size >= len(words):
                break
    return chunks

def persist_chunks(chunks: list[DocumentChunk]) -> int:
    """Idempotently merge document chunks by stable chunk identifier."""
    if not chunks:
        return 0
    values = [(c.chunk_id,c.contract_id,c.document_name,c.chunk_text,c.chunk_index,c.page_number,
               c.section,c.partner_id,c.effective_date,c.expiry_date) for c in chunks]
    sql = """MERGE INTO AI.DOCUMENT_CHUNKS T USING
      (SELECT %s CHUNK_ID,%s CONTRACT_ID,%s DOCUMENT_NAME,%s CHUNK_TEXT,%s CHUNK_INDEX,
       %s PAGE_NUMBER,%s SECTION,%s PARTNER_ID,%s EFFECTIVE_DATE,%s EXPIRY_DATE) S
      ON T.CHUNK_ID=S.CHUNK_ID
      WHEN MATCHED THEN UPDATE SET T.CHUNK_TEXT=S.CHUNK_TEXT,T.SECTION=S.SECTION
      WHEN NOT MATCHED THEN INSERT
      (CHUNK_ID,CONTRACT_ID,DOCUMENT_NAME,CHUNK_TEXT,CHUNK_INDEX,PAGE_NUMBER,SECTION,
       PARTNER_ID,EFFECTIVE_DATE,EXPIRY_DATE)
      VALUES (S.CHUNK_ID,S.CONTRACT_ID,S.DOCUMENT_NAME,S.CHUNK_TEXT,S.CHUNK_INDEX,
       S.PAGE_NUMBER,S.SECTION,S.PARTNER_ID,S.EFFECTIVE_DATE,S.EXPIRY_DATE)"""
    import snowflake.connector
    with connection() as conn, conn.cursor() as cur:
        cur.executemany(sql, values)
        return int(cur.rowcount or len(values))
