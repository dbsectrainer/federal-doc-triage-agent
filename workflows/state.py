"""Workflow state schema for the federal document triage pipeline."""

from __future__ import annotations

from enum import Enum
from typing import TypedDict, Optional, List, Dict, Any
from datetime import datetime


class DocumentType(str, Enum):
    CONTRACT = "contract"
    FOIA = "foia"
    POLICY_MEMO = "policy_memo"
    INCIDENT_REPORT = "incident_report"
    PERSONNEL_ACTION = "personnel_action"
    FINANCIAL = "financial"
    EXECUTIVE_CORRESPONDENCE = "executive_correspondence"
    LEGAL = "legal"
    UNKNOWN = "unknown"


class SensitivityLevel(str, Enum):
    UNCLASSIFIED = "unclassified"
    CONTROLLED_UNCLASSIFIED = "cui"           # CUI / SBU
    SENSITIVE_BUT_UNCLASSIFIED = "sbu"
    FOR_OFFICIAL_USE_ONLY = "fouo"


class Urgency(str, Enum):
    ROUTINE = "routine"        # 10 business days
    PRIORITY = "priority"      # 5 business days
    IMMEDIATE = "immediate"    # 24 hours
    EMERGENCY = "emergency"    # 4 hours


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    DELEGATED = "delegated"
    ESCALATED = "escalated"
    EXPIRED = "expired"


class RoutingQueue(str, Enum):
    CONTRACTING_OFFICER = "contracting_officer"
    LEGAL_COUNSEL = "legal_counsel"
    POLICY_OFFICE = "policy_office"
    SECURITY_TEAM = "security_team"
    HR_OFFICE = "hr_office"
    FINANCE_OFFICE = "finance_office"
    CHIEF_OF_STAFF = "chief_of_staff"
    GENERAL_QUEUE = "general_queue"


class PIIDetection(TypedDict):
    has_pii: bool
    entity_types: List[str]
    entity_count: int
    redaction_applied: bool


class ClassificationResult(TypedDict):
    document_type: DocumentType
    sensitivity_level: SensitivityLevel
    urgency: Urgency
    subject: str
    summary: str
    action_required: str
    originating_agency: Optional[str]
    keywords: List[str]
    confidence_score: float


class RoutingDecision(TypedDict):
    primary_queue: RoutingQueue
    backup_queue: Optional[RoutingQueue]
    primary_reviewer_id: Optional[str]
    backup_reviewer_id: Optional[str]
    sla_deadline: str                       # ISO-8601 timestamp
    routing_rationale: str
    rule_applied: str


class AuditEvent(TypedDict):
    event_id: str
    timestamp: str
    event_type: str
    agent: str
    action: str
    outcome: str
    metadata: Dict[str, Any]


class TriageState(TypedDict):
    """Full workflow state passed between LangGraph nodes."""

    # --- Input ---
    document_id: str
    document_s3_key: str
    document_content: str                   # Raw text content
    document_content_redacted: str          # PII-redacted version sent to LLM
    intake_timestamp: str                   # ISO-8601

    # --- PII Detection ---
    pii_detection: Optional[PIIDetection]

    # --- Classification ---
    classification: Optional[ClassificationResult]

    # --- Routing ---
    routing: Optional[RoutingDecision]

    # --- Approval ---
    approval_status: ApprovalStatus
    approval_reviewer: Optional[str]
    approval_timestamp: Optional[str]
    approval_notes: Optional[str]
    escalation_count: int

    # --- Audit ---
    audit_trail: List[AuditEvent]

    # --- Error handling ---
    error: Optional[str]
    retry_count: int

    # --- Metadata ---
    processing_complete: bool
    workflow_version: str


def initial_state(document_id: str, s3_key: str, content: str) -> TriageState:
    """Create the initial state for a new document."""
    return TriageState(
        document_id=document_id,
        document_s3_key=s3_key,
        document_content=content,
        document_content_redacted="",
        intake_timestamp=datetime.utcnow().isoformat(),
        pii_detection=None,
        classification=None,
        routing=None,
        approval_status=ApprovalStatus.PENDING,
        approval_reviewer=None,
        approval_timestamp=None,
        approval_notes=None,
        escalation_count=0,
        audit_trail=[],
        error=None,
        retry_count=0,
        processing_complete=False,
        workflow_version="1.0.0",
    )
