"""LangGraph workflow definition for federal document triage."""

from langgraph.graph import StateGraph, END

from workflows.state import TriageState, ApprovalStatus
from workflows.nodes import (
    intake_node,
    classify_node,
    route_node,
    approval_node,
    escalation_node,
    audit_node,
)


def build_triage_graph():
    """
    Build the LangGraph workflow for document triage.

    Workflow:
    1. Intake: Parse document, detect & redact PII
    2. Classify: Determine document type, sensitivity, urgency
    3. Route: Assign to appropriate queue and reviewer
    4. Approval: Wait for human decision (approve/reject/delegate)
    5. Escalation: Monitor SLA and escalate if overdue
    6. Audit: Log all decisions for compliance
    """

    graph = StateGraph(TriageState)

    # Add nodes
    graph.add_node("intake", intake_node)
    graph.add_node("classify", classify_node)
    graph.add_node("route", route_node)
    graph.add_node("approval", approval_node)
    graph.add_node("escalation", escalation_node)
    graph.add_node("audit", audit_node)

    # Define edges (state transitions)
    graph.add_edge("intake", "classify")
    graph.add_edge("classify", "route")
    graph.add_edge("route", "approval")

    # Approval can go to escalation or audit based on approval status
    graph.add_conditional_edges(
        "approval",
        lambda state: (
            "escalation"
            if state["approval_status"] in (ApprovalStatus.PENDING, ApprovalStatus.IN_REVIEW)
            else "audit"
        ),
    )

    # Escalation always leads to audit
    graph.add_edge("escalation", "audit")

    # Audit is terminal
    graph.add_edge("audit", END)

    # Set entry point
    graph.set_entry_point("intake")

    return graph.compile()


def create_workflow():
    """Create and return the compiled workflow graph."""
    return build_triage_graph()
