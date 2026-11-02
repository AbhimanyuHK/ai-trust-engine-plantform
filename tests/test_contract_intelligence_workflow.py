import pytest

pytest.importorskip("langgraph")

from trust_engine.workflows.contract_intelligence_workflow import (
    _build_request_payload,
    build_contract_intelligence_graph,
)


def test_contract_intelligence_graph_delegates_processing_to_ingestion():
    calls = []

    def fake_ingest(source, **kwargs):
        calls.append((source, kwargs))
        return [object(), object(), object()]

    graph = build_contract_intelligence_graph(
        ingest_callable=fake_ingest,
        refresh_callable=lambda **_kwargs: {"STATE": "SUCCEEDED", "REFRESH_TRIGGER": "MANUAL"},
    )
    result = graph.invoke({
        "run_id": "RUN-1",
        "source": "s3://contracts/C-1/v1.pdf",
        "contract_id": "C-1",
        "document_id": "DOC-1",
        "document_version": 1,
        "contract_version": 1,
        "document_type": "ORIGINAL",
        "chunk_size": 450,
        "overlap": 60,
        "max_attempts": 3,
        "base_delay_seconds": 1.0,
    })

    assert result["status"] == "COMPLETED"
    assert result["current_stage"] == "CHUNKS_PERSISTED"
    assert result["chunk_count"] == 3
    assert result["search_index_status"] == "SUCCEEDED"
    assert result["search_refresh"]["STATE"] == "SUCCEEDED"
    assert calls[0][0] == "s3://contracts/C-1/v1.pdf"
    assert calls[0][1]["run_id"] == "RUN-1"
    assert calls[0][1]["document_id"] == "DOC-1"
    assert calls[0][1]["contract_id"] == "C-1"


def test_contract_intelligence_graph_does_not_complete_empty_pdf():
    graph = build_contract_intelligence_graph(ingest_callable=lambda *_args, **_kwargs: [])
    with pytest.raises(ValueError, match="no text chunks"):
        graph.invoke({
            "run_id": "RUN-2",
            "source": "empty.pdf",
            "contract_id": "C-2",
            "document_id": "DOC-2",
            "document_version": 1,
            "contract_version": 1,
            "document_type": "ORIGINAL",
            "chunk_size": 450,
            "overlap": 60,
            "max_attempts": 1,
            "base_delay_seconds": 0,
        })


@pytest.mark.parametrize(
    "overrides",
    [
        {"document_id": ""},
        {"contract_id": ""},
        {"document_version": 0},
        {"contract_version": 0},
        {"chunk_size": 10, "overlap": 10},
        {"max_attempts": 0},
        {"base_delay_seconds": -0.1},
        {"effective_date": "2026-07-01", "expiry_date": "2026-06-30"},
    ],
)
def test_contract_intelligence_request_validation(overrides):
    options = {
        "source": "s3://contracts/C-3/v1.pdf",
        "contract_id": "C-3",
        "document_id": "DOC-3",
    }
    options.update(overrides)
    with pytest.raises(ValueError):
        _build_request_payload(**options)


def test_contract_intelligence_request_is_replayable_and_normalized():
    payload = _build_request_payload(
        source="s3://contracts/C-4/v2.pdf",
        contract_id="C-4",
        document_id="DOC-4",
        document_type="amendment",
        document_version=2,
        contract_version=2,
        effective_date="2026-07-01",
        expiry_date="2027-06-30",
    )
    assert payload["document_type"] == "AMENDMENT"
    assert payload["document_id"] == "DOC-4"
    assert payload["source"] == "s3://contracts/C-4/v2.pdf"
    assert payload["document_version"] == 2
