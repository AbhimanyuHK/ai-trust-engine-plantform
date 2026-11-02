"""Version-aware contract PDF extraction, chunking and Snowflake persistence.

Original PDFs remain in object storage (for example S3). This module only downloads
them to an OS temporary file when parsing is required; it does not create a permanent
S3 processing directory.
"""
from __future__ import annotations

import hashlib
import json
import re
import tempfile
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator
from urllib.parse import urlparse

from pypdf import PdfReader

from trust_engine.common.infrastructure.db import connection


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
    document_id: str | None = None
    document_version: int = 1
    contract_version: int = 1
    document_type: str = "ORIGINAL"
    source_uri: str | None = None
    content_hash: str | None = None
    clause_number: str | None = None
    page_end: int | None = None
    parser_version: str = "pypdf-v1"
    chunking_version: str = "page-window-v2"


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def normalize_text(text: str) -> str:
    text = text.replace("\x00", " ")
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def parse_s3_uri(uri: str) -> tuple[str, str]:
    parsed = urlparse(uri)
    if parsed.scheme != "s3" or not parsed.netloc or not parsed.path.lstrip("/"):
        raise ValueError("Expected an S3 URI in the form s3://bucket/key")
    return parsed.netloc, parsed.path.lstrip("/")


@contextmanager
def local_document(source: str | Path, *, s3_client: Any | None = None) -> Iterator[Path]:
    """Yield a local path for a local file or an S3 object; S3 downloads are temporary."""
    value = str(source)
    if value.startswith("s3://"):
        if s3_client is None:
            try:
                import boto3
            except ImportError as exc:
                raise RuntimeError("Reading s3:// documents requires the optional 'aws' extra (boto3).") from exc
            s3_client = boto3.client("s3")
        bucket, key = parse_s3_uri(value)
        suffix = Path(key).suffix or ".pdf"
        with tempfile.TemporaryDirectory(prefix="trust-contract-") as temp_dir:
            target = Path(temp_dir) / f"source{suffix}"
            s3_client.download_file(bucket, key, str(target))
            yield target
    else:
        path = Path(source)
        if not path.is_file():
            raise FileNotFoundError(path)
        yield path


def extract_pdf(path: str | Path, ocr_fallback: bool = True) -> list[dict[str, object]]:
    """Extract page text; OCR is attempted only for pages with no extractable text."""
    reader = PdfReader(str(path))
    pages: list[dict[str, object]] = []
    for page_number, page in enumerate(reader.pages, start=1):
        text = normalize_text(page.extract_text() or "")
        if not text and ocr_fallback:
            try:
                from pdf2image import convert_from_path
                import pytesseract
            except ImportError:
                pass
            else:
                try:
                    image = convert_from_path(
                        str(path), first_page=page_number, last_page=page_number, dpi=220
                    )[0]
                    text = normalize_text(pytesseract.image_to_string(image))
                except Exception as exc:
                    raise RuntimeError(
                        "OCR fallback failed; install the OCR extra, Tesseract and Poppler."
                    ) from exc
        pages.append({"page_number": page_number, "text": text})
    return pages


_SECTION_RE = re.compile(
    r"(?im)^\s*((?:section\s+)?\d+(?:\.\d+)*\.?\s+.{2,100})\s*$"
)
_CLAUSE_RE = re.compile(r"(?im)^\s*((?:\d+\.){1,5}\d+)[.)]?\s+")


def _section_for(text: str) -> str | None:
    match = _SECTION_RE.search(text)
    return match.group(1).strip() if match else None


def _clause_for(text: str) -> str | None:
    match = _CLAUSE_RE.search(text)
    return match.group(1).rstrip(".") if match else None


def chunk_pages(
    pages: Iterable[dict[str, object]],
    contract_id: str,
    document_name: str,
    partner_id: str | None = None,
    effective_date: str | None = None,
    expiry_date: str | None = None,
    chunk_size: int = 450,
    overlap: int = 60,
    *,
    document_id: str | None = None,
    document_version: int = 1,
    contract_version: int = 1,
    document_type: str = "ORIGINAL",
    source_uri: str | None = None,
    content_hash: str | None = None,
) -> list[DocumentChunk]:
    """Create page-aware, overlapping chunks.

    chunk_size/overlap are whitespace-token (word) counts, not model-token counts.
    Keep the initial size conservative and evaluate Cortex Search retrieval quality.
    """
    if chunk_size <= 0 or overlap < 0 or overlap >= chunk_size:
        raise ValueError("Require chunk_size > overlap >= 0")
    if document_version < 1 or contract_version < 1:
        raise ValueError("document_version and contract_version must be >= 1")

    document_id = document_id or hashlib.sha256(
        f"{contract_id}|{document_name}|{content_hash or ''}".encode()
    ).hexdigest()[:32]
    chunks: list[DocumentChunk] = []
    index = 0
    step = chunk_size - overlap

    for page in pages:
        page_number = int(page["page_number"])
        page_text = normalize_text(str(page["text"]))
        words = page_text.split()
        if not words:
            continue
        for start in range(0, len(words), step):
            body = " ".join(words[start : start + chunk_size]).strip()
            if not body:
                continue
            digest = hashlib.sha256(
                f"{document_id}|{document_version}|{page_number}|{index}|{body}".encode()
            ).hexdigest()
            chunks.append(
                DocumentChunk(
                    chunk_id=digest,
                    contract_id=contract_id,
                    document_name=document_name,
                    chunk_text=body,
                    chunk_index=index,
                    page_number=page_number,
                    section=_section_for(body),
                    partner_id=partner_id,
                    effective_date=effective_date,
                    expiry_date=expiry_date,
                    document_id=document_id,
                    document_version=document_version,
                    contract_version=contract_version,
                    document_type=document_type.upper(),
                    source_uri=source_uri,
                    content_hash=content_hash,
                    clause_number=_clause_for(body),
                    page_end=page_number,
                )
            )
            index += 1
            if start + chunk_size >= len(words):
                break
    return chunks


def write_artifacts(
    *,
    s3_client: Any,
    bucket: str,
    partner_id: str,
    contract_id: str,
    document_version: int,
    pages: list[dict[str, object]],
    chunks: list[DocumentChunk],
    manifest: dict[str, Any],
) -> dict[str, str]:
    """Persist durable, versioned artifacts; no per-run processing prefix is created."""
    if not partner_id or not contract_id or document_version < 1:
        raise ValueError("partner_id, contract_id and positive document_version are required")
    content_hash = str(manifest.get("content_hash") or "unknown")
    parser_version = str(manifest.get("parser_version") or "unknown")
    chunking_version = str(manifest.get("chunking_version") or "unknown")
    prefix = (
        f"contracts/{partner_id}/{contract_id}/"
        f"document-versions/v{document_version:04d}/"
        f"derived/{content_hash}/{parser_version}/{chunking_version}"
    )
    artifacts = {
        "extracted": (f"{prefix}/extracted/extracted.json", json.dumps(pages, ensure_ascii=False)),
        "chunks": (
            f"{prefix}/chunks/chunks.jsonl",
            "\n".join(json.dumps(asdict(chunk), ensure_ascii=False) for chunk in chunks) + "\n",
        ),
        "manifest": (
            f"{prefix}/manifests/manifest.json",
            json.dumps(manifest, indent=2, ensure_ascii=False),
        ),
    }
    for key, body in artifacts.values():
        s3_client.put_object(
            Bucket=bucket,
            Key=key,
            Body=body.encode("utf-8"),
            ContentType="application/json" if key.endswith(".json") else "application/x-ndjson",
        )
    return {name: f"s3://{bucket}/{key}" for name, (key, _) in artifacts.items()}


def register_document(
    *,
    document_id: str,
    contract_id: str,
    document_name: str,
    source_uri: str,
    content_hash: str,
    partner_id: str | None = None,
    document_type: str = "ORIGINAL",
    document_version: int = 1,
    contract_version: int = 1,
    parent_document_id: str | None = None,
    effective_date: str | None = None,
    expiry_date: str | None = None,
    parser_version: str = "pypdf-v1",
    chunking_version: str = "page-window-v2",
) -> None:
    """Register an immutable source document; reject ID reuse with different bytes."""
    if not document_id or not contract_id or not document_name or not source_uri:
        raise ValueError("document_id, contract_id, document_name and source_uri are required")
    if document_version < 1 or contract_version < 1:
        raise ValueError("document_version and contract_version must be >= 1")
    if not re.fullmatch(r"[a-fA-F0-9]{64}", content_hash):
        raise ValueError("content_hash must be a SHA-256 hex digest")

    sql = """
    MERGE INTO AI.DOCUMENTS T
    USING (
      SELECT %s::VARCHAR DOCUMENT_ID, %s::VARCHAR CONTRACT_ID,
             %s::VARCHAR PARTNER_ID, %s::VARCHAR DOCUMENT_NAME,
             %s::VARCHAR DOCUMENT_TYPE, %s::NUMBER DOCUMENT_VERSION,
             %s::NUMBER CONTRACT_VERSION, %s::VARCHAR PARENT_DOCUMENT_ID,
             %s::VARCHAR SOURCE_URI, %s::VARCHAR CONTENT_HASH,
             %s::DATE EFFECTIVE_DATE, %s::DATE EXPIRY_DATE,
             %s::VARCHAR PARSER_VERSION, %s::VARCHAR CHUNKING_VERSION
    ) S
    ON T.DOCUMENT_ID = S.DOCUMENT_ID
    WHEN MATCHED AND T.CONTENT_HASH = S.CONTENT_HASH THEN UPDATE SET
      T.UPDATED_AT = CURRENT_TIMESTAMP()
    WHEN NOT MATCHED THEN INSERT (
      DOCUMENT_ID, CONTRACT_ID, PARTNER_ID, DOCUMENT_NAME, DOCUMENT_TYPE,
      DOCUMENT_VERSION, CONTRACT_VERSION, PARENT_DOCUMENT_ID, SOURCE_URI,
      CONTENT_HASH, EFFECTIVE_DATE, EXPIRY_DATE, INGESTION_STATUS,
      PARSER_VERSION, CHUNKING_VERSION
    ) VALUES (
      S.DOCUMENT_ID, S.CONTRACT_ID, S.PARTNER_ID, S.DOCUMENT_NAME, S.DOCUMENT_TYPE,
      S.DOCUMENT_VERSION, S.CONTRACT_VERSION, S.PARENT_DOCUMENT_ID, S.SOURCE_URI,
      S.CONTENT_HASH, S.EFFECTIVE_DATE, S.EXPIRY_DATE, 'PROCESSING',
      S.PARSER_VERSION, S.CHUNKING_VERSION
    )
    """
    params = (
        document_id, contract_id, partner_id, document_name, document_type.upper(),
        document_version, contract_version, parent_document_id, source_uri,
        content_hash, effective_date, expiry_date, parser_version, chunking_version,
    )
    with connection() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        cur.execute(
            "SELECT CONTENT_HASH FROM AI.DOCUMENTS WHERE DOCUMENT_ID = %s",
            (document_id,),
        )
        row = cur.fetchone()
        if not row:
            raise RuntimeError(f"Document registration did not create or find {document_id}")
        stored_hash = row[0] if not isinstance(row, dict) else row.get("CONTENT_HASH") or row.get("content_hash")
        if stored_hash != content_hash:
            raise ValueError(
                "DOCUMENT_ID already exists with different content; register the changed "
                "source as a new document ID/version"
            )


def record_ingestion_status(
    *,
    run_id: str,
    document_id: str,
    stage: str,
    status: str,
    attempt: int = 1,
    error_message: str | None = None,
) -> None:
    """Upsert the latest status for one document stage in an ingestion run."""
    allowed = {"PENDING", "RUNNING", "SUCCEEDED", "FAILED", "RETRYING", "CANCELLED"}
    normalized = status.upper()
    if normalized not in allowed:
        raise ValueError(f"Unsupported ingestion status: {status}")
    if attempt < 1:
        raise ValueError("attempt must be >= 1")
    sql = """
    MERGE INTO AI.DOCUMENT_INGESTION_STATUS T
    USING (
      SELECT %s::VARCHAR RUN_ID, %s::VARCHAR DOCUMENT_ID, %s::VARCHAR STAGE,
             %s::VARCHAR STATUS, %s::NUMBER ATTEMPT, %s::VARCHAR ERROR_MESSAGE
    ) S
    ON T.RUN_ID = S.RUN_ID AND T.DOCUMENT_ID = S.DOCUMENT_ID AND T.STAGE = S.STAGE
    WHEN MATCHED THEN UPDATE SET
      T.STATUS = S.STATUS, T.ATTEMPT = S.ATTEMPT, T.ERROR_MESSAGE = S.ERROR_MESSAGE,
      T.COMPLETED_AT = IFF(S.STATUS IN ('SUCCEEDED', 'FAILED', 'CANCELLED'),
                           CURRENT_TIMESTAMP(), NULL),
      T.UPDATED_AT = CURRENT_TIMESTAMP()
    WHEN NOT MATCHED THEN INSERT (
      RUN_ID, DOCUMENT_ID, STAGE, STATUS, ATTEMPT, ERROR_MESSAGE,
      STARTED_AT, COMPLETED_AT, UPDATED_AT
    ) VALUES (
      S.RUN_ID, S.DOCUMENT_ID, S.STAGE, S.STATUS, S.ATTEMPT, S.ERROR_MESSAGE,
      CURRENT_TIMESTAMP(),
      IFF(S.STATUS IN ('SUCCEEDED', 'FAILED', 'CANCELLED'), CURRENT_TIMESTAMP(), NULL),
      CURRENT_TIMESTAMP()
    )
    """
    with connection() as conn, conn.cursor() as cur:
        cur.execute(sql, (run_id, document_id, stage, normalized, attempt, error_message))


def _set_document_ingestion_status(document_id: str, status: str) -> None:
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            """UPDATE AI.DOCUMENTS
               SET INGESTION_STATUS = %s, UPDATED_AT = CURRENT_TIMESTAMP()
               WHERE DOCUMENT_ID = %s""",
            (status.upper(), document_id),
        )


def persist_chunks(chunks: list[DocumentChunk]) -> int:
    """Idempotently merge chunks; apply the canonical contract-intelligence DDL first."""
    if not chunks:
        return 0
    values = [
        (
            c.chunk_id, c.contract_id, c.document_name, c.chunk_text, c.chunk_index,
            c.page_number, c.section, c.partner_id, c.effective_date, c.expiry_date,
            c.document_id, c.document_version, c.contract_version, c.document_type,
            c.source_uri, c.content_hash, c.clause_number, c.page_end,
            c.parser_version, c.chunking_version,
        )
        for c in chunks
    ]
    sql = """
    MERGE INTO AI.DOCUMENT_CHUNKS T
    USING (
      SELECT %s CHUNK_ID, %s CONTRACT_ID, %s DOCUMENT_NAME, %s CHUNK_TEXT,
             %s CHUNK_INDEX, %s PAGE_NUMBER, %s SECTION, %s PARTNER_ID,
             %s EFFECTIVE_DATE, %s EXPIRY_DATE, %s DOCUMENT_ID,
             %s DOCUMENT_VERSION, %s CONTRACT_VERSION, %s DOCUMENT_TYPE,
             %s SOURCE_URI, %s CONTENT_HASH, %s CLAUSE_NUMBER, %s PAGE_END,
             %s PARSER_VERSION, %s CHUNKING_VERSION
    ) S
    ON T.CHUNK_ID = S.CHUNK_ID
    WHEN MATCHED THEN UPDATE SET
      T.CHUNK_TEXT = S.CHUNK_TEXT, T.SECTION = S.SECTION,
      T.CLAUSE_NUMBER = S.CLAUSE_NUMBER, T.PAGE_END = S.PAGE_END
    WHEN NOT MATCHED THEN INSERT (
      CHUNK_ID, CONTRACT_ID, DOCUMENT_NAME, CHUNK_TEXT, CHUNK_INDEX,
      PAGE_NUMBER, SECTION, PARTNER_ID, EFFECTIVE_DATE, EXPIRY_DATE,
      DOCUMENT_ID, DOCUMENT_VERSION, CONTRACT_VERSION, DOCUMENT_TYPE,
      SOURCE_URI, CONTENT_HASH, CLAUSE_NUMBER, PAGE_END, PARSER_VERSION,
      CHUNKING_VERSION
    ) VALUES (
      S.CHUNK_ID, S.CONTRACT_ID, S.DOCUMENT_NAME, S.CHUNK_TEXT, S.CHUNK_INDEX,
      S.PAGE_NUMBER, S.SECTION, S.PARTNER_ID, S.EFFECTIVE_DATE, S.EXPIRY_DATE,
      S.DOCUMENT_ID, S.DOCUMENT_VERSION, S.CONTRACT_VERSION, S.DOCUMENT_TYPE,
      S.SOURCE_URI, S.CONTENT_HASH, S.CLAUSE_NUMBER, S.PAGE_END,
      S.PARSER_VERSION, S.CHUNKING_VERSION
    )
    """
    with connection() as conn, conn.cursor() as cur:
        cur.executemany(sql, values)
        return int(cur.rowcount or len(values))


def ingest_pdf(
    source: str | Path,
    *,
    contract_id: str,
    document_name: str | None = None,
    partner_id: str | None = None,
    document_id: str | None = None,
    document_version: int = 1,
    contract_version: int = 1,
    document_type: str = "ORIGINAL",
    parent_document_id: str | None = None,
    effective_date: str | None = None,
    expiry_date: str | None = None,
    chunk_size: int = 450,
    overlap: int = 60,
    s3_client: Any | None = None,
    persist_to_snowflake: bool = True,
    artifact_bucket: str | None = None,
    artifact_s3_client: Any | None = None,
    run_id: str | None = None,
    attempt: int = 1,
) -> list[DocumentChunk]:
    """Ingest a PDF and track document registration and every durable processing stage.

    Snowflake lifecycle tracking is enabled with persist_to_snowflake. A caller may
    supply run_id to correlate retries; otherwise a unique run ID is generated.
    """
    if attempt < 1:
        raise ValueError("attempt must be >= 1")
    source_uri = str(source)
    name = document_name or Path(urlparse(source_uri).path).name or Path(source_uri).name
    execution_id = run_id or str(uuid.uuid4())
    current_stage = "SOURCE_READ"
    registered = False

    with local_document(source, s3_client=s3_client) as local_path:
        content_hash = sha256_file(local_path)
        resolved_document_id = document_id or hashlib.sha256(
            f"{contract_id}|{name}|{content_hash}".encode()
        ).hexdigest()[:32]

        if persist_to_snowflake:
            register_document(
                document_id=resolved_document_id,
                contract_id=contract_id,
                document_name=name,
                source_uri=source_uri,
                content_hash=content_hash,
                partner_id=partner_id,
                document_type=document_type,
                document_version=document_version,
                contract_version=contract_version,
                parent_document_id=parent_document_id,
                effective_date=effective_date,
                expiry_date=expiry_date,
            )
            registered = True
            record_ingestion_status(
                run_id=execution_id, document_id=resolved_document_id,
                stage="DOCUMENT_REGISTRATION", status="SUCCEEDED", attempt=attempt,
            )

        try:
            current_stage = "PDF_EXTRACTION"
            if persist_to_snowflake:
                record_ingestion_status(
                    run_id=execution_id, document_id=resolved_document_id,
                    stage=current_stage, status="RUNNING", attempt=attempt,
                )
            pages = extract_pdf(local_path)
            chunks = chunk_pages(
                pages, contract_id, name, partner_id, effective_date, expiry_date,
                chunk_size, overlap, document_id=resolved_document_id,
                document_version=document_version, contract_version=contract_version,
                document_type=document_type, source_uri=source_uri, content_hash=content_hash,
            )
            if persist_to_snowflake:
                record_ingestion_status(
                    run_id=execution_id, document_id=resolved_document_id,
                    stage=current_stage, status="SUCCEEDED", attempt=attempt,
                )

            if persist_to_snowflake:
                current_stage = "CHUNK_PERSISTENCE"
                record_ingestion_status(
                    run_id=execution_id, document_id=resolved_document_id,
                    stage=current_stage, status="RUNNING", attempt=attempt,
                )
                persist_chunks(chunks)
                record_ingestion_status(
                    run_id=execution_id, document_id=resolved_document_id,
                    stage=current_stage, status="SUCCEEDED", attempt=attempt,
                )

            if artifact_bucket:
                current_stage = "ARTIFACT_PERSISTENCE"
                if not partner_id:
                    raise ValueError("partner_id is required to persist versioned S3 artifacts")
                if persist_to_snowflake:
                    record_ingestion_status(
                        run_id=execution_id, document_id=resolved_document_id,
                        stage=current_stage, status="RUNNING", attempt=attempt,
                    )
                client = artifact_s3_client
                if client is None:
                    try:
                        import boto3
                    except ImportError as exc:
                        raise RuntimeError(
                            "Writing S3 artifacts requires the optional 'aws' extra (boto3)."
                        ) from exc
                    client = boto3.client("s3")
                manifest = {
                    "run_id": execution_id,
                    "contract_id": contract_id,
                    "partner_id": partner_id,
                    "document_id": resolved_document_id,
                    "document_version": document_version,
                    "contract_version": contract_version,
                    "document_type": document_type.upper(),
                    "source_uri": source_uri,
                    "content_hash": content_hash,
                    "effective_from": effective_date,
                    "effective_to": expiry_date,
                    "parser_version": "pypdf-v1",
                    "chunking_version": "page-window-v2",
                    "chunk_count": len(chunks),
                }
                write_artifacts(
                    s3_client=client, bucket=artifact_bucket, partner_id=partner_id,
                    contract_id=contract_id, document_version=document_version,
                    pages=pages, chunks=chunks, manifest=manifest,
                )
                if persist_to_snowflake:
                    record_ingestion_status(
                        run_id=execution_id, document_id=resolved_document_id,
                        stage=current_stage, status="SUCCEEDED", attempt=attempt,
                    )

            if persist_to_snowflake:
                _set_document_ingestion_status(resolved_document_id, "SUCCEEDED")
            return chunks
        except Exception as exc:
            if persist_to_snowflake and registered:
                try:
                    record_ingestion_status(
                        run_id=execution_id, document_id=resolved_document_id,
                        stage=current_stage, status="FAILED", attempt=attempt,
                        error_message=str(exc)[:16000],
                    )
                    _set_document_ingestion_status(resolved_document_id, "FAILED")
                except Exception:
                    # Preserve the original processing exception; operational logs
                    # should capture any secondary status-write failure.
                    pass
            raise
