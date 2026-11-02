"""Router agent for rule-based document routing."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from workflows.state import (
    ClassificationResult,
    DocumentType,
    RoutingDecision,
    RoutingQueue,
    SensitivityLevel,
    Urgency,
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
        # SBU (Sensitive But Unclassified) documents require security team review
        (DocumentType.UNKNOWN, SensitivityLevel.SENSITIVE_BUT_UNCLASSIFIED): (
            RoutingQueue.SECURITY_TEAM,
            RoutingQueue.LEGAL_COUNSEL,
        ),
        (DocumentType.INCIDENT_REPORT, SensitivityLevel.SENSITIVE_BUT_UNCLASSIFIED): (
            RoutingQueue.SECURITY_TEAM,
            RoutingQueue.LEGAL_COUNSEL,
        ),
    }

    # Fallback by document type when no sensitivity-specific rule exists.
    # Without this, an otherwise well-classified document could fall through to
    # the general queue just because the classifier returned a sensitivity
    # value that had no exact rule (for example a contract marked SBU).
    TYPE_DEFAULT_ROUTING = {
        DocumentType.CONTRACT: (RoutingQueue.CONTRACTING_OFFICER, RoutingQueue.LEGAL_COUNSEL),
        DocumentType.FOIA: (RoutingQueue.LEGAL_COUNSEL, RoutingQueue.POLICY_OFFICE),
        DocumentType.POLICY_MEMO: (RoutingQueue.POLICY_OFFICE, RoutingQueue.CHIEF_OF_STAFF),
        DocumentType.INCIDENT_REPORT: (RoutingQueue.SECURITY_TEAM, RoutingQueue.LEGAL_COUNSEL),
        DocumentType.PERSONNEL_ACTION: (RoutingQueue.HR_OFFICE, RoutingQueue.LEGAL_COUNSEL),
        DocumentType.FINANCIAL: (RoutingQueue.FINANCE_OFFICE, RoutingQueue.CHIEF_OF_STAFF),
        DocumentType.EXECUTIVE_CORRESPONDENCE: (
            RoutingQueue.CHIEF_OF_STAFF,
            RoutingQueue.POLICY_OFFICE,
        ),
        DocumentType.LEGAL: (RoutingQueue.LEGAL_COUNSEL, RoutingQueue.SECURITY_TEAM),
    }

    # Default routing for unmatched combinations
    DEFAULT_ROUTING = (RoutingQueue.GENERAL_QUEUE, RoutingQueue.LEGAL_COUNSEL)

    # Default SLA mapping: Urgency -> timedelta
    DEFAULT_SLA_MAPPING = {
        Urgency.ROUTINE: timedelta(days=10),
        Urgency.PRIORITY: timedelta(days=5),
        Urgency.IMMEDIATE: timedelta(hours=24),
        Urgency.EMERGENCY: timedelta(hours=4),
    }

    def __init__(self):
        self.routing_rules = self.ROUTING_RULES
        self.sla_mapping = {
            Urgency.ROUTINE: timedelta(days=self._env_number("DEFAULT_SLA_ROUTINE_DAYS", 10)),
            Urgency.PRIORITY: timedelta(days=self._env_number("DEFAULT_SLA_PRIORITY_DAYS", 5)),
            Urgency.IMMEDIATE: timedelta(hours=self._env_number("DEFAULT_SLA_IMMEDIATE_HOURS", 24)),
            Urgency.EMERGENCY: timedelta(hours=self._env_number("DEFAULT_SLA_EMERGENCY_HOURS", 4)),
        }

    @staticmethod
    def _env_number(name: str, default: float) -> float:
        raw = os.environ.get(name)
        if raw is None:
            return default
        try:
            value = float(raw)
        except ValueError:
            return default
        return value if value > 0 else default

    def route_document(
        self, document_id: str, classification: ClassificationResult
    ) -> RoutingDecision:
        """
        Route a classified document to appropriate queue.

        Resolution order: exact (type, sensitivity) rule, type default, global
        default.  The applied rule is recorded so downstream reviewers can see
        whether a sensitivity-specific rule matched.

        Args:
            document_id: Document identifier
            classification: Classification result from classifier agent

        Returns:
            RoutingDecision with queue assignment and SLA
        """
        document_type = self._coerce(DocumentType, classification["document_type"])
        sensitivity = self._coerce(SensitivityLevel, classification["sensitivity_level"])
        urgency = self._coerce(Urgency, classification["urgency"])

        rule_key = (document_type, sensitivity)
        exact_rule = self.routing_rules.get(rule_key)

        if exact_rule is not None:
            primary_queue, backup_queue = exact_rule
            rule_applied = f"{document_type.value}:{sensitivity.value}"
            rationale_prefix = "Matched sensitivity-specific routing rule"
        elif document_type in self.TYPE_DEFAULT_ROUTING:
            primary_queue, backup_queue = self.TYPE_DEFAULT_ROUTING[document_type]
            rule_applied = f"{document_type.value}:type-default"
            rationale_prefix = (
                "No sensitivity-specific rule for "
                f"{sensitivity.value}; applied document-type default"
            )
        else:
            primary_queue, backup_queue = self.DEFAULT_ROUTING
            rule_applied = "global-default"
            rationale_prefix = (
                f"No rule for {document_type.value}/{sensitivity.value}; applied global default"
            )

        # Assign reviewers (in production, would query staff directory)
        primary_reviewer_id = self._get_reviewer_for_queue(primary_queue)
        backup_reviewer_id = self._get_reviewer_for_queue(backup_queue)

        # Calculate SLA deadline
        sla_offset = self.sla_mapping.get(urgency, timedelta(days=10))
        sla_deadline = (datetime.now(timezone.utc) + sla_offset).isoformat()

        return RoutingDecision(
            primary_queue=primary_queue,
            backup_queue=backup_queue,
            primary_reviewer_id=primary_reviewer_id,
            backup_reviewer_id=backup_reviewer_id,
            sla_deadline=sla_deadline,
            routing_rationale=(
                f"{rationale_prefix}. Routed {document_type.value} with "
                f"{sensitivity.value} sensitivity to {primary_queue.value}."
            ),
            rule_applied=rule_applied,
        )

    @staticmethod
    def _coerce(enum_type, value):
        """Accept either an enum member or its serialized string value."""
        if isinstance(value, enum_type):
            return value
        return enum_type(value)

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
        sla_offset = self.sla_mapping.get(self._coerce(Urgency, urgency), timedelta(days=10))
        return (datetime.now(timezone.utc) + sla_offset).isoformat()
