import pytest

pytest.importorskip("langgraph")

import trust_engine.workflows.contract_intelligence_workflow as workflow
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
        "search_refresh_timeout_seconds": 10,
        "search_refresh_poll_interval_seconds": 0.1,
    })

    assert result["status"] == "COMPLETED"
    assert result["current_stage"] == "CORTEX_SEARCH_INDEXED"
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
            "search_refresh_timeout_seconds": 10,
            "search_refresh_poll_interval_seconds": 0.1,
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



def test_cortex_search_refresh_uses_configured_service_and_waits_for_success(monkeypatch):
    from contextlib import nullcontext
    from types import SimpleNamespace

    statements = []

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, sql):
            statements.append(sql)

    class Connection:
        def cursor(self):
            return Cursor()

    monkeypatch.setattr(workflow, "connection", lambda _settings: nullcontext(Connection()))
    def fake_query(sql, _params, _settings):
        if sql.strip().startswith("SELECT CURRENT_TIMESTAMP"):
            return [{"STARTED_AT": "2026-11-02T00:00:00+00:00"}]
        return [{"STATE": "SUCCEEDED", "REFRESH_TRIGGER": "MANUAL"}]

    monkeypatch.setattr(workflow, "query", fake_query)
    settings = SimpleNamespace(cortex_search_service="TRUST_DB.AI.CONTRACT_SEARCH_SERVICE")

    result = workflow._refresh_and_wait_for_cortex_search(
        settings=settings, timeout_seconds=1, poll_interval_seconds=0.01
    )

    assert result["STATE"] == "SUCCEEDED"
    assert (
        "ALTER CORTEX SEARCH SERVICE TRUST_DB.AI.CONTRACT_SEARCH_SERVICE REFRESH"
        in statements[0]
    )
