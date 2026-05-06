"""Auditor agent for compliance logging and audit trail."""

import json
import uuid
from datetime import datetime
from typing import Any, Dict

from workflows.state import AuditEvent


class AuditorAgent:
    """Handles compliance logging and audit trail creation for FISMA/FedRAMP."""

    def __init__(self):
        self.audit_events = []

    def log_event(
        self,
        agent: str,
        action: str,
        outcome: str,
        metadata: Dict[str, Any] = None,
    ) -> AuditEvent:
        """
        Log an audit event for compliance tracking.

        Args:
            agent: Agent that performed the action (classifier, router, approval_worker)
            action: Action performed (classify, route, approve, reject, escalate)
            outcome: Outcome of action (success, failure, partial)
            metadata: Additional context (document details, decisions, etc.)

        Returns:
            AuditEvent record
        """
        event = AuditEvent(
            event_id=str(uuid.uuid4()),
            timestamp=datetime.utcnow().isoformat(),
            event_type="WORKFLOW_ACTION",
            agent=agent,
            action=action,
            outcome=outcome,
            metadata=metadata or {},
        )

        self.audit_events.append(event)
        return event

    def log_pii_detection(
        self, document_id: str, entity_types: list, entity_count: int
    ) -> AuditEvent:
        """Log PII detection event."""
        return self.log_event(
            agent="intake_agent",
            action="detect_pii",
            outcome="success",
            metadata={
                "document_id": document_id,
                "entity_types": entity_types,
                "entity_count": entity_count,
                "redaction_applied": True,
            },
        )

    def log_classification(
        self, document_id: str, document_type: str, confidence_score: float
    ) -> AuditEvent:
        """Log document classification event."""
        return self.log_event(
            agent="classifier_agent",
            action="classify_document",
            outcome="success",
            metadata={
                "document_id": document_id,
                "document_type": document_type,
                "confidence_score": confidence_score,
            },
        )

    def log_routing(
        self,
        document_id: str,
        primary_queue: str,
        backup_queue: str,
        sla_deadline: str,
    ) -> AuditEvent:
        """Log document routing event."""
        return self.log_event(
            agent="router_agent",
            action="route_document",
            outcome="success",
            metadata={
                "document_id": document_id,
                "primary_queue": primary_queue,
                "backup_queue": backup_queue,
                "sla_deadline": sla_deadline,
            },
        )

    def log_approval_decision(
        self,
        document_id: str,
        reviewer_id: str,
        decision: str,
        notes: str = None,
    ) -> AuditEvent:
        """Log approval decision event."""
        return self.log_event(
            agent="approval_worker",
            action="approve_document",
            outcome="success",
            metadata={
                "document_id": document_id,
                "reviewer_id": reviewer_id,
                "decision": decision,  # approved, rejected, delegated
                "notes": notes,
            },
        )

    def log_escalation(
        self, document_id: str, reason: str, escalated_to: str
    ) -> AuditEvent:
        """Log escalation event (SLA breach, stalled approval)."""
        return self.log_event(
            agent="escalation_worker",
            action="escalate_document",
            outcome="escalation_triggered",
            metadata={
                "document_id": document_id,
                "reason": reason,
                "escalated_to": escalated_to,
            },
        )

    def log_error(
        self, document_id: str, agent: str, error_message: str
    ) -> AuditEvent:
        """Log processing error event."""
        return self.log_event(
            agent=agent,
            action="process_error",
            outcome="failure",
            metadata={
                "document_id": document_id,
                "error_message": error_message,
            },
        )

    def get_audit_trail(self) -> list[AuditEvent]:
        """Get all audit events logged in this session."""
        return self.audit_events

    def export_audit_trail_json(self) -> str:
        """Export audit trail as JSON for CloudTrail / DynamoDB storage."""
        return json.dumps(self.audit_events, default=str, indent=2)

    def clear_audit_trail(self):
        """Clear in-memory audit trail (should be persisted before clearing)."""
        self.audit_events = []
