"""Workflow orchestration APIs.

Contract Intelligence is imported directly. The older recommendation workflow
is loaded lazily so its legacy SQLite checkpointer is not imported by ingestion.
"""
from importlib import import_module

from .contract_intelligence_workflow import (
    ContractIntelligenceWorkflowState,
    build_contract_intelligence_graph,
    get_contract_intelligence_workflow_status,
    list_contract_intelligence_workflow_events,
    resume_contract_intelligence_workflow,
    start_contract_intelligence_workflow,
)

__all__ = [
    "ContractIntelligenceWorkflowState",
    "build_contract_intelligence_graph",
    "get_contract_intelligence_workflow_status",
    "list_contract_intelligence_workflow_events",
    "resume_contract_intelligence_workflow",
    "start_contract_intelligence_workflow",
    "ContractState",
    "build_contract_graph",
    "get_workflow_status",
    "list_workflow_events",
    "resume_contract_workflow",
    "sqlite_checkpointer",
    "start_contract_workflow",
]

_LEGACY_RECOMMENDATION_EXPORTS = {
    "ContractState",
    "build_contract_graph",
    "get_workflow_status",
    "list_workflow_events",
    "resume_contract_workflow",
    "sqlite_checkpointer",
    "start_contract_workflow",
}


def __getattr__(name: str):
    if name in _LEGACY_RECOMMENDATION_EXPORTS:
        module = import_module(".contract_recommendation", __name__)
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
