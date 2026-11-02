"""LangGraph contract recommendation workflow with interrupt/resume checkpoints."""
from __future__ import annotations
from contextlib import contextmanager
from pathlib import Path
import json
from typing import Any,TypedDict
from trust_engine.cortex import complete,grounded_contract_answer
from trust_engine.db import query

class ContractState(TypedDict,total=False):
    question: str
    contract_id: str
    partner_id: str
    evidence: dict[str,Any]
    business_context: dict[str,Any]
    recommendation: dict[str,Any]
    approval_decision: dict[str,Any]
    status: str

def build_contract_graph(checkpointer: Any | None=None) -> Any:
    try:
        from langgraph.graph import END,START,StateGraph
        from langgraph.types import interrupt
    except ImportError as exc:
        raise RuntimeError("Install optional dependencies: pip install -e '.[agent]'") from exc

    def retrieve_contract(state: ContractState) -> ContractState:
        evidence=grounded_contract_answer(state["question"],contract_id=state.get("contract_id"),
                                          partner_id=state.get("partner_id"))
        return {"evidence":evidence,"status":"CONTRACT_EVIDENCE_RETRIEVED"}

    def route_evidence(state: ContractState) -> str:
        return "retrieve_business" if state.get("evidence",{}).get("grounded") else "finish"

    def retrieve_business_context(state: ContractState) -> ContractState:
        partner_id=state.get("partner_id")
        if not partner_id:
            return {"business_context":{"transactions":[],"forecasts":[],
              "note":"No partner identifier supplied; structured partner facts were not queried."}}
        transactions=query("""SELECT TRANSACTION_TYPE,COUNT(*) AS TRANSACTION_COUNT,
          SUM(AMOUNT) AS NET_AMOUNT,MIN(TRANSACTION_DATE) AS FIRST_DATE,
          MAX(TRANSACTION_DATE) AS LAST_DATE
          FROM CORE.TRANSACTIONS WHERE PARTNER_ID=%s
          AND TRANSACTION_DATE>=DATEADD(day,-90,CURRENT_DATE())
          GROUP BY TRANSACTION_TYPE""",(partner_id,))
        forecasts=query("""SELECT FORECAST_DATE,PREDICTED_REVENUE,PREDICTED_ROYALTY,
          MODEL_NAME,MODEL_VERSION FROM FORECAST.DEMAND_FORECAST
          WHERE PARTNER_ID=%s AND FORECAST_DATE>=CURRENT_DATE()
          ORDER BY FORECAST_DATE LIMIT 30""",(partner_id,))
        return {"business_context":{"transactions":transactions,"forecasts":forecasts}}

    def analyze(state: ContractState) -> ContractState:
        prompt=("You are preparing a contract recommendation for a human reviewer. "
          "Use only the contract evidence and structured facts supplied. Never invent royalty "
          "rates, legal obligations, dates, or financial values. Separate verified facts from "
          "recommendations, cite contract ID/page/section, and call out missing information.\n"
          f"QUESTION: {state['question']}\n"
          f"CONTRACT EVIDENCE: {json.dumps(state.get('evidence',{}),default=str)}\n"
          f"STRUCTURED BUSINESS CONTEXT: {json.dumps(state.get('business_context',{}),default=str)}")
        recommendation=complete(prompt)
        if not recommendation.strip():
            raise ValueError("Cortex returned an empty recommendation")
        return {"recommendation":{"text":recommendation,
          "citations":state["evidence"].get("citations",[]),
          "structured_context":state.get("business_context",{}),
          "requires_human_review":True},"status":"RECOMMENDATION_VALIDATED"}

    def human_approval(state: ContractState) -> ContractState:
        decision=interrupt({"kind":"contract_recommendation",
          "recommendation":state["recommendation"],"contract_id":state.get("contract_id"),
          "partner_id":state.get("partner_id"),
          "allowed_decisions":["APPROVED","REJECTED","MODIFIED"]})
        normalized=str(decision.get("decision","")).upper()
        if normalized not in {"APPROVED","REJECTED","MODIFIED"}:
            raise ValueError("Resume requires APPROVED, REJECTED or MODIFIED decision")
        status={"APPROVED":"APPROVED","REJECTED":"REJECTED","MODIFIED":"REVISION_REQUIRED"}[normalized]
        return {"approval_decision":decision,"status":status}

    graph=StateGraph(ContractState)
    graph.add_node("retrieve_contract",retrieve_contract)
    graph.add_node("retrieve_business_context",retrieve_business_context)
    graph.add_node("analyze_and_recommend",analyze)
    graph.add_node("human_approval",human_approval)
    graph.add_edge(START,"retrieve_contract")
    graph.add_conditional_edges("retrieve_contract",route_evidence,
      {"retrieve_business":"retrieve_business_context","finish":END})
    graph.add_edge("retrieve_business_context","analyze_and_recommend")
    graph.add_edge("analyze_and_recommend","human_approval")
    graph.add_edge("human_approval",END)
    return graph.compile(checkpointer=checkpointer)

@contextmanager
def sqlite_checkpointer(path: str):
    """Local development checkpoint store; use a shared backend for multi-instance production."""
    try:
        from langgraph.checkpoint.sqlite import SqliteSaver
    except ImportError as exc:
        raise RuntimeError("Install optional dependencies: pip install -e '.[agent]'") from exc
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    with SqliteSaver.from_conn_string(path) as saver:
        yield saver

def start_contract_workflow(question: str,thread_id: str,contract_id: str|None=None,
                            partner_id: str|None=None,checkpointer: Any|None=None) -> dict:
    if checkpointer is None:
        raise ValueError("A persistent checkpointer is required for resumable workflows")
    graph=build_contract_graph(checkpointer)
    return graph.invoke({"question":question,"contract_id":contract_id,"partner_id":partner_id},
                         config={"configurable":{"thread_id":thread_id}})

def resume_contract_workflow(thread_id: str,decision: str,reviewer: str,reason: str,
                             checkpointer: Any,modified_payload: dict[str,Any]|None=None) -> dict:
    try:
        from langgraph.types import Command
    except ImportError as exc:
        raise RuntimeError("Install optional dependencies: pip install -e '.[agent]'") from exc
    if decision.upper() not in {"APPROVED","REJECTED","MODIFIED"}:
        raise ValueError("Unsupported approval decision")
    if not reviewer.strip() or not reason.strip():
        raise ValueError("Reviewer identity and reason are required")
    graph=build_contract_graph(checkpointer)
    return graph.invoke(Command(resume={"decision":decision.upper(),"reviewer":reviewer,
      "reason":reason,"modified_payload":modified_payload}),
      config={"configurable":{"thread_id":thread_id}})
