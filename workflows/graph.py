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

    # Define conditional edges for error retry and normal flow
    def intake_router(state):
        """Route from intake: retry on error or proceed to classify."""
        max_retries = 3
        if state.get("error") and state.get("retry_count", 0) < max_retries:
            return "intake"
        else:
            return "classify"

    def classify_router(state):
        """Route from classify: retry on error or proceed to route."""
        max_retries = 3
        if state.get("error") and state.get("retry_count", 0) < max_retries:
            return "classify"
        else:
            return "route"

    def route_router(state):
        """Route from route: retry on error or proceed to approval."""
        max_retries = 3
        if state.get("error") and state.get("retry_count", 0) < max_retries:
            return "route"
        else:
            return "approval"

    # Add conditional edges with retry logic
    graph.add_conditional_edges(
        "intake",
        intake_router,
    )
    graph.add_conditional_edges(
        "classify",
        classify_router,
    )
    graph.add_conditional_edges(
        "route",
        route_router,
    )

    # Approval can go to escalation (for IN_REVIEW) or audit (for APPROVED/REJECTED)
    def approval_routing(state):
        """Route based on approval status.

        - IN_REVIEW documents go to escalation for SLA monitoring
        - APPROVED, REJECTED, DELEGATED documents go directly to audit
        """
        if state["approval_status"] == ApprovalStatus.IN_REVIEW:
            return "escalation"
        else:
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
