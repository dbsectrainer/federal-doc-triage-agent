"""Tests for router agent."""

from datetime import datetime, timezone

import pytest

from agents.router_agent import RouterAgent
from workflows.state import (
    ClassificationResult,
    DocumentType,
    RoutingQueue,
    SensitivityLevel,
    Urgency,
)


@pytest.fixture
def router():
    """Create a router agent."""
    return RouterAgent()


@pytest.fixture
def sample_classification():
    """Create a sample classification result."""
    return ClassificationResult(
        document_type=DocumentType.CONTRACT,
        sensitivity_level=SensitivityLevel.CONTROLLED_UNCLASSIFIED,
        urgency=Urgency.PRIORITY,
        subject="Test Contract",
        summary="Test contract memo",
        action_required="Review and approve",
        originating_agency="Test Agency",
        keywords=["contract", "procurement"],
        confidence_score=0.95,
    )


def test_router_initialization(router):
    """Test router initialization."""
    assert router.routing_rules is not None
    assert router.sla_mapping is not None
    assert len(router.routing_rules) > 0


def test_route_contract_document(router, sample_classification):
    """Test routing a contract document."""
    routing = router.route_document(
        document_id="DOC-001",
        classification=sample_classification,
    )

    assert routing["primary_queue"] == RoutingQueue.CONTRACTING_OFFICER
    assert routing["backup_queue"] == RoutingQueue.LEGAL_COUNSEL
    assert routing["primary_reviewer_id"] is not None
    assert routing["sla_deadline"] is not None


def test_route_foia_document(router):
    """Test routing a FOIA document."""
    foia_classification = ClassificationResult(
        document_type=DocumentType.FOIA,
        sensitivity_level=SensitivityLevel.UNCLASSIFIED,
        urgency=Urgency.ROUTINE,
        subject="FOIA Request",
        summary="FOIA request for records",
        action_required="Process and respond",
        originating_agency=None,
        keywords=["foia", "public"],
        confidence_score=0.88,
    )

    routing = router.route_document(
        document_id="DOC-002",
        classification=foia_classification,
    )

    assert routing["primary_queue"] == RoutingQueue.LEGAL_COUNSEL
    assert routing["backup_queue"] == RoutingQueue.POLICY_OFFICE


def test_route_incident_report(router):
    """Test routing an incident report."""
    incident_classification = ClassificationResult(
        document_type=DocumentType.INCIDENT_REPORT,
        sensitivity_level=SensitivityLevel.CONTROLLED_UNCLASSIFIED,
        urgency=Urgency.EMERGENCY,
        subject="Security Incident Report",
        summary="High-severity security incident",
        action_required="Immediate escalation",
        originating_agency="Federal Agency XYZ",
        keywords=["incident", "security", "breach"],
        confidence_score=0.99,
    )

    routing = router.route_document(
        document_id="DOC-003",
        classification=incident_classification,
    )

    assert routing["primary_queue"] == RoutingQueue.SECURITY_TEAM
    assert routing["backup_queue"] == RoutingQueue.LEGAL_COUNSEL


def test_sla_deadline_calculation(router):
    """Test SLA deadline calculation."""
    # Test routine (10 days)
    routine_sla = router.get_sla_deadline(Urgency.ROUTINE)
    routine_deadline = datetime.fromisoformat(routine_sla)
    days_remaining = (routine_deadline - datetime.now(timezone.utc)).total_seconds() / 86400
    assert 9.9 < days_remaining < 10.1

    # Test priority (5 days)
    priority_sla = router.get_sla_deadline(Urgency.PRIORITY)
    priority_deadline = datetime.fromisoformat(priority_sla)
    days_remaining = (priority_deadline - datetime.now(timezone.utc)).total_seconds() / 86400
    assert 4.9 < days_remaining < 5.1

    # Test immediate (24 hours)
    immediate_sla = router.get_sla_deadline(Urgency.IMMEDIATE)
    immediate_deadline = datetime.fromisoformat(immediate_sla)
    hours_remaining = (immediate_deadline - datetime.now(timezone.utc)).total_seconds() / 3600
    assert 23 < hours_remaining < 25

    # Test emergency (4 hours)
    emergency_sla = router.get_sla_deadline(Urgency.EMERGENCY)
    emergency_deadline = datetime.fromisoformat(emergency_sla)
    hours_remaining = (emergency_deadline - datetime.now(timezone.utc)).total_seconds() / 3600
    assert 3.5 < hours_remaining < 4.5


def test_default_routing(router):
    """Test default routing for unknown document types."""
    unknown_classification = ClassificationResult(
        document_type=DocumentType.UNKNOWN,
        sensitivity_level=SensitivityLevel.UNCLASSIFIED,
        urgency=Urgency.ROUTINE,
        subject="Unknown Document",
        summary="Unknown document type",
        action_required="Manual review",
        originating_agency=None,
        keywords=[],
        confidence_score=0.45,
    )

    routing = router.route_document(
        document_id="DOC-004",
        classification=unknown_classification,
    )

    # Should use default routing
    assert routing["primary_queue"] == RoutingQueue.GENERAL_QUEUE
    assert routing["backup_queue"] == RoutingQueue.LEGAL_COUNSEL


def test_routing_rationale(router, sample_classification):
    """Test that routing rationale is generated."""
    routing = router.route_document(
        document_id="DOC-005",
        classification=sample_classification,
    )

    assert routing["routing_rationale"] is not None
    assert len(routing["routing_rationale"]) > 0
    assert "contract" in routing["routing_rationale"].lower()


@pytest.mark.parametrize(
    "document_type,expected_queue",
    [
        (DocumentType.CONTRACT, RoutingQueue.CONTRACTING_OFFICER),
        (DocumentType.FOIA, RoutingQueue.LEGAL_COUNSEL),
        (DocumentType.POLICY_MEMO, RoutingQueue.POLICY_OFFICE),
        (DocumentType.PERSONNEL_ACTION, RoutingQueue.HR_OFFICE),
        (DocumentType.FINANCIAL, RoutingQueue.FINANCE_OFFICE),
        (DocumentType.EXECUTIVE_CORRESPONDENCE, RoutingQueue.CHIEF_OF_STAFF),
        (DocumentType.LEGAL, RoutingQueue.LEGAL_COUNSEL),
    ],
)
def test_sbu_uses_document_type_fallback(router, document_type, expected_queue):
    """SBU documents without an exact rule must not fall through to general queue."""
    classification = ClassificationResult(
        document_type=document_type,
        sensitivity_level=SensitivityLevel.SENSITIVE_BUT_UNCLASSIFIED,
        urgency=Urgency.ROUTINE,
        subject="SBU document",
        summary="SBU document",
        action_required="Review",
        originating_agency=None,
        keywords=[],
        confidence_score=0.8,
    )

    routing = router.route_document("DOC-SBU", classification)

    assert routing["primary_queue"] == expected_queue
    assert routing["rule_applied"] == f"{document_type.value}:type-default"
    assert "document-type default" in routing["routing_rationale"]


def test_unknown_type_uses_global_default(router):
    classification = ClassificationResult(
        document_type=DocumentType.UNKNOWN,
        sensitivity_level=SensitivityLevel.UNCLASSIFIED,
        urgency=Urgency.ROUTINE,
        subject="Unknown",
        summary="Unknown",
        action_required="Review",
        originating_agency=None,
        keywords=[],
        confidence_score=0.4,
    )

    routing = router.route_document("DOC-UNKNOWN", classification)

    assert routing["primary_queue"] == RoutingQueue.GENERAL_QUEUE
    assert routing["rule_applied"] == "global-default"


def test_router_accepts_serialized_enum_values(router):
    classification = ClassificationResult(
        document_type="contract",  # type: ignore[typeddict-item]
        sensitivity_level="cui",  # type: ignore[typeddict-item]
        urgency="priority",  # type: ignore[typeddict-item]
        subject="Serialized",
        summary="Serialized",
        action_required="Review",
        originating_agency=None,
        keywords=[],
        confidence_score=0.5,
    )

    routing = router.route_document("DOC-SERIALIZED", classification)

    assert routing["primary_queue"] == RoutingQueue.CONTRACTING_OFFICER
    assert routing["rule_applied"] == "contract:cui"


def test_sla_environment_overrides(monkeypatch):
    monkeypatch.setenv("DEFAULT_SLA_ROUTINE_DAYS", "2")
    monkeypatch.setenv("DEFAULT_SLA_EMERGENCY_HOURS", "1")
    agent = RouterAgent()

    routine_deadline = datetime.fromisoformat(agent.get_sla_deadline(Urgency.ROUTINE))
    emergency_deadline = datetime.fromisoformat(agent.get_sla_deadline(Urgency.EMERGENCY))
    now = datetime.now(timezone.utc)

    assert 1.9 < (routine_deadline - now).total_seconds() / 86400 < 2.1
    assert 0.9 < (emergency_deadline - now).total_seconds() / 3600 < 1.1


def test_invalid_sla_environment_uses_defaults(monkeypatch):
    monkeypatch.setenv("DEFAULT_SLA_PRIORITY_DAYS", "not-a-number")
    agent = RouterAgent()

    priority_deadline = datetime.fromisoformat(agent.get_sla_deadline(Urgency.PRIORITY))
    days_remaining = (priority_deadline - datetime.now(timezone.utc)).total_seconds() / 86400
    assert 4.9 < days_remaining < 5.1


def test_sla_deadline_type_is_serializable(router):
    deadline = router.get_sla_deadline(Urgency.IMMEDIATE)
    assert isinstance(deadline, str)
    assert datetime.fromisoformat(deadline).tzinfo is not None
