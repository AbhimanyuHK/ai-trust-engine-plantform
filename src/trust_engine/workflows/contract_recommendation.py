"""Durable LangGraph contract recommendation workflow and execution registry."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypedDict

from trust_engine.contract_intelligence.cortex import complete, grounded_contract_answer
from trust_engine.common.infrastructure.db import query


class ContractState(TypedDict, total=False):
    question: str
    contract_id: str
    partner_id: str
    evidence: dict[str, Any]
    business_context: dict[str, Any]
    recommendation: dict[str, Any]
    approval_decision: dict[str, Any]
    status: str


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def _registry_connection(path: str):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(target), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS workflow_runs (
                thread_id TEXT PRIMARY KEY,
                workflow_type TEXT NOT NULL,
                contract_id TEXT,
                partner_id TEXT,
                status TEXT NOT NULL,
                current_step TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                completed_at TEXT,
                last_error TEXT
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS workflow_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                thread_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                status TEXT NOT NULL,
                details_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                FOREIGN KEY(thread_id) REFERENCES workflow_runs(thread_id)
            )"""
        )
        conn.commit()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    finally:
        conn.close()


def _record_workflow(
    path: str,
    thread_id: str,
    status: str,
    *,
    event_type: str,
    details: dict[str, Any] | None = None,
    contract_id: str | None = None,
    partner_id: str | None = None,
    error: str | None = None,
) -> None:
    now = _utc_now()
    with _registry_connection(path) as conn:
        existing = conn.execute(
            "SELECT thread_id FROM workflow_runs WHERE thread_id = ?", (thread_id,)
        ).fetchone()
        if existing:
            conn.execute(
                """UPDATE workflow_runs
                   SET status=?, updated_at=?, completed_at=?,
                       last_error=?, current_step=?
                   WHERE thread_id=?""",
                (
                    status, now,
                    now if status in {"COMPLETED", "APPROVED", "REJECTED", "REVISION_REQUIRED", "FAILED"} else None,
                    error,
                    event_type,
                    thread_id,
                ),
            )
        else:
            conn.execute(
                """INSERT INTO workflow_runs
                   (thread_id, workflow_type, contract_id, partner_id, status,
                    current_step, created_at, updated_at, last_error)
                   VALUES (?, 'CONTRACT_RECOMMENDATION', ?, ?, ?, ?, ?, ?, ?)""",
                (thread_id, contract_id, partner_id, status, event_type, now, now, error),
            )
        conn.execute(
            """INSERT INTO workflow_events
               (thread_id, event_type, status, details_json, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (thread_id, event_type, status, json.dumps(details or {}, default=str), now),
        )


def get_workflow_status(thread_id: str, checkpoint_path: str) -> dict[str, Any] | None:
    """Return the latest workflow registry row for a thread."""
    with _registry_connection(checkpoint_path) as conn:
        row = conn.execute(
            "SELECT * FROM workflow_runs WHERE thread_id = ?", (thread_id,)
        ).fetchone()
        return dict(row) if row else None


def list_workflow_events(thread_id: str, checkpoint_path: str) -> list[dict[str, Any]]:
    """Return append-only execution events ordered by insertion."""
    with _registry_connection(checkpoint_path) as conn:
        rows = conn.execute(
            """SELECT event_id, thread_id, event_type, status, details_json, created_at
               FROM workflow_events WHERE thread_id=? ORDER BY event_id""",
            (thread_id,),
        ).fetchall()
        return [
            {**dict(row), "details": json.loads(row["details_json"])}
            for row in rows
        ]


def build_contract_graph(checkpointer: Any | None = None) -> Any:
    try:
        from langgraph.graph import END, START, StateGraph
        from langgraph.types import interrupt
    except ImportError as exc:
        raise RuntimeError("Install optional dependencies: pip install -e '.[agent]'") from exc

    def retrieve_contract(state: ContractState) -> ContractState:
        evidence = grounded_contract_answer(
            state["question"],
            contract_id=state.get("contract_id"),
            partner_id=state.get("partner_id"),
        )
        return {"evidence": evidence, "status": "CONTRACT_EVIDENCE_RETRIEVED"}

    def route_evidence(state: ContractState) -> str:
        return "retrieve_business" if state.get("evidence", {}).get("grounded") else "finish"

    def retrieve_business_context(state: ContractState) -> ContractState:
        partner_id = state.get("partner_id")
        if not partner_id:
            return {
                "business_context": {
                    "transactions": [], "forecasts": [],
                    "note": "No partner identifier supplied; structured partner facts were not queried.",
                }
            }
        transactions = query(
            """SELECT TRANSACTION_TYPE, COUNT(*) AS TRANSACTION_COUNT,
                      SUM(AMOUNT) AS NET_AMOUNT, MIN(TRANSACTION_DATE) AS FIRST_DATE,
                      MAX(TRANSACTION_DATE) AS LAST_DATE
               FROM CORE.TRANSACTIONS WHERE PARTNER_ID=%s
                 AND TRANSACTION_DATE>=DATEADD(day,-90,CURRENT_DATE())
               GROUP BY TRANSACTION_TYPE""",
            (partner_id,),
        )
        forecasts = query(
            """SELECT FORECAST_DATE, PREDICTED_REVENUE, PREDICTED_ROYALTY,
                      MODEL_NAME, MODEL_VERSION
               FROM FORECAST.DEMAND_FORECAST WHERE PARTNER_ID=%s
                 AND FORECAST_DATE>=CURRENT_DATE()
               ORDER BY FORECAST_DATE LIMIT 30""",
            (partner_id,),
        )
        return {"business_context": {"transactions": transactions, "forecasts": forecasts}}

    def analyze(state: ContractState) -> ContractState:
        prompt = (
            "You are preparing a contract recommendation for a human reviewer. Use only "
            "the contract evidence and structured facts supplied. Never invent royalty rates, "
            "legal obligations, dates, or financial values. Separate verified facts from "
            "recommendations, cite contract ID/page/section, and call out missing information.\n"
            f"QUESTION: {state['question']}\n"
            f"CONTRACT EVIDENCE: {json.dumps(state.get('evidence', {}), default=str)}\n"
            f"STRUCTURED BUSINESS CONTEXT: {json.dumps(state.get('business_context', {}), default=str)}"
        )
        recommendation = complete(prompt)
        if not recommendation.strip():
            raise ValueError("Cortex returned an empty recommendation")
        return {
            "recommendation": {
                "text": recommendation,
                "citations": state["evidence"].get("citations", []),
                "structured_context": state.get("business_context", {}),
                "requires_human_review": True,
            },
            "status": "RECOMMENDATION_VALIDATED",
        }

    def human_approval(state: ContractState) -> ContractState:
        decision = interrupt({
            "kind": "contract_recommendation",
            "recommendation": state["recommendation"],
            "contract_id": state.get("contract_id"),
            "partner_id": state.get("partner_id"),
            "allowed_decisions": ["APPROVED", "REJECTED", "MODIFIED"],
        })
        normalized = str(decision.get("decision", "")).upper()
        if normalized not in {"APPROVED", "REJECTED", "MODIFIED"}:
            raise ValueError("Resume requires APPROVED, REJECTED or MODIFIED decision")
        return {
            "approval_decision": decision,
            "status": {
                "APPROVED": "APPROVED",
                "REJECTED": "REJECTED",
                "MODIFIED": "REVISION_REQUIRED",
            }[normalized],
        }

    graph = StateGraph(ContractState)
    graph.add_node("retrieve_contract", retrieve_contract)
    graph.add_node("retrieve_business_context", retrieve_business_context)
    graph.add_node("analyze_and_recommend", analyze)
    graph.add_node("human_approval", human_approval)
    graph.add_edge(START, "retrieve_contract")
    graph.add_conditional_edges(
        "retrieve_contract", route_evidence,
        {"retrieve_business": "retrieve_business_context", "finish": END},
    )
    graph.add_edge("retrieve_business_context", "analyze_and_recommend")
    graph.add_edge("analyze_and_recommend", "human_approval")
    graph.add_edge("human_approval", END)
    return graph.compile(checkpointer=checkpointer)


@contextmanager
def sqlite_checkpointer(path: str):
    """Open a local SQLite checkpointer; production should use shared durable storage."""
    try:
        from langgraph.checkpoint.sqlite import SqliteSaver
    except ImportError as exc:
        raise RuntimeError("Install optional dependencies: pip install -e '.[agent]'") from exc
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    # Initialize the adjacent workflow registry and SQLite durability settings.
    with _registry_connection(path) as conn:
        conn.execute("PRAGMA synchronous=FULL")
    with SqliteSaver.from_conn_string(path) as saver:
        yield saver


def _is_interrupted(result: dict[str, Any]) -> bool:
    return bool(result.get("__interrupt__"))


def _status_from_result(result: dict[str, Any]) -> str:
    if _is_interrupted(result):
        return "WAITING_FOR_APPROVAL"
    state_status = str(result.get("status", "")).upper()
    if state_status in {"APPROVED", "REJECTED", "REVISION_REQUIRED"}:
        return state_status
    return "COMPLETED"


def start_contract_workflow(
    question: str,
    thread_id: str,
    contract_id: str | None = None,
    partner_id: str | None = None,
    checkpointer: Any | None = None,
    *,
    checkpoint_path: str | None = None,
) -> dict[str, Any]:
    """Start exactly one run per thread ID and persist lifecycle metadata beside checkpoints."""
    if checkpointer is None:
        raise ValueError("A persistent checkpointer is required for resumable workflows")
    if not question.strip() or not thread_id.strip():
        raise ValueError("question and thread_id are required")
    if checkpoint_path is None:
        from trust_engine.common.config.settings import Settings
        checkpoint_path = Settings().trust_checkpoint_db
    path = checkpoint_path
    existing = get_workflow_status(thread_id, path)
    if existing:
        raise ValueError(
            f"Workflow thread {thread_id!r} already exists with status {existing['status']}; "
            "use resume_contract_workflow or a new thread_id"
        )
    _record_workflow(
        path, thread_id, "RUNNING", event_type="WORKFLOW_STARTED",
        details={"question": question}, contract_id=contract_id, partner_id=partner_id,
    )
    try:
        graph = build_contract_graph(checkpointer)
        result = graph.invoke(
            {"question": question, "contract_id": contract_id, "partner_id": partner_id},
            config=config,
        )
        status = _status_from_result(result)
        _record_workflow(
            path, thread_id, status, event_type="WORKFLOW_PAUSED" if status == "WAITING_FOR_APPROVAL" else "WORKFLOW_FINISHED",
            details={"state_status": result.get("status")},
        )
        return result
    except Exception as exc:
        _record_workflow(
            path, thread_id, "FAILED", event_type="WORKFLOW_FAILED",
            error=str(exc)[:16000], details={"error": str(exc)[:16000]},
        )
        raise


def resume_contract_workflow(
    thread_id: str,
    decision: str,
    reviewer: str,
    reason: str,
    checkpointer: Any,
    modified_payload: dict[str, Any] | None = None,
    *,
    checkpoint_path: str | None = None,
) -> dict[str, Any]:
    """Resume a paused thread; the checkpointer restores graph state without rerunning prior nodes."""
    try:
        from langgraph.types import Command
    except ImportError as exc:
        raise RuntimeError("Install optional dependencies: pip install -e '.[agent]'") from exc
    normalized = decision.upper()
    if normalized not in {"APPROVED", "REJECTED", "MODIFIED"}:
        raise ValueError("Unsupported approval decision")
    if not reviewer.strip() or not reason.strip():
        raise ValueError("Reviewer identity and reason are required")
    if checkpoint_path is None:
        from trust_engine.common.config.settings import Settings
        checkpoint_path = Settings().trust_checkpoint_db
    current = get_workflow_status(thread_id, checkpoint_path)
    if not current:
        raise ValueError(f"Unknown workflow thread: {thread_id}")
    if current["status"] not in {"WAITING_FOR_APPROVAL", "RESUMING"}:
        raise ValueError(
            f"Workflow {thread_id!r} is {current['status']}, not awaiting or recovering approval"
        )

    # A process may have crashed after recording RESUMING. Inspect the persisted
    # checkpoint before replaying the resume command to avoid applying a decision twice.
    graph = build_contract_graph(checkpointer)
    config = {"configurable": {"thread_id": thread_id}}
    if current["status"] == "RESUMING":
        snapshot = graph.get_state(config)
        if snapshot and not snapshot.next:
            recovered = dict(snapshot.values)
            recovered_status = _status_from_result(recovered)
            _record_workflow(
                checkpoint_path, thread_id, recovered_status,
                event_type="WORKFLOW_RESUME_RECOVERED",
                details={"state_status": recovered.get("status")},
            )
            return recovered

    _record_workflow(
        checkpoint_path, thread_id, "RESUMING", event_type="APPROVAL_SUBMITTED",
        details={
            "decision": normalized, "reviewer": reviewer, "reason": reason,
            "modified_payload": modified_payload,
        },
    )
    try:
        result = graph.invoke(
            Command(resume={
                "decision": normalized,
                "reviewer": reviewer,
                "reason": reason,
                "modified_payload": modified_payload,
            }),
            config={"configurable": {"thread_id": thread_id}},
        )
        status = _status_from_result(result)
        _record_workflow(
            checkpoint_path, thread_id, status,
            event_type="WORKFLOW_PAUSED" if status == "WAITING_FOR_APPROVAL" else "WORKFLOW_RESUMED",
            details={"decision": normalized, "reviewer": reviewer, "state_status": result.get("status")},
        )
        return result
    except Exception as exc:
        _record_workflow(
            checkpoint_path, thread_id, "FAILED", event_type="WORKFLOW_RESUME_FAILED",
            error=str(exc)[:16000], details={"error": str(exc)[:16000]},
        )
        raise
