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



def test_ingestion_records_document_and_stage_lifecycle(monkeypatch, tmp_path):
    from contextlib import nullcontext
    import trust_engine.contract_intelligence.ingestion as ingestion

    source = tmp_path / "contract.pdf"
    source.write_bytes(b"pdf bytes")
    events = []
    monkeypatch.setattr(ingestion, "local_document", lambda *_args, **_kwargs: nullcontext(source))
    monkeypatch.setattr(ingestion, "sha256_file", lambda _path: "a" * 64)
    monkeypatch.setattr(ingestion, "extract_pdf", lambda _path: [{"page_number": 1, "text": "terms"}])
    monkeypatch.setattr(ingestion, "chunk_pages", lambda *args, **kwargs: [])
    monkeypatch.setattr(ingestion, "register_document", lambda **kwargs: events.append(("register", kwargs)))
    monkeypatch.setattr(
        ingestion, "record_ingestion_status",
        lambda **kwargs: events.append(("stage", kwargs["stage"], kwargs["status"])),
    )
    monkeypatch.setattr(ingestion, "persist_chunks", lambda _chunks: 0)
    monkeypatch.setattr(ingestion, "_set_document_ingestion_status",
                        lambda _document_id, status: events.append(("document", status)))

    result = ingestion.ingest_pdf(
        source, contract_id="C-1", partner_id="P-1", run_id="RUN-1"
    )

    assert result == []
    assert events[0][0] == "register"
    assert ("stage", "DOCUMENT_REGISTRATION", "SUCCEEDED") in events
    assert ("stage", "PDF_EXTRACTION", "RUNNING") in events
    assert ("stage", "PDF_EXTRACTION", "SUCCEEDED") in events
    assert ("stage", "CHUNK_PERSISTENCE", "RUNNING") in events
    assert ("stage", "CHUNK_PERSISTENCE", "SUCCEEDED") in events
    assert events[-1] == ("document", "SUCCEEDED")


def test_ingestion_marks_failed_stage_and_document(monkeypatch, tmp_path):
    from contextlib import nullcontext
    import trust_engine.contract_intelligence.ingestion as ingestion

    source = tmp_path / "broken.pdf"
    source.write_bytes(b"not a real pdf")
    events = []
    monkeypatch.setattr(ingestion, "local_document", lambda *_args, **_kwargs: nullcontext(source))
    monkeypatch.setattr(ingestion, "sha256_file", lambda _path: "b" * 64)
    monkeypatch.setattr(ingestion, "register_document", lambda **_kwargs: None)
    monkeypatch.setattr(
        ingestion, "record_ingestion_status",
        lambda **kwargs: events.append((kwargs["stage"], kwargs["status"], kwargs.get("error_message"))),
    )
    monkeypatch.setattr(ingestion, "_set_document_ingestion_status",
                        lambda _document_id, status: events.append(("DOCUMENT", status, None)))
    monkeypatch.setattr(ingestion, "extract_pdf",
                        lambda _path: (_ for _ in ()).throw(RuntimeError("bad PDF")))

    try:
        ingestion.ingest_pdf(source, contract_id="C-2", run_id="RUN-2")
    except RuntimeError as exc:
        assert str(exc) == "bad PDF"
    else:
        raise AssertionError("expected extraction failure")

    assert ("PDF_EXTRACTION", "RUNNING", None) in events
    assert any(stage == "PDF_EXTRACTION" and status == "FAILED" and error == "bad PDF"
               for stage, status, error in events)
    assert ("DOCUMENT", "FAILED", None) in events



def test_retry_ingest_pdf_retries_transient_failure_with_same_ids(monkeypatch):
    import trust_engine.contract_intelligence.ingestion as ingestion

    calls = []
    statuses = []
    sleeps = []

    def flaky_ingest(source, **kwargs):
        calls.append(kwargs.copy())
        if len(calls) == 1:
            raise TimeoutError("temporary Snowflake/network timeout")
        return ["chunk"]

    monkeypatch.setattr(ingestion, "ingest_pdf", flaky_ingest)
    monkeypatch.setattr(ingestion, "record_ingestion_status",
                        lambda **kwargs: statuses.append(kwargs))
    monkeypatch.setattr(ingestion.time, "sleep", sleeps.append)

    result = ingestion.retry_ingest_pdf(
        "contract.pdf",
        contract_id="C-10",
        document_id="DOC-10",
        run_id="RUN-10",
        max_attempts=3,
        base_delay_seconds=0.25,
    )

    assert result == ["chunk"]
    assert [call["attempt"] for call in calls] == [1, 2]
    assert all(call["document_id"] == "DOC-10" for call in calls)
    assert all(call["run_id"] == "RUN-10" for call in calls)
    assert statuses[0]["stage"] == "INGESTION_RETRY"
    assert statuses[0]["status"] == "RETRYING"
    assert statuses[0]["attempt"] == 1
    assert statuses[1]["status"] == "SUCCEEDED"
    assert statuses[1]["attempt"] == 2
    assert sleeps == [0.25]


def test_retry_ingest_pdf_does_not_retry_non_transient_failure(monkeypatch):
    import trust_engine.contract_intelligence.ingestion as ingestion

    calls = []
    monkeypatch.setattr(
        ingestion, "ingest_pdf",
        lambda *_args, **_kwargs: (calls.append(1), (_ for _ in ()).throw(ValueError("bad input")))[1],
    )

    try:
        ingestion.retry_ingest_pdf(
            "contract.pdf", contract_id="C-11", document_id="DOC-11",
            run_id="RUN-11", max_attempts=4,
        )
    except ValueError as exc:
        assert str(exc) == "bad input"
    else:
        raise AssertionError("expected non-transient failure")

    assert len(calls) == 1


def test_retry_ingest_pdf_validates_retry_configuration():
    import trust_engine.contract_intelligence.ingestion as ingestion

    for kwargs in (
        {"document_id": "", "run_id": "RUN"},
        {"document_id": "DOC", "run_id": ""},
        {"document_id": "DOC", "run_id": "RUN", "max_attempts": 0},
        {"document_id": "DOC", "run_id": "RUN", "base_delay_seconds": -1},
    ):
        options = {"contract_id": "C-12", **kwargs}
        try:
            ingestion.retry_ingest_pdf("contract.pdf", **options)
        except ValueError:
            continue
        raise AssertionError(f"Expected invalid retry configuration to fail: {kwargs}")



def test_retry_ingest_pdf_marks_exhausted_retry_failed(monkeypatch):
    import trust_engine.contract_intelligence.ingestion as ingestion

    statuses = []
    monkeypatch.setattr(
        ingestion, "ingest_pdf",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(TimeoutError("still unavailable")),
    )
    monkeypatch.setattr(ingestion, "record_ingestion_status",
                        lambda **kwargs: statuses.append(kwargs))
    monkeypatch.setattr(ingestion.time, "sleep", lambda _seconds: None)

    try:
        ingestion.retry_ingest_pdf(
            "contract.pdf", contract_id="C-13", document_id="DOC-13",
            run_id="RUN-13", max_attempts=2, base_delay_seconds=0,
        )
    except TimeoutError as exc:
        assert str(exc) == "still unavailable"
    else:
        raise AssertionError("expected retry exhaustion")

    assert [item["status"] for item in statuses] == ["RETRYING", "FAILED"]
    assert [item["attempt"] for item in statuses] == [1, 2]
