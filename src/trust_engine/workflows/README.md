# Workflows

Owns cross-domain orchestration, not underlying business capabilities. Coordinates
Contract Intelligence retrieval, structured transaction/forecast context,
recommendations, human approval interrupts and durable resume.

## Durable execution model

The LangGraph SQLite checkpointer and the workflow registry share the configured
`trust_checkpoint_db` file (default `.trust/checkpoints.sqlite`). The checkpointer
stores graph state and pending interrupts; the registry stores queryable lifecycle
state and append-only workflow events:

- `workflow_runs`: one row per `thread_id`, current status/step, contract and
  partner references, timestamps and the last error.
- `workflow_events`: append-only start, pause, approval submission, resume,
  completion and failure events with JSON details.

SQLite uses WAL mode, a busy timeout and full synchronous durability. Keep this
file on persistent storage and back it up together with its checkpoint data. SQLite
is suitable for local development or a single-worker deployment with a durable
volume. For multi-instance production, replace it with a shared LangGraph
checkpointer and a transactional shared workflow registry; do not put SQLite on
an arbitrary network filesystem.

## Lifecycle

```text
WORKFLOW_STARTED
      |
      v
    RUNNING
      |
      +---- evidence not grounded ----> COMPLETED
      |
      v
WAITING_FOR_APPROVAL
      |
      v
   RESUMING
      |
      +---- APPROVED -------------> APPROVED
      +---- REJECTED -------------> REJECTED
      +---- MODIFIED -------------> REVISION_REQUIRED
      +---- exception ------------> FAILED
```

A `thread_id` is the idempotency key for one workflow execution. Starting an
existing thread is rejected; callers must resume it or create a new thread. The
same thread ID is supplied to LangGraph on start and resume, so the checkpointer
restores the saved state and continues at the interrupted node rather than
re-running retrieval and recommendation nodes. If the process dies after the
registry records `RESUMING`, the resume API inspects the saved checkpoint before
replaying the decision, preventing duplicate application after a completed resume.

The registry records reviewer identity, decision and reason in the approval
submission event. Protect the SQLite file as sensitive audit data. In a regulated
deployment, use authenticated reviewer identities, authorization checks and
tamper-evident external audit retention; a local SQLite event log alone is not a
compliance control.

## Python API

```python
from trust_engine.workflows import (
    get_workflow_status,
    list_workflow_events,
    resume_contract_workflow,
    sqlite_checkpointer,
    start_contract_workflow,
)
from trust_engine.common.config.settings import Settings

settings = Settings()
with sqlite_checkpointer(settings.trust_checkpoint_db) as checkpointer:
    result = start_contract_workflow(
        question="Summarize the royalty terms and risks",
        thread_id="contract-C1001-review-001",
        contract_id="C1001",
        partner_id="PARTNER_1001",
        checkpointer=checkpointer,
    )

status = get_workflow_status(
    "contract-C1001-review-001", settings.trust_checkpoint_db
)
events = list_workflow_events(
    "contract-C1001-review-001", settings.trust_checkpoint_db
)

# Called later by the authenticated reviewer callback, potentially days later.
if status and status["status"] == "WAITING_FOR_APPROVAL":
    with sqlite_checkpointer(settings.trust_checkpoint_db) as checkpointer:
        result = resume_contract_workflow(
            thread_id="contract-C1001-review-001",
            decision="APPROVED",
            reviewer="authenticated-user-id",
            reason="Reviewed source clauses and supporting evidence",
            checkpointer=checkpointer,
        )
```

The reviewer identity shown above is a placeholder for the authenticated
identity supplied by the API layer; never trust a reviewer name sent without
authentication. The checkpointer context must remain open while invoking or
resuming the graph. For a human approval delay of days or weeks, close the
process after the interrupt is persisted and reopen the same checkpoint store
when the approval callback arrives.

## Ownership boundaries

Workflows call Contract Intelligence and Forecasting through public interfaces.
They do not parse PDFs, create embeddings, train forecasting models, or duplicate
the authoritative approval/contract-term storage. Workflow approval is an
orchestration decision; activation of legal terms still requires the contract
governance and effective-date controls.
