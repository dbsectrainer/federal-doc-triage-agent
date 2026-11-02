"""Individual node implementations for the triage workflow."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

from agents.classifier_agent import ClassifierAgent
from agents.intake_agent import IntakeAgent
from agents.router_agent import RouterAgent
from workflows.audit_context import get_auditor
from workflows.state import (
    ApprovalStatus,
    SensitivityLevel,
    TriageState,
)

logger = logging.getLogger(__name__)

# Agent instances are stateless apart from the auditor, which is scoped per
# workflow invocation in ``workflows.audit_context``.
intake_agent = IntakeAgent()
classifier_agent = ClassifierAgent()
router_agent = RouterAgent()

# Only unclassified documents may be processed without a human decision.
SENSITIVE_LEVELS = {
    SensitivityLevel.CONTROLLED_UNCLASSIFIED,
    SensitivityLevel.SENSITIVE_BUT_UNCLASSIFIED,
    SensitivityLevel.FOR_OFFICIAL_USE_ONLY,
}

DEFAULT_AUTO_APPROVAL_CONFIDENCE = 0.85


def _demo_mode() -> bool:
    return os.environ.get("DEMO_MODE", "").lower() in ("true", "1", "yes")


def _auto_approval_threshold() -> float:
    raw = os.environ.get(
        "AUTO_APPROVAL_CONFIDENCE_THRESHOLD", str(DEFAULT_AUTO_APPROVAL_CONFIDENCE)
    )
    try:
        value = float(raw)
    except ValueError:
        logger.warning(
            "Invalid AUTO_APPROVAL_CONFIDENCE_THRESHOLD=%r; using %.2f",
            raw,
            DEFAULT_AUTO_APPROVAL_CONFIDENCE,
        )
        return DEFAULT_AUTO_APPROVAL_CONFIDENCE
    return min(max(value, 0.0), 1.0)


async def intake_node(state: TriageState) -> TriageState:
    """
    Intake node: Parse document, normalize, detect and redact PII.

    Updates:
    - document_content_redacted: PII-redacted version
    - pii_detection: Detection metadata
    - error: Any processing errors
    """
    auditor = get_auditor()
    try:
        # Normalize document content
        normalized_content = intake_agent.normalize_document(state["document_content"])

        # Detect and redact PII
        redacted_content, pii_detection = intake_agent.process_document(
            state["document_id"], normalized_content
        )

        # Log intake event
        auditor.log_event(
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
            "retry_count": 0,
        }
    except Exception as exc:
        auditor.log_error(state["document_id"], "intake_agent", str(exc))
        return {
            **state,
            "error": f"Intake processing failed: {exc}",
            "retry_count": state["retry_count"] + 1,
        }


async def classify_node(state: TriageState) -> TriageState:
    """
    Classify node: Use Bedrock to classify document type, sensitivity, urgency.

    Updates:
    - classification: Classification result from Bedrock
    - error: Any classification errors
    """
    auditor = get_auditor()
    try:
        classification = classifier_agent.classify_document(
            document_id=state["document_id"],
            content=state["document_content"],
            redacted_content=state["document_content_redacted"],
        )

        # Log classification event
        auditor.log_classification(
            document_id=state["document_id"],
            document_type=classification["document_type"].value,
            confidence_score=classification["confidence_score"],
        )

        return {
            **state,
            "classification": classification,
            "error": None,
            "retry_count": 0,
        }
    except Exception as exc:
        auditor.log_error(state["document_id"], "classifier_agent", str(exc))
        return {
            **state,
            "error": f"Classification failed: {exc}",
            "retry_count": state["retry_count"] + 1,
        }


async def route_node(state: TriageState) -> TriageState:
    """
    Route node: Determine primary queue, backup queue, reviewer, and SLA.

    Updates:
    - routing: Routing decision with queue and SLA
    - error: Any routing errors
    """
    auditor = get_auditor()
    try:
        if not state["classification"]:
            raise ValueError("No classification available for routing")

        routing = router_agent.route_document(
            document_id=state["document_id"],
            classification=state["classification"],
        )

        # Log routing event
        auditor.log_routing(
            document_id=state["document_id"],
            primary_queue=routing["primary_queue"].value,
            backup_queue=routing["backup_queue"].value if routing["backup_queue"] else None,
            sla_deadline=routing["sla_deadline"],
        )

        return {
            **state,
            "routing": routing,
            "error": None,
            "retry_count": 0,
        }
    except Exception as exc:
        auditor.log_error(state["document_id"], "router_agent", str(exc))
        return {
            **state,
            "error": f"Routing failed: {exc}",
            "retry_count": state["retry_count"] + 1,
        }


async def approval_node(state: TriageState) -> TriageState:
    """
    Approval node: auto-approve only high-confidence *unclassified* documents.

    Sensitive documents (CUI, SBU, FOUO) always require a human decision,
    regardless of the classifier's confidence.  This is deliberately stricter
    than a confidence-only threshold: a misclassification must not be able to
    auto-approve a controlled document.

    Updates:
    - approval_status: APPROVED for eligible documents, otherwise IN_REVIEW
    - approval_reviewer: Assigned reviewer
    - approval_timestamp: Set if auto-approved
    """
    auditor = get_auditor()
    try:
        if not state["classification"]:
            raise ValueError("No classification available for approval")

        classification = state["classification"]
        confidence = float(classification["confidence_score"])
        try:
            sensitivity = SensitivityLevel(classification["sensitivity_level"])
        except (ValueError, TypeError):
            # Unknown sensitivity is treated as controlled: never auto-approve.
            sensitivity = SensitivityLevel.CONTROLLED_UNCLASSIFIED
        is_sensitive = sensitivity in SENSITIVE_LEVELS
        threshold = _auto_approval_threshold()

        # Auto-approve only unclassified documents with high confidence.
        if not is_sensitive and confidence > threshold:
            approval_timestamp = datetime.now(timezone.utc).isoformat()
            auditor.log_approval_decision(
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
                "retry_count": 0,
            }

        # Everything else needs a human reviewer.
        reviewer = state["routing"]["primary_reviewer_id"] if state["routing"] else None
        reason = (
            f"sensitivity {sensitivity.value} requires human review"
            if is_sensitive
            else f"confidence {confidence:.2f} does not exceed {threshold:.2f}"
        )
        auditor.log_event(
            agent="approval_agent",
            action="require_human_review",
            outcome="pending",
            metadata={
                "document_id": state["document_id"],
                "reviewer_id": reviewer,
                "reason": reason,
                "confidence_score": confidence,
                "sensitivity_level": sensitivity.value,
            },
        )
        return {
            **state,
            "approval_status": ApprovalStatus.IN_REVIEW,
            "approval_reviewer": reviewer,
            "approval_notes": f"Human review required: {reason}",
            "error": None,
            "retry_count": 0,
        }
    except Exception as exc:
        auditor.log_error(state["document_id"], "approval_agent", str(exc))
        return {
            **state,
            "error": f"Approval initiation failed: {exc}",
            "retry_count": state["retry_count"] + 1,
        }


async def escalation_node(state: TriageState) -> TriageState:
    """
    Escalation node: Check for SLA breaches and escalate if overdue.

    NOTE: A single workflow run creates the SLA deadline immediately before
    this check, so it only escalates if the deadline was restored from a
    previous run (for example from DynamoDB).  The current implementation does
    not persist/reload workflow state between runs; multi-run SLA tracking is
    tracked in ROADMAP.md.

    Updates:
    - escalation_count: Incremented if escalated
    - approval_status: Updated to ESCALATED if overdue
    """
    auditor = get_auditor()
    try:
        if not state["routing"]:
            return state

        sla_deadline = datetime.fromisoformat(state["routing"]["sla_deadline"])
        now = datetime.now(timezone.utc)
        if sla_deadline.tzinfo is None:
            sla_deadline = sla_deadline.replace(tzinfo=timezone.utc)
        grace_period_hours = 1

        # Check if current time exceeds deadline + grace period
        escalation_threshold = sla_deadline + timedelta(hours=grace_period_hours)

        if now > escalation_threshold:
            auditor.log_escalation(
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
    except Exception as exc:
        auditor.log_error(state["document_id"], "escalation_agent", str(exc))
        return {
            **state,
            "error": f"Escalation check failed: {exc}",
        }


async def audit_node(state: TriageState) -> TriageState:
    """
    Audit node: persist the audit trail, then finalize the workflow.

    In DEMO_MODE the trail is returned in state but not written to DynamoDB.
    In production a failed persistence attempt is a workflow failure: the
    document is not marked complete because its compliance record is missing.

    Updates:
    - processing_complete: True only when no error occurred and the audit
      record was either persisted or intentionally kept in memory for a demo
    - audit_trail: Complete audit events for this document only
    - audit_persisted: Whether DynamoDB accepted the events
    - error: Prior error is preserved; persistence errors are added
    """
    auditor = get_auditor()
    prior_error = state.get("error")
    events_before_finalization = len(auditor.get_audit_trail())
    approval_status = state["approval_status"]
    approval_status_value = getattr(approval_status, "value", str(approval_status))

    auditor.log_event(
        agent="audit_agent",
        action="finalize_workflow",
        outcome="failure" if prior_error else "success",
        metadata={
            "document_id": state["document_id"],
            "approval_status": approval_status_value,
            "event_count": events_before_finalization,
            "workflow_error": prior_error,
        },
    )

    demo_mode = _demo_mode()
    if demo_mode:
        persistence_success = False
        persistence_mode = "in_memory_demo"
    else:
        table_name = os.environ.get(
            "AUDIT_DYNAMODB_TABLE",
            os.environ.get("AUDIT_TABLE_NAME", "document-triage-audit"),
        )
        persistence_success = auditor.persist_to_dynamodb(table_name)
        persistence_mode = "dynamodb"
        if not persistence_success:
            logger.error(
                "Failed to persist audit trail to DynamoDB table '%s'", table_name
            )

    audit_trail = list(auditor.get_audit_trail())
    auditor.clear_audit_trail()

    error = prior_error
    if not demo_mode and not persistence_success:
        persistence_error = "Audit persistence failed: audit trail was not written to DynamoDB"
        error = f"{prior_error}; {persistence_error}" if prior_error else persistence_error

    return {
        **state,
        "audit_trail": audit_trail,
        "processing_complete": error is None,
        "audit_persisted": persistence_success,
        "audit_persistence_mode": persistence_mode,
        "error": error,
    }
