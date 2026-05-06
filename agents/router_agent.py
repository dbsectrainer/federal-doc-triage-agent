"""Router agent for rule-based document routing."""

from datetime import datetime, timedelta
from typing import Optional

from workflows.state import (
    DocumentType,
    SensitivityLevel,
    Urgency,
    RoutingQueue,
    RoutingDecision,
    ClassificationResult,
)


class RouterAgent:
    """Rule-based router that assigns documents to appropriate queues and reviewers."""

    # Routing rules: (document_type, sensitivity) -> (primary_queue, backup_queue)
    ROUTING_RULES = {
        (DocumentType.CONTRACT, SensitivityLevel.CONTROLLED_UNCLASSIFIED): (
            RoutingQueue.CONTRACTING_OFFICER,
            RoutingQueue.LEGAL_COUNSEL,
        ),
        (DocumentType.CONTRACT, SensitivityLevel.FOR_OFFICIAL_USE_ONLY): (
            RoutingQueue.CONTRACTING_OFFICER,
            RoutingQueue.LEGAL_COUNSEL,
        ),
        (DocumentType.FOIA, SensitivityLevel.UNCLASSIFIED): (
            RoutingQueue.LEGAL_COUNSEL,
            RoutingQueue.POLICY_OFFICE,
        ),
        (DocumentType.POLICY_MEMO, SensitivityLevel.UNCLASSIFIED): (
            RoutingQueue.POLICY_OFFICE,
            RoutingQueue.CHIEF_OF_STAFF,
        ),
        (DocumentType.POLICY_MEMO, SensitivityLevel.FOR_OFFICIAL_USE_ONLY): (
            RoutingQueue.CHIEF_OF_STAFF,
            RoutingQueue.POLICY_OFFICE,
        ),
        (DocumentType.INCIDENT_REPORT, SensitivityLevel.CONTROLLED_UNCLASSIFIED): (
            RoutingQueue.SECURITY_TEAM,
            RoutingQueue.LEGAL_COUNSEL,
        ),
        (DocumentType.INCIDENT_REPORT, SensitivityLevel.FOR_OFFICIAL_USE_ONLY): (
            RoutingQueue.SECURITY_TEAM,
            RoutingQueue.CHIEF_OF_STAFF,
        ),
        (DocumentType.PERSONNEL_ACTION, SensitivityLevel.CONTROLLED_UNCLASSIFIED): (
            RoutingQueue.HR_OFFICE,
            RoutingQueue.LEGAL_COUNSEL,
        ),
        (DocumentType.FINANCIAL, SensitivityLevel.CONTROLLED_UNCLASSIFIED): (
            RoutingQueue.FINANCE_OFFICE,
            RoutingQueue.CHIEF_OF_STAFF,
        ),
        (DocumentType.EXECUTIVE_CORRESPONDENCE, SensitivityLevel.FOR_OFFICIAL_USE_ONLY): (
            RoutingQueue.CHIEF_OF_STAFF,
            RoutingQueue.POLICY_OFFICE,
        ),
        (DocumentType.LEGAL, SensitivityLevel.CONTROLLED_UNCLASSIFIED): (
            RoutingQueue.LEGAL_COUNSEL,
            RoutingQueue.SECURITY_TEAM,
        ),
        (DocumentType.LEGAL, SensitivityLevel.FOR_OFFICIAL_USE_ONLY): (
            RoutingQueue.LEGAL_COUNSEL,
            RoutingQueue.CHIEF_OF_STAFF,
        ),
    }

    # Default routing for unmatched combinations
    DEFAULT_ROUTING = (RoutingQueue.GENERAL_QUEUE, RoutingQueue.LEGAL_COUNSEL)

    # SLA mapping: Urgency -> days (for ROUTINE/PRIORITY) or hours (for IMMEDIATE/EMERGENCY)
    SLA_MAPPING = {
        Urgency.ROUTINE: timedelta(days=10),
        Urgency.PRIORITY: timedelta(days=5),
        Urgency.IMMEDIATE: timedelta(hours=24),
        Urgency.EMERGENCY: timedelta(hours=4),
    }

    def __init__(self):
        self.routing_rules = self.ROUTING_RULES
        self.sla_mapping = self.SLA_MAPPING

    def route_document(
        self, document_id: str, classification: ClassificationResult
    ) -> RoutingDecision:
        """
        Route a classified document to appropriate queue.

        Args:
            document_id: Document identifier
            classification: Classification result from classifier agent

        Returns:
            RoutingDecision with queue assignment and SLA
        """
        # Look up routing rule
        rule_key = (classification["document_type"], classification["sensitivity_level"])
        primary_queue, backup_queue = self.routing_rules.get(rule_key, self.DEFAULT_ROUTING)

        # Assign reviewers (in production, would query staff directory)
        primary_reviewer_id = self._get_reviewer_for_queue(primary_queue)
        backup_reviewer_id = self._get_reviewer_for_queue(backup_queue)

        # Calculate SLA deadline
        sla_offset = self.sla_mapping.get(classification["urgency"], timedelta(days=10))
        sla_deadline = (datetime.utcnow() + sla_offset).isoformat()

        return RoutingDecision(
            primary_queue=primary_queue,
            backup_queue=backup_queue,
            primary_reviewer_id=primary_reviewer_id,
            backup_reviewer_id=backup_reviewer_id,
            sla_deadline=sla_deadline,
            routing_rationale=f"Routed {classification['document_type'].value} with {classification['sensitivity_level'].value} sensitivity to {primary_queue.value}",
            rule_applied=f"{rule_key[0].value}:{rule_key[1].value}",
        )

    def _get_reviewer_for_queue(self, queue: RoutingQueue) -> str:
        """Assign a reviewer ID for a queue (stub: in production, queries staff directory)."""
        queue_to_reviewer = {
            RoutingQueue.CONTRACTING_OFFICER: "contracting-officer-001",
            RoutingQueue.LEGAL_COUNSEL: "legal-counsel-001",
            RoutingQueue.POLICY_OFFICE: "policy-officer-001",
            RoutingQueue.SECURITY_TEAM: "security-lead-001",
            RoutingQueue.HR_OFFICE: "hr-director-001",
            RoutingQueue.FINANCE_OFFICE: "finance-director-001",
            RoutingQueue.CHIEF_OF_STAFF: "chief-of-staff-001",
            RoutingQueue.GENERAL_QUEUE: "general-queue-001",
        }
        return queue_to_reviewer.get(queue, "unassigned")

    def get_sla_deadline(self, urgency: Urgency) -> str:
        """Get SLA deadline offset from now."""
        sla_offset = self.sla_mapping.get(urgency, timedelta(days=10))
        return (datetime.utcnow() + sla_offset).isoformat()
