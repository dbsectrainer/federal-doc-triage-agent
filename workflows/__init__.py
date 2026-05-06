"""Workflow package for LangGraph orchestration."""

from workflows.state import (
    DocumentType,
    SensitivityLevel,
    Urgency,
    ApprovalStatus,
    RoutingQueue,
    TriageState,
    initial_state,
)

def __getattr__(name):
    """Lazy import create_workflow to avoid circular imports."""
    if name == "create_workflow":
        from workflows.graph import create_workflow
        return create_workflow
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "DocumentType",
    "SensitivityLevel",
    "Urgency",
    "ApprovalStatus",
    "RoutingQueue",
    "TriageState",
    "initial_state",
    "create_workflow",
]
