"""LangGraph workflow definition for federal document triage."""

from langgraph.graph import END, StateGraph

from workflows.nodes import (
    approval_node,
    audit_node,
    classify_node,
    escalation_node,
    intake_node,
    route_node,
)
from workflows.state import ApprovalStatus, TriageState

MAX_NODE_RETRIES = 3


def _retry_or_continue(state: TriageState, node: str, next_node: str) -> str:
    """Retry the failed node, or stop the pipeline when retries are exhausted."""
    if state.get("error"):
        if state.get("retry_count", 0) <= MAX_NODE_RETRIES:
            return node
        return "audit"
    return next_node


def build_triage_graph():
    """
    Build the LangGraph workflow for document triage.

    Workflow:
    1. Intake: Parse document, detect & redact PII
    2. Classify: Determine document type, sensitivity, urgency
    3. Route: Assign to appropriate queue and reviewer
    4. Approval: Auto-approve eligible documents or require human review
    5. Escalation: Check SLA (no-op within a single run)
    6. Audit: Persist the audit trail and finalize the workflow

    Each processing node may be retried up to ``MAX_NODE_RETRIES`` times
    (four total attempts).  When the retry budget is exhausted the graph goes
    directly to audit, preserving the error and marking the workflow incomplete
    instead of processing empty or partially populated state.
    """

    graph = StateGraph(TriageState)

    # Add nodes
    graph.add_node("intake", intake_node)
    graph.add_node("classify", classify_node)
    graph.add_node("route", route_node)
    graph.add_node("approval", approval_node)
    graph.add_node("escalation", escalation_node)
    graph.add_node("audit", audit_node)

    # Conditional edges implement per-node retries and failure short-circuiting.
    graph.add_conditional_edges(
        "intake",
        lambda state: _retry_or_continue(state, "intake", "classify"),
    )
    graph.add_conditional_edges(
        "classify",
        lambda state: _retry_or_continue(state, "classify", "route"),
    )
    graph.add_conditional_edges(
        "route",
        lambda state: _retry_or_continue(state, "route", "approval"),
    )

    # Approval goes to escalation for IN_REVIEW documents or audit otherwise.
    def approval_routing(state: TriageState) -> str:
        if state.get("error"):
            return "audit"
        if state["approval_status"] == ApprovalStatus.IN_REVIEW:
            return "escalation"
        return "audit"

    graph.add_conditional_edges(
        "approval",
        approval_routing,
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
