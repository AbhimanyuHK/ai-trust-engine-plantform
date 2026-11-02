from trust_engine.workflows.contract_recommendation import (
    _record_workflow,
    _status_from_result,
    get_workflow_status,
    list_workflow_events,
)


def test_workflow_registry_tracks_lifecycle_and_events(tmp_path):
    database = str(tmp_path / "state" / "workflows.sqlite")

    _record_workflow(
        database,
        "thread-1",
        "RUNNING",
        event_type="WORKFLOW_STARTED",
        details={"question": "Review contract"},
        contract_id="C-1",
        partner_id="P-1",
    )
    _record_workflow(
        database,
        "thread-1",
        "WAITING_FOR_APPROVAL",
        event_type="WORKFLOW_PAUSED",
        details={"node": "human_approval"},
    )

    status = get_workflow_status("thread-1", database)
    events = list_workflow_events("thread-1", database)

    assert status is not None
    assert status["workflow_type"] == "CONTRACT_RECOMMENDATION"
    assert status["contract_id"] == "C-1"
    assert status["partner_id"] == "P-1"
    assert status["status"] == "WAITING_FOR_APPROVAL"
    assert status["completed_at"] is None
    assert [event["status"] for event in events] == ["RUNNING", "WAITING_FOR_APPROVAL"]
    assert events[0]["details"] == {"question": "Review contract"}
    assert events[1]["event_type"] == "WORKFLOW_PAUSED"


def test_workflow_registry_marks_terminal_state_and_error(tmp_path):
    database = str(tmp_path / "workflows.sqlite")
    _record_workflow(database, "thread-2", "RUNNING", event_type="WORKFLOW_STARTED")
    _record_workflow(
        database,
        "thread-2",
        "FAILED",
        event_type="WORKFLOW_FAILED",
        error="database unavailable",
        details={"error": "database unavailable"},
    )

    status = get_workflow_status("thread-2", database)
    assert status["status"] == "FAILED"
    assert status["completed_at"] is not None
    assert status["last_error"] == "database unavailable"


def test_workflow_status_detects_interrupt_and_terminal_approval():
    assert _status_from_result({"__interrupt__": ["approval"]}) == "WAITING_FOR_APPROVAL"
    assert _status_from_result({"status": "APPROVED"}) == "APPROVED"
    assert _status_from_result({"status": "REJECTED"}) == "REJECTED"
    assert _status_from_result({"status": "REVISION_REQUIRED"}) == "REVISION_REQUIRED"
    assert _status_from_result({"status": "RECOMMENDATION_VALIDATED"}) == "COMPLETED"
