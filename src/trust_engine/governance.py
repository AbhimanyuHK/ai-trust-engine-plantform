"""Deterministic approval policy and durable approval request operations."""
from __future__ import annotations
import json
import uuid
from typing import Any
from trust_engine.db import connection, query

def approval_required(change_type: str, change_percent: float | None = None,
                      contract_activation: bool = False) -> bool:
    if contract_activation or change_type == "contract_activation":
        return True
    if change_type == "royalty_change":
        return change_percent is None or abs(change_percent) >= 5.0
    if change_type == "discount_change":
        return change_percent is None or abs(change_percent) >= 10.0
    return True

def create_approval(recommendation_id: str, workflow_id: str, change_type: str,
                    payload: dict[str,Any], required_role: str,
                    change_percent: float | None = None) -> str:
    if not approval_required(change_type,change_percent):
        raise ValueError("This change does not require human approval under current policy")
    approval_id = str(uuid.uuid4())
    sql = """INSERT INTO GOVERNANCE.APPROVAL_REQUESTS
      (APPROVAL_ID,RECOMMENDATION_ID,WORKFLOW_ID,CHANGE_TYPE,REQUIRED_ROLE,STATUS,
       PAYLOAD,CREATED_AT,UPDATED_AT)
      SELECT %s,%s,%s,%s,%s,'PENDING',PARSE_JSON(%s),CURRENT_TIMESTAMP(),CURRENT_TIMESTAMP()"""
    with connection() as conn, conn.cursor() as cur:
        cur.execute(sql,(approval_id,recommendation_id,workflow_id,change_type,required_role,
                         json.dumps(payload,default=str)))
    return approval_id

def decide_approval(approval_id: str, decision: str, reviewer: str, role: str,
                    reason: str, modified_payload: dict[str,Any] | None = None) -> None:
    decision = decision.upper()
    if decision not in {"APPROVED","REJECTED","MODIFIED"}:
        raise ValueError("decision must be APPROVED, REJECTED or MODIFIED")
    if not reviewer.strip() or not reason.strip():
        raise ValueError("reviewer and decision reason are required")
    rows = query("SELECT REQUIRED_ROLE,STATUS FROM GOVERNANCE.APPROVAL_REQUESTS WHERE APPROVAL_ID=%s",
                 (approval_id,))
    if not rows:
        raise ValueError("Approval request not found")
    if rows[0]["STATUS"] != "PENDING":
        raise ValueError("Approval request is no longer pending")
    if rows[0]["REQUIRED_ROLE"].lower() != role.lower():
        raise PermissionError("Reviewer does not have the required approval role")
    sql = """UPDATE GOVERNANCE.APPROVAL_REQUESTS SET STATUS=%s,REVIEWER=%s,REVIEWER_ROLE=%s,
      DECISION_REASON=%s,DECIDED_AT=CURRENT_TIMESTAMP(),UPDATED_AT=CURRENT_TIMESTAMP(),
      MODIFIED_PAYLOAD=PARSE_JSON(%s) WHERE APPROVAL_ID=%s AND STATUS='PENDING'"""
    payload = json.dumps(modified_payload,default=str) if modified_payload is not None else None
    with connection() as conn, conn.cursor() as cur:
        cur.execute(sql,(decision,reviewer,role,reason,payload,approval_id))
        if cur.rowcount != 1:
            raise RuntimeError("Approval was concurrently updated; reload current state")

def get_approval(approval_id: str) -> dict[str,Any] | None:
    rows = query("SELECT * FROM GOVERNANCE.APPROVAL_REQUESTS WHERE APPROVAL_ID=%s",(approval_id,))
    return rows[0] if rows else None
