"""Optional LangGraph workflow builder with persistent checkpoint support."""
from __future__ import annotations
from typing import Any, TypedDict
from trust_engine.cortex import grounded_contract_answer

class ContractState(TypedDict,total=False):
    question: str
    contract_id: str
    partner_id: str
    recommendation: dict[str,Any]
    evidence: dict[str,Any]
    status: str

def build_contract_graph(checkpointer: Any | None = None) -> Any:
    try:
        from langgraph.graph import END, START, StateGraph
    except ImportError as exc:
        raise RuntimeError("Install optional dependencies: pip install -e '.[agent]'") from exc
    def retrieve(state: ContractState) -> ContractState:
        evidence = grounded_contract_answer(state["question"],contract_id=state.get("contract_id"),
                                            partner_id=state.get("partner_id"))
        return {"evidence":evidence,"status":"RETRIEVED"}
    def route(state: ContractState) -> str:
        return "recommend" if state.get("evidence",{}).get("grounded") else "finish"
    def recommend(state: ContractState) -> ContractState:
        return {"recommendation":{"text":state["evidence"]["answer"],
          "citations":state["evidence"]["citations"],"requires_human_review":True},
          "status":"AWAITING_APPROVAL"}
    graph = StateGraph(ContractState)
    graph.add_node("retrieve_contract",retrieve)
    graph.add_node("generate_recommendation",recommend)
    graph.add_edge(START,"retrieve_contract")
    graph.add_conditional_edges("retrieve_contract",route,{"recommend":"generate_recommendation","finish":END})
    graph.add_edge("generate_recommendation",END)
    return graph.compile(checkpointer=checkpointer)

def sqlite_checkpointer(path: str) -> Any:
    try:
        from langgraph.checkpoint.sqlite import SqliteSaver
    except ImportError as exc:
        raise RuntimeError("Install optional dependencies: pip install -e '.[agent]'") from exc
    from pathlib import Path
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    return SqliteSaver.from_conn_string(path)

def run_contract_workflow(question: str, thread_id: str, contract_id: str | None = None,
                          partner_id: str | None = None, checkpointer: Any | None = None) -> dict:
    if checkpointer is None:
        raise ValueError("A persistent checkpointer is required for resumable workflows")
    return build_contract_graph(checkpointer).invoke(
      {"question":question,"contract_id":contract_id,"partner_id":partner_id},
      config={"configurable":{"thread_id":thread_id}})
