"""Individual node implementations for the triage workflow."""

from datetime import datetime

from agents.intake_agent import IntakeAgent
from agents.classifier_agent import ClassifierAgent
from agents.router_agent import RouterAgent
from agents.auditor_agent import AuditorAgent
from workflows.state import TriageState, ApprovalStatus


# Singleton agent instances
intake_agent = IntakeAgent()
classifier_agent = ClassifierAgent()
router_agent = RouterAgent()
auditor_agent = AuditorAgent()


async def intake_node(state: TriageState) -> TriageState:
    """
    Intake node: Parse document, normalize, detect and redact PII.

    Updates:
    - document_content_redacted: PII-redacted version
    - pii_detection: Detection metadata
    - error: Any processing errors
    """
    try:
        # Normalize document content
        normalized_content = intake_agent.normalize_document(state["document_content"])

        # Detect and redact PII
        redacted_content, pii_detection = intake_agent.process_document(
            state["document_id"], normalized_content
        )

        # Log intake event
        auditor_agent.log_event(
            agent="intake_agent",
            action="process_document",
            outcome="success",
            metadata={
                "document_id": state["document_id"],
                "content_length": len(normalized_content),
                "has_pii": pii_detection["has_pii"],
                "entity_count": pii_detection["entity_count"],
            },
        )

        return {
            **state,
            "document_content_redacted": redacted_content,
            "pii_detection": pii_detection,
            "error": None,
        }
    except Exception as e:
        auditor_agent.log_error(state["document_id"], "intake_agent", str(e))
        return {
            **state,
            "error": f"Intake processing failed: {str(e)}",
            "retry_count": state["retry_count"] + 1,
        }


async def classify_node(state: TriageState) -> TriageState:
    """
    Classify node: Use Bedrock to classify document type, sensitivity, urgency.

    Updates:
    - classification: Classification result from Bedrock
    - error: Any classification errors
    """
    try:
        classification = classifier_agent.classify_document(
            document_id=state["document_id"],
            content=state["document_content"],
            redacted_content=state["document_content_redacted"],
        )

        # Log classification event
        auditor_agent.log_classification(
            document_id=state["document_id"],
            document_type=classification["document_type"].value,
            confidence_score=classification["confidence_score"],
        )

        return {
            **state,
            "classification": classification,
            "error": None,
        }
    except Exception as e:
        auditor_agent.log_error(state["document_id"], "classifier_agent", str(e))
        return {
            **state,
            "error": f"Classification failed: {str(e)}",
            "retry_count": state["retry_count"] + 1,
        }


async def route_node(state: TriageState) -> TriageState:
    """
    Route node: Determine primary queue, backup queue, reviewer, and SLA.

    Updates:
    - routing: Routing decision with queue and SLA
    - error: Any routing errors
    """
    try:
        if not state["classification"]:
            raise ValueError("No classification available for routing")

        routing = router_agent.route_document(
            document_id=state["document_id"],
            classification=state["classification"],
        )

        # Log routing event
        auditor_agent.log_routing(
            document_id=state["document_id"],
            primary_queue=routing["primary_queue"].value,
            backup_queue=routing["backup_queue"].value if routing["backup_queue"] else None,
            sla_deadline=routing["sla_deadline"],
        )

        return {
            **state,
            "routing": routing,
            "error": None,
        }
    except Exception as e:
        auditor_agent.log_error(state["document_id"], "router_agent", str(e))
        return {
            **state,
            "error": f"Routing failed: {str(e)}",
            "retry_count": state["retry_count"] + 1,
        }


async def approval_node(state: TriageState) -> TriageState:
    """
    Approval node: Wait for human review and decision.

    In production, this would integrate with Step Functions to wait for
    SNS notification of approval decision. For now, returns PENDING state.

    Updates:
    - approval_status: Updated to IN_REVIEW
    - approval_reviewer: Assigned reviewer
    """
    try:
        # In production, this would:
        # 1. Send SNS notification to reviewer
        # 2. Wait for approval decision callback via API Gateway
        # 3. Update state with approval_reviewer, approval_timestamp, approval_notes

        # For now, mark as IN_REVIEW
        return {
            **state,
            "approval_status": ApprovalStatus.IN_REVIEW,
            "approval_reviewer": state["routing"]["primary_reviewer_id"] if state["routing"] else None,
            "error": None,
        }
    except Exception as e:
        auditor_agent.log_error(state["document_id"], "approval_agent", str(e))
        return {
            **state,
            "error": f"Approval initiation failed: {str(e)}",
            "retry_count": state["retry_count"] + 1,
        }


async def escalation_node(state: TriageState) -> TriageState:
    """
    Escalation node: Check for SLA breaches and escalate if overdue.

    Updates:
    - escalation_count: Incremented if escalated
    - approval_status: Updated to ESCALATED if overdue
    """
    try:
        if not state["routing"]:
            return state

        sla_deadline = datetime.fromisoformat(state["routing"]["sla_deadline"])
        now = datetime.utcnow()

        if now > sla_deadline:
            auditor_agent.log_escalation(
                document_id=state["document_id"],
                reason="SLA deadline exceeded",
                escalated_to=state["routing"]["backup_reviewer_id"] or "escalation_queue",
            )

            return {
                **state,
                "approval_status": ApprovalStatus.ESCALATED,
                "escalation_count": state["escalation_count"] + 1,
            }

        return state
    except Exception as e:
        auditor_agent.log_error(state["document_id"], "escalation_agent", str(e))
        return {
            **state,
            "error": f"Escalation check failed: {str(e)}",
        }


async def audit_node(state: TriageState) -> TriageState:
    """
    Audit node: Log all decisions and update processing state.

    Updates:
    - processing_complete: Mark workflow as complete
    - audit_trail: Store all audit events
    """
    try:
        # Store audit trail
        audit_trail = [
            {
                "event_id": event["event_id"],
                "timestamp": event["timestamp"],
                "event_type": event["event_type"],
                "agent": event["agent"],
                "action": event["action"],
                "outcome": event["outcome"],
                "metadata": event["metadata"],
            }
            for event in auditor_agent.get_audit_trail()
        ]

        # Final logging
        auditor_agent.log_event(
            agent="audit_agent",
            action="finalize_workflow",
            outcome="success",
            metadata={
                "document_id": state["document_id"],
                "approval_status": state["approval_status"].value,
                "event_count": len(audit_trail),
            },
        )

        return {
            **state,
            "audit_trail": audit_trail,
            "processing_complete": True,
            "error": None,
        }
    except Exception as e:
        return {
            **state,
            "error": f"Audit finalization failed: {str(e)}",
        }
