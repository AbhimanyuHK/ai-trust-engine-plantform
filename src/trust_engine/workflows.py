"""LangGraph contract workflow with interrupt/resume and durable checkpoints."""
from __future__ import annotations
from contextlib import contextmanager
from pathlib import Path
from typing import Any, TypedDict
from trust_engine.cortex import grounded_contract_answer

class ContractState(TypedDict,total=False):
    question: str
    contract_id: str
    partner_id: str
    evidence: dict[str,Any]
    recommendation: dict[str,Any]
    approval_decision: dict[str,Any]
    status: str

def build_contract_graph(checkpointer: Any | None = None) -> Any:
    try:
        from langgraph.graph import END,START,StateGraph
        from langgraph.types import interrupt
    except ImportError as exc:
        raise RuntimeError("Install optional dependencies: pip install -e '.[agent]'") from exc

    def retrieve(state: ContractState) -> ContractState:
        evidence=grounded_contract_answer(state["question"],contract_id=state.get("contract_id"),
                                          partner_id=state.get("partner_id"))
        return {"evidence":evidence,"status":"RETRIEVED"}

    def route(state: ContractState) -> str:
        return "recommend" if state.get("evidence",{}).get("grounded") else "finish"

    def recommend(state: ContractState) -> ContractState:
        return {"recommendation":{"text":state["evidence"]["answer"],
          "citations":state["evidence"]["citations"],"requires_human_review":True},
          "status":"AWAITING_HUMAN_APPROVAL"}

    def human_approval(state: ContractState) -> ContractState:
        # interrupt() persists graph state; no model execution continues while a reviewer is away.
        decision=interrupt({"kind":"contract_recommendation",
          "recommendation":state["recommendation"],"contract_id":state.get("contract_id"),
          "partner_id":state.get("partner_id"),"allowed_decisions":["APPROVED","REJECTED","MODIFIED"]})
        normalized=str(decision.get("decision","")).upper()
        if normalized not in {"APPROVED","REJECTED","MODIFIED"}:
            raise ValueError("Resume requires APPROVED, REJECTED or MODIFIED decision")
        return {"approval_decision":decision,
                "status":{"APPROVED":"APPROVED","REJECTED":"REJECTED","MODIFIED":"REVISION_REQUIRED"}[normalized]}

    graph=StateGraph(ContractState)
    graph.add_node("retrieve_contract",retrieve)
    graph.add_node("generate_recommendation",recommend)
    graph.add_node("human_approval",human_approval)
    graph.add_edge(START,"retrieve_contract")
    graph.add_conditional_edges("retrieve_contract",route,{"recommend":"generate_recommendation","finish":END})
    graph.add_edge("generate_recommendation","human_approval")
    graph.add_edge("human_approval",END)
    return graph.compile(checkpointer=checkpointer)

@contextmanager
def sqlite_checkpointer(path: str):
    """Open a local development checkpointer; production should use a shared durable backend."""
    try:
        from langgraph.checkpoint.sqlite import SqliteSaver
    except ImportError as exc:
        raise RuntimeError("Install optional dependencies: pip install -e '.[agent]'") from exc
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    with SqliteSaver.from_conn_string(path) as saver:
        yield saver

def start_contract_workflow(question: str, thread_id: str, contract_id: str | None = None,
                            partner_id: str | None = None, checkpointer: Any | None = None) -> dict:
    if checkpointer is None:
        raise ValueError("A persistent checkpointer is required for resumable workflows")
    graph=build_contract_graph(checkpointer)
    return graph.invoke({"question":question,"contract_id":contract_id,"partner_id":partner_id},
                         config={"configurable":{"thread_id":thread_id}})

def resume_contract_workflow(thread_id: str, decision: str, reviewer: str, reason: str,
                             checkpointer: Any, modified_payload: dict[str,Any] | None = None) -> dict:
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
