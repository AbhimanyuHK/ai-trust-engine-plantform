from trust_engine.contract_intelligence.ingestion import (
    chunk_pages,
    normalize_text,
    parse_s3_uri,
)


def test_normalize_text_removes_extraction_noise():
    assert normalize_text("  hello\x00  world \n\n\n next ") == "hello world \n\n next"


def test_chunk_pages_preserves_page_metadata_overlap_and_version_lineage():
    pages = [{"page_number": 4, "text": " ".join(f"word{i}" for i in range(25))}]
    chunks = chunk_pages(
        pages,
        "C-1",
        "agreement.pdf",
        chunk_size=10,
        overlap=2,
        document_id="DOC-2",
        document_version=2,
        contract_version=2,
        document_type="AMENDMENT",
        source_uri="s3://contracts/C-1/v2.pdf",
        content_hash="abc123",
    )
    assert len(chunks) == 3
    assert all(chunk.page_number == 4 for chunk in chunks)
    assert chunks[0].chunk_text.split()[-2:] == chunks[1].chunk_text.split()[:2]
    assert all(chunk.document_id == "DOC-2" for chunk in chunks)
    assert all(chunk.document_version == 2 for chunk in chunks)
    assert all(chunk.contract_version == 2 for chunk in chunks)
    assert all(chunk.document_type == "AMENDMENT" for chunk in chunks)
    assert all(chunk.source_uri == "s3://contracts/C-1/v2.pdf" for chunk in chunks)
    assert all(chunk.content_hash == "abc123" for chunk in chunks)


def test_chunking_rejects_invalid_overlap():
    try:
        chunk_pages([], "C-1", "x.pdf", chunk_size=10, overlap=10)
    except ValueError:
        return
    raise AssertionError("invalid overlap should fail")


def test_parse_s3_uri():
    assert parse_s3_uri("s3://bucket/path/to/contract.pdf") == (
        "bucket",
        "path/to/contract.pdf",
    )


def test_parse_s3_uri_rejects_invalid_values():
    for value in ("https://bucket/key.pdf", "s3://bucket", "s3:///key.pdf"):
        try:
            parse_s3_uri(value)
        except ValueError:
            continue
        raise AssertionError(f"Expected invalid S3 URI to fail: {value}")
