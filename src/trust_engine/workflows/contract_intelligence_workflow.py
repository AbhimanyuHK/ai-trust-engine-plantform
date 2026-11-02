"""LangGraph orchestration for versioned contract PDF ingestion.

The processing implementation lives in trust_engine.contract_intelligence.ingestion.
This module only coordinates it and records workflow lifecycle in Snowflake.
"""
from __future__ import annotations

import json
import re
import time
import uuid
from datetime import date, datetime, timezone
from typing import Any, Callable, TypedDict

from langgraph.graph import END, START, StateGraph

from trust_engine.common.config.settings import Settings
from trust_engine.common.infrastructure.db import connection, query
from trust_engine.contract_intelligence.ingestion import DocumentChunk, retry_ingest_pdf


RUNS_TABLE = "AI.CONTRACT_INTELLIGENCE_WORKFLOW_RUNS"
EVENTS_TABLE = "AI.CONTRACT_INTELLIGENCE_WORKFLOW_EVENTS"
TERMINAL_STATUSES = {"COMPLETED", "FAILED", "CANCELLED"}


class ContractIntelligenceWorkflowState(TypedDict, total=False):
    run_id: str
    document_id: str
    source: str
    contract_id: str
    partner_id: str | None
    document_name: str | None
    document_version: int
    contract_version: int
    document_type: str
    parent_document_id: str | None
    effective_date: str | None
    expiry_date: str | None
    chunk_size: int
    overlap: int
    max_attempts: int
    base_delay_seconds: float
    artifact_bucket: str | None
    search_refresh_timeout_seconds: float
    search_refresh_poll_interval_seconds: float
    chunk_count: int
    search_index_status: str
    status: str
    current_stage: str
    error_message: str | None


def _variant(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _load_run(run_id: str, settings: Settings | None = None) -> dict[str, Any] | None:
    rows = query(
        f"""SELECT RUN_ID, DOCUMENT_ID, CONTRACT_ID, PARTNER_ID, SOURCE_URI,
                   STATUS, CURRENT_STAGE, ATTEMPT, CHUNK_COUNT, ERROR_MESSAGE,
                   REQUEST_PAYLOAD, STARTED_AT, UPDATED_AT, COMPLETED_AT
            FROM {RUNS_TABLE} WHERE RUN_ID = %s""",
        (run_id,),
        settings,
    )
    if not rows:
        return None
    row = dict(rows[0])
    row["REQUEST_PAYLOAD"] = _variant(row.get("REQUEST_PAYLOAD"))
    return row


def _refresh_and_wait_for_cortex_search(
    *,
    settings: Settings | None = None,
    timeout_seconds: float = 600,
    poll_interval_seconds: float = 5,
) -> dict[str, Any]:
    """Trigger a manual Cortex Search refresh and wait for its refresh-history result."""
    if timeout_seconds <= 0 or poll_interval_seconds <= 0:
        raise ValueError("Search refresh timeout and poll interval must be positive")
    cfg = settings or Settings()
    parts = cfg.cortex_search_service.split(".")
    if len(parts) != 3 or any(not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$]*", part) for part in parts):
        raise ValueError("CORTEX_SEARCH_SERVICE must be a safe DATABASE.SCHEMA.SERVICE identifier")
    database, schema, service = parts
    service_fqn = ".".join(parts)
    started_at = datetime.now(timezone.utc).isoformat()

    with connection(cfg) as conn, conn.cursor() as cur:
        cur.execute(f"ALTER CORTEX SEARCH SERVICE {service_fqn} REFRESH")

    history_sql = f"""
        SELECT NAME, DATABASE_NAME, SCHEMA_NAME, STATE, REFRESH_TRIGGER,
               REFRESH_START_TIME, REFRESH_END_TIME, DATA_TIMESTAMP, ERROR
        FROM TABLE(INFORMATION_SCHEMA.CORTEX_SEARCH_REFRESH_HISTORY(
            NAME => '{service}',
            DATA_TIMESTAMP_START => DATEADD(HOUR, -24, CURRENT_TIMESTAMP()),
            RESULT_LIMIT => 100
        ))
        WHERE DATABASE_NAME = %s
          AND SCHEMA_NAME = %s
          AND NAME = %s
          AND REFRESH_TRIGGER = 'MANUAL'
          AND REFRESH_START_TIME >= %s::TIMESTAMP_TZ
        ORDER BY REFRESH_START_TIME DESC
        LIMIT 1
    """
    deadline = time.monotonic() + timeout_seconds
    while True:
        rows = query(history_sql, (database, schema, service, started_at), cfg)
        if rows:
            result = dict(rows[0])
            state = str(result.get("STATE") or "").upper()
            if state == "SUCCEEDED":
                return result
            if state in {"FAILED", "CANCELLED"}:
                raise RuntimeError(
                    f"Cortex Search refresh {state.lower()}: "
                    f"{result.get('ERROR') or 'no Snowflake error detail returned'}"
                )
        if time.monotonic() >= deadline:
            raise TimeoutError(
                f"Timed out waiting {timeout_seconds}s for Cortex Search refresh "
                f"{database}.{schema}.{service}"
            )
        time.sleep(poll_interval_seconds)


def _record_workflow(
    *,
    run_id: str,
    document_id: str,
    contract_id: str,
    source_uri: str,
    status: str,
    event_type: str,
    current_stage: str,
    partner_id: str | None = None,
    attempt: int = 1,
    chunk_count: int | None = None,
    error_message: str | None = None,
    request_payload: dict[str, Any] | None = None,
    details: dict[str, Any] | None = None,
    settings: Settings | None = None,
) -> None:
    """Upsert current run state and append its event in one Snowflake transaction."""
    normalized = status.upper()
    if normalized not in {"PENDING", "RUNNING", "COMPLETED", "FAILED", "CANCELLED"}:
        raise ValueError(f"Unsupported workflow status: {status}")
    if attempt < 1:
        raise ValueError("attempt must be >= 1")

    event_id = str(uuid.uuid4())
    payload_json = json.dumps(request_payload, default=str) if request_payload is not None else None
    details_json = json.dumps(details or {}, default=str)

    with connection(settings) as conn, conn.cursor() as cur:
        # Keep the run row and its event consistent if either write fails.
        conn.autocommit(False)
        try:
            cur.execute(
                f"""
                MERGE INTO {RUNS_TABLE} T
                USING (
                    SELECT %s::VARCHAR RUN_ID, %s::VARCHAR DOCUMENT_ID,
                           %s::VARCHAR CONTRACT_ID, %s::VARCHAR PARTNER_ID,
                           %s::VARCHAR SOURCE_URI, %s::VARCHAR STATUS,
                           %s::VARCHAR CURRENT_STAGE, %s::NUMBER ATTEMPT,
                           %s::NUMBER CHUNK_COUNT, %s::VARCHAR ERROR_MESSAGE,
                           PARSE_JSON(%s) REQUEST_PAYLOAD
                ) S
                ON T.RUN_ID = S.RUN_ID
                WHEN MATCHED THEN UPDATE SET
                    T.STATUS = S.STATUS,
                    T.CURRENT_STAGE = S.CURRENT_STAGE,
                    T.ATTEMPT = S.ATTEMPT,
                    T.CHUNK_COUNT = COALESCE(S.CHUNK_COUNT, T.CHUNK_COUNT),
                    T.ERROR_MESSAGE = S.ERROR_MESSAGE,
                    T.REQUEST_PAYLOAD = COALESCE(S.REQUEST_PAYLOAD, T.REQUEST_PAYLOAD),
                    T.UPDATED_AT = CURRENT_TIMESTAMP(),
                    T.COMPLETED_AT = IFF(
                        S.STATUS IN ('COMPLETED', 'FAILED', 'CANCELLED'),
                        CURRENT_TIMESTAMP(), NULL
                    )
                WHEN NOT MATCHED THEN INSERT (
                    RUN_ID, DOCUMENT_ID, CONTRACT_ID, PARTNER_ID, SOURCE_URI,
                    STATUS, CURRENT_STAGE, ATTEMPT, CHUNK_COUNT, ERROR_MESSAGE,
                    REQUEST_PAYLOAD, STARTED_AT, CREATED_AT, UPDATED_AT, COMPLETED_AT
                ) VALUES (
                    S.RUN_ID, S.DOCUMENT_ID, S.CONTRACT_ID, S.PARTNER_ID, S.SOURCE_URI,
                    S.STATUS, S.CURRENT_STAGE, S.ATTEMPT, S.CHUNK_COUNT, S.ERROR_MESSAGE,
                    S.REQUEST_PAYLOAD, CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP(),
                    CURRENT_TIMESTAMP(),
                    IFF(S.STATUS IN ('COMPLETED', 'FAILED', 'CANCELLED'),
                        CURRENT_TIMESTAMP(), NULL)
                )
                """,
                (
                    run_id, document_id, contract_id, partner_id, source_uri, normalized,
                    current_stage, attempt, chunk_count, error_message, payload_json,
                ),
            )
            cur.execute(
                f"""
                INSERT INTO {EVENTS_TABLE} (
                    EVENT_ID, RUN_ID, DOCUMENT_ID, EVENT_TYPE, STAGE, STATUS,
                    ATTEMPT, DETAILS, CREATED_AT
                )
                SELECT %s, %s, %s, %s, %s, %s, %s, PARSE_JSON(%s), CURRENT_TIMESTAMP()
                """,
                (
                    event_id, run_id, document_id, event_type, current_stage,
                    normalized, attempt, details_json,
                ),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise


def _build_request_payload(
    *,
    source: str,
    contract_id: str,
    document_id: str,
    partner_id: str | None = None,
    document_name: str | None = None,
    document_version: int = 1,
    contract_version: int = 1,
    document_type: str = "ORIGINAL",
    parent_document_id: str | None = None,
    effective_date: str | None = None,
    expiry_date: str | None = None,
    chunk_size: int = 450,
    overlap: int = 60,
    max_attempts: int = 3,
    base_delay_seconds: float = 1.0,
    artifact_bucket: str | None = None,
    search_refresh_timeout_seconds: float = 600,
    search_refresh_poll_interval_seconds: float = 5,
) -> dict[str, Any]:
    if not source or not str(source).strip():
        raise ValueError("source is required")
    if not contract_id or not contract_id.strip():
        raise ValueError("contract_id is required")
    if not document_id or not document_id.strip():
        raise ValueError("document_id is required and must be stable across retries")
    if document_version < 1 or contract_version < 1:
        raise ValueError("document_version and contract_version must be >= 1")
    if chunk_size <= 0 or overlap < 0 or overlap >= chunk_size:
        raise ValueError("Require chunk_size > overlap >= 0")
    if max_attempts < 1 or base_delay_seconds < 0:
        raise ValueError("max_attempts must be >= 1 and base_delay_seconds >= 0")
    if search_refresh_timeout_seconds <= 0 or search_refresh_poll_interval_seconds <= 0:
        raise ValueError("Search refresh timeout and poll interval must be positive")
    parsed_effective = date.fromisoformat(effective_date) if effective_date else None
    parsed_expiry = date.fromisoformat(expiry_date) if expiry_date else None
    if parsed_effective and parsed_expiry and parsed_expiry < parsed_effective:
        raise ValueError("expiry_date cannot be earlier than effective_date")

    return {
        "source": str(source),
        "contract_id": contract_id,
        "document_id": document_id,
        "partner_id": partner_id,
        "document_name": document_name,
        "document_version": document_version,
        "contract_version": contract_version,
        "document_type": document_type.upper(),
        "parent_document_id": parent_document_id,
        "effective_date": effective_date,
        "expiry_date": expiry_date,
        "chunk_size": chunk_size,
        "overlap": overlap,
        "max_attempts": max_attempts,
        "base_delay_seconds": base_delay_seconds,
        "artifact_bucket": artifact_bucket,
        "search_refresh_timeout_seconds": search_refresh_timeout_seconds,
        "search_refresh_poll_interval_seconds": search_refresh_poll_interval_seconds,
    }


def build_contract_intelligence_graph(
    *,
    ingest_callable: Callable[..., list[DocumentChunk]] = retry_ingest_pdf,
    refresh_callable: Callable[..., dict[str, Any]] = _refresh_and_wait_for_cortex_search,
    settings: Settings | None = None,
):
    """Build ingestion -> managed Cortex Search indexing orchestration."""
    graph = StateGraph(ContractIntelligenceWorkflowState)

    def ingest_document(state: ContractIntelligenceWorkflowState) -> dict[str, Any]:
        chunks = ingest_callable(
            state["source"],
            contract_id=state["contract_id"],
            document_id=state["document_id"],
            run_id=state["run_id"],
            max_attempts=state["max_attempts"],
            base_delay_seconds=state["base_delay_seconds"],
            partner_id=state.get("partner_id"),
            document_name=state.get("document_name"),
            document_version=state["document_version"],
            contract_version=state["contract_version"],
            document_type=state["document_type"],
            parent_document_id=state.get("parent_document_id"),
            effective_date=state.get("effective_date"),
            expiry_date=state.get("expiry_date"),
            chunk_size=state["chunk_size"],
            overlap=state["overlap"],
            artifact_bucket=state.get("artifact_bucket"),
        )
        if not chunks:
            raise ValueError(
                "PDF processing produced no text chunks; verify the PDF text layer "
                "or install/configure the OCR extra before marking ingestion complete."
            )
        return {
            "chunk_count": len(chunks),
            "status": "RUNNING",
            "current_stage": "CHUNKS_PERSISTED",
        }

    def refresh_search_index(state: ContractIntelligenceWorkflowState) -> dict[str, Any]:
        refresh_result = refresh_callable(
            settings=settings,
            timeout_seconds=state["search_refresh_timeout_seconds"],
            poll_interval_seconds=state["search_refresh_poll_interval_seconds"],
        )
        return {
            "search_index_status": "SUCCEEDED",
            "search_refresh": refresh_result,
            "status": "COMPLETED",
            "current_stage": "CORTEX_SEARCH_INDEXED",
        }

    graph.add_node("ingest_document", ingest_document)
    graph.add_node("refresh_search_index", refresh_search_index)
    graph.add_edge(START, "ingest_document")
    graph.add_edge("ingest_document", "refresh_search_index")
    graph.add_edge("refresh_search_index", END)
    return graph.compile()


def _execute_payload(
    *,
    run_id: str,
    payload: dict[str, Any],
    workflow_attempt: int = 1,
    settings: Settings | None = None,
    ingest_callable: Callable[..., list[DocumentChunk]] = retry_ingest_pdf,
    refresh_callable: Callable[..., dict[str, Any]] = _refresh_and_wait_for_cortex_search,
) -> dict[str, Any]:
    document_id = payload["document_id"]
    contract_id = payload["contract_id"]
    source = payload["source"]
    graph = build_contract_intelligence_graph(
        ingest_callable=ingest_callable, refresh_callable=refresh_callable,
        settings=settings,
    )

    try:
        _record_workflow(
            run_id=run_id, document_id=document_id, contract_id=contract_id,
            source_uri=source, partner_id=payload.get("partner_id"),
            status="RUNNING", event_type="DOCUMENT_INGESTION_STARTED",
            current_stage="DOCUMENT_INGESTION", attempt=workflow_attempt,
            request_payload=payload, settings=settings,
        )
        result = graph.invoke({"run_id": run_id, **payload})
        _record_workflow(
            run_id=run_id, document_id=document_id, contract_id=contract_id,
            source_uri=source, partner_id=payload.get("partner_id"),
            status="COMPLETED", event_type="DOCUMENT_INGESTION_COMPLETED",
            current_stage="CORTEX_SEARCH_INDEXED", attempt=workflow_attempt,
            chunk_count=result["chunk_count"],
            details={
                "chunk_count": result["chunk_count"],
                "search_index_status": result["search_index_status"],
                "search_refresh": result["search_refresh"],
            },
            settings=settings,
        )
        return {
            "run_id": run_id,
            "document_id": document_id,
            "contract_id": contract_id,
            "status": "COMPLETED",
            "chunk_count": result["chunk_count"],
            "search_index_status": result["search_index_status"],
            "search_refresh": result["search_refresh"],
        }
    except Exception as exc:
        _record_workflow(
            run_id=run_id, document_id=document_id, contract_id=contract_id,
            source_uri=source, partner_id=payload.get("partner_id"),
            status="FAILED", event_type="DOCUMENT_INGESTION_FAILED",
            current_stage=(
                "CORTEX_SEARCH_INDEXING"
                if "result" in locals() and isinstance(result, dict) and "chunk_count" in result
                else "DOCUMENT_INGESTION"
            ),
            attempt=workflow_attempt,
            error_message=str(exc)[:16000],
            details={"error_type": type(exc).__name__, "error": str(exc)[:16000]},
            settings=settings,
        )
        raise


def start_contract_intelligence_workflow(
    source: str,
    *,
    contract_id: str,
    document_id: str,
    run_id: str | None = None,
    partner_id: str | None = None,
    document_name: str | None = None,
    document_version: int = 1,
    contract_version: int = 1,
    document_type: str = "ORIGINAL",
    parent_document_id: str | None = None,
    effective_date: str | None = None,
    expiry_date: str | None = None,
    chunk_size: int = 450,
    overlap: int = 60,
    max_attempts: int = 3,
    base_delay_seconds: float = 1.0,
    artifact_bucket: str | None = None,
    search_refresh_timeout_seconds: float = 600,
    search_refresh_poll_interval_seconds: float = 5,
    settings: Settings | None = None,
    ingest_callable: Callable[..., list[DocumentChunk]] = retry_ingest_pdf,
    refresh_callable: Callable[..., dict[str, Any]] = _refresh_and_wait_for_cortex_search,
) -> dict[str, Any]:
    """Start a PDF-to-chunks workflow and track its lifecycle in Snowflake.

    Cortex Search performs embedding/indexing asynchronously from its configured
    source table; this workflow does not create a duplicate embedding column.
    """
    payload = _build_request_payload(
        source=source, contract_id=contract_id, document_id=document_id,
        partner_id=partner_id, document_name=document_name,
        document_version=document_version, contract_version=contract_version,
        document_type=document_type, parent_document_id=parent_document_id,
        effective_date=effective_date, expiry_date=expiry_date,
        chunk_size=chunk_size, overlap=overlap, max_attempts=max_attempts,
        base_delay_seconds=base_delay_seconds, artifact_bucket=artifact_bucket,
        search_refresh_timeout_seconds=search_refresh_timeout_seconds,
        search_refresh_poll_interval_seconds=search_refresh_poll_interval_seconds,
    )
    execution_id = run_id or str(uuid.uuid4())
    if _load_run(execution_id, settings):
        raise ValueError(f"Workflow run_id already exists: {execution_id}")
    _record_workflow(
        run_id=execution_id, document_id=document_id, contract_id=contract_id,
        source_uri=str(source), partner_id=partner_id, status="PENDING",
        event_type="WORKFLOW_CREATED", current_stage="PENDING",
        request_payload=payload, settings=settings,
    )
    return _execute_payload(
        run_id=execution_id, payload=payload, settings=settings,
        ingest_callable=ingest_callable, refresh_callable=refresh_callable,
    )


def resume_contract_intelligence_workflow(
    run_id: str,
    *,
    settings: Settings | None = None,
    ingest_callable: Callable[..., list[DocumentChunk]] = retry_ingest_pdf,
    refresh_callable: Callable[..., dict[str, Any]] = _refresh_and_wait_for_cortex_search,
) -> dict[str, Any]:
    """Replay an interrupted/failed ingestion with the same stable IDs.

    Chunk/document writes use deterministic identifiers and Snowflake MERGE, so
    replay is at-least-once and idempotent. This resumes by replaying the ingestion
    operation, not by restoring an in-memory LangGraph node checkpoint.
    """
    row = _load_run(run_id, settings)
    if not row:
        raise ValueError(f"Unknown contract-intelligence workflow run_id: {run_id}")
    status = str(row.get("STATUS") or "").upper()
    if status in TERMINAL_STATUSES:
        raise ValueError(f"Cannot resume terminal workflow with status {status}")
    payload = row.get("REQUEST_PAYLOAD")
    if not isinstance(payload, dict):
        raise RuntimeError("Workflow request payload is missing or invalid; cannot resume safely")
    _record_workflow(
        run_id=run_id, document_id=row["DOCUMENT_ID"], contract_id=row["CONTRACT_ID"],
        source_uri=row["SOURCE_URI"], partner_id=row.get("PARTNER_ID"),
        status="RUNNING", event_type="WORKFLOW_RESUME_REQUESTED",
        current_stage="DOCUMENT_INGESTION", attempt=int(row.get("ATTEMPT") or 1) + 1,
        request_payload=payload, settings=settings,
    )
    return _execute_payload(
        run_id=run_id, payload=payload, workflow_attempt=int(row.get("ATTEMPT") or 1) + 1,
        settings=settings, ingest_callable=ingest_callable,
        refresh_callable=refresh_callable,
    )


def get_contract_intelligence_workflow_status(
    run_id: str, *, settings: Settings | None = None
) -> dict[str, Any] | None:
    """Return the current Snowflake workflow-run row."""
    return _load_run(run_id, settings)


def list_contract_intelligence_workflow_events(
    run_id: str, *, settings: Settings | None = None
) -> list[dict[str, Any]]:
    """Return append-only Snowflake workflow events for a run."""
    return query(
        f"""SELECT EVENT_ID, RUN_ID, DOCUMENT_ID, EVENT_TYPE, STAGE, STATUS,
                   ATTEMPT, DETAILS, CREATED_AT
            FROM {EVENTS_TABLE}
            WHERE RUN_ID = %s
            ORDER BY CREATED_AT, EVENT_ID""",
        (run_id,),
        settings,
    )
