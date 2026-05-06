"""Individual node implementations for the triage workflow."""

import os
import logging
from datetime import datetime, timezone

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
    Approval node: Auto-approve high-confidence docs, mark others for review.

    Auto-approval heuristic: If classification confidence > 0.85, auto-approve.
    Otherwise, mark as IN_REVIEW to await human decision.

    In production, IN_REVIEW documents would integrate with Step Functions to wait
    for SNS notification of approval decision.

    Updates:
    - approval_status: APPROVED if confidence > 0.85, else IN_REVIEW
    - approval_reviewer: Assigned reviewer
    - approval_timestamp: Set if auto-approved
    """
    try:
        if not state["classification"]:
            raise ValueError("No classification available for approval")

        confidence = state["classification"]["confidence_score"]

        # Auto-approve high-confidence documents
        if confidence > 0.85:
            approval_timestamp = datetime.now(timezone.utc).isoformat()
            auditor_agent.log_approval_decision(
                document_id=state["document_id"],
                reviewer_id="auto-approval-bot",
                decision="approved",
                notes=f"Auto-approved based on confidence score: {confidence:.2f}",
            )
            return {
                **state,
                "approval_status": ApprovalStatus.APPROVED,
                "approval_reviewer": "auto-approval-bot",
                "approval_timestamp": approval_timestamp,
                "approval_notes": f"Auto-approved (confidence: {confidence:.2f})",
                "error": None,
            }
        else:
            # Low-confidence documents require human review
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

    NOTE: SLA check with 1-hour grace period to allow buffer before escalation.
    TODO: Multi-run SLA check requires state persistence across invocations.
    Current implementation only works for single-run workflows. For production,
    implement SLA tracking in DynamoDB to check against deadline from routing,
    not just when this node executes.

    Updates:
    - escalation_count: Incremented if escalated
    - approval_status: Updated to ESCALATED if overdue
    """
    try:
        if not state["routing"]:
            return state

        sla_deadline = datetime.fromisoformat(state["routing"]["sla_deadline"])
        now = datetime.now(timezone.utc)
        grace_period_hours = 1

        # Check if current time exceeds deadline + grace period
        from datetime import timedelta
        escalation_threshold = sla_deadline + timedelta(hours=grace_period_hours)

        if now > escalation_threshold:
            auditor_agent.log_escalation(
                document_id=state["document_id"],
                reason=f"SLA deadline exceeded (with {grace_period_hours}h grace period)",
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
    Audit node: Persist audit trail and finalize workflow.

    Attempts to persist all audit events to DynamoDB for compliance tracking.
    If persistence fails, audit trail is still returned in state for fallback handling.

    Updates:
    - processing_complete: Mark workflow as complete
    - audit_trail: Store all audit events
    - error: Any persistence errors (non-fatal)
    """
    try:
        # Get current audit trail
        events = auditor_agent.get_audit_trail()

        # Log finalization event
        auditor_agent.log_event(
            agent="audit_agent",
            action="finalize_workflow",
            outcome="success",
            metadata={
                "document_id": state["document_id"],
                "approval_status": state["approval_status"].value,
                "event_count": len(events),
            },
        )

        # Attempt to persist to DynamoDB (non-blocking)
        table_name = os.environ.get("AUDIT_TABLE_NAME", "federal-doc-triage-audit-trail")
        persistence_success = auditor_agent.persist_to_dynamodb(table_name)

        if not persistence_success:
            logging.warning(f"Failed to persist audit trail to DynamoDB table '{table_name}'")

        # Build audit trail for state
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

        # Clear in-memory trail after persistence
        auditor_agent.clear_audit_trail()

        return {
            **state,
            "audit_trail": audit_trail,
            "processing_complete": True,
            "audit_persisted": persistence_success,
            "error": None,
        }
    except Exception as e:
        return {
            **state,
            "error": f"Audit finalization failed: {str(e)}",
        }
