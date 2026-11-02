"""FastAPI interface for contract RAG, governed analytics and HITL decisions."""
from __future__ import annotations
from typing import Any
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from trust_engine.analytics import ask_analytics
from trust_engine.cortex import grounded_contract_answer
from trust_engine.governance import create_approval,decide_approval,get_approval

app=FastAPI(title="AI TRUST Engine API",version="0.2.0")

class ContractQuestion(BaseModel):
    question: str = Field(min_length=3,max_length=4000)
    contract_id: str | None = None
    partner_id: str | None = None

class AnalyticsQuestion(BaseModel):
    question: str = Field(min_length=3,max_length=2000)

class ApprovalCreate(BaseModel):
    recommendation_id: str
    workflow_id: str
    change_type: str
    required_role: str
    payload: dict[str,Any]
    change_percent: float | None = None

class ApprovalDecision(BaseModel):
    decision: str
    reviewer: str
    role: str
    reason: str
    modified_payload: dict[str,Any] | None = None

@app.get("/health")
def health() -> dict[str,str]:
    return {"status":"ok"}

@app.post("/v1/contracts/ask")
def ask_contract(request: ContractQuestion) -> dict[str,Any]:
    try:
        return grounded_contract_answer(request.question,contract_id=request.contract_id,
                                        partner_id=request.partner_id)
    except Exception as exc:
        raise HTTPException(status_code=502,detail="Contract retrieval failed") from exc

@app.post("/v1/analytics/ask")
def ask_business_question(request: AnalyticsQuestion) -> dict[str,Any]:
    semantic = """CORE.TRANSACTIONS(TRANSACTION_DATE,PARTNER_ID,TRANSACTION_TYPE,AMOUNT,CURRENCY);
CORE.CONTRACTS(CONTRACT_ID,PARTNER_ID,EFFECTIVE_DATE,EXPIRY_DATE,COUNTRY,STATUS);
FORECAST.DEMAND_FORECAST(FORECAST_DATE,PARTNER_ID,PREDICTED_REVENUE,PREDICTED_ROYALTY,MODEL_NAME)."""
    try:
        return ask_analytics(request.question,semantic,
          {"CORE.TRANSACTIONS","CORE.CONTRACTS","FORECAST.DEMAND_FORECAST"})
    except ValueError as exc:
        raise HTTPException(status_code=400,detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502,detail="Analytics execution failed") from exc

@app.post("/v1/approvals")
def submit_approval(request: ApprovalCreate) -> dict[str,str]:
    try:
        approval_id=create_approval(request.recommendation_id,request.workflow_id,
          request.change_type,request.payload,request.required_role,request.change_percent)
        return {"approval_id":approval_id,"status":"PENDING"}
    except ValueError as exc:
        raise HTTPException(status_code=422,detail=str(exc)) from exc

@app.get("/v1/approvals/{approval_id}")
def approval_status(approval_id: str) -> dict[str,Any]:
    record=get_approval(approval_id)
    if record is None:
        raise HTTPException(status_code=404,detail="Approval request not found")
    return record

@app.post("/v1/approvals/{approval_id}/decision")
def approval_decision(approval_id: str,request: ApprovalDecision) -> dict[str,str]:
    try:
        decide_approval(approval_id,request.decision,request.reviewer,request.role,
                        request.reason,request.modified_payload)
        return {"approval_id":approval_id,"status":request.decision.upper()}
    except ValueError as exc:
        raise HTTPException(status_code=422,detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403,detail=str(exc)) from exc
