"""End-to-end and node-level tests for the triage workflow."""

from pathlib import Path

import pytest

from agents.supervisor import SupervisorAgent
from workflows import nodes
from workflows.audit_context import close_audit_scope, get_auditor, open_audit_scope
from workflows.state import (
    ApprovalStatus,
    ClassificationResult,
    DocumentType,
    RoutingDecision,
    RoutingQueue,
    SensitivityLevel,
    TriageState,
    Urgency,
    initial_state,
)

SAMPLES = Path(__file__).resolve().parent.parent / "samples"

SAMPLE_EXPECTATIONS = {
    "sample_foia_request.txt": (
        DocumentType.FOIA,
        SensitivityLevel.UNCLASSIFIED,
        RoutingQueue.LEGAL_COUNSEL,
    ),
    "sample_contract_memo.txt": (
        DocumentType.CONTRACT,
        SensitivityLevel.SENSITIVE_BUT_UNCLASSIFIED,
        RoutingQueue.CONTRACTING_OFFICER,
    ),
    "sample_incident_report.txt": (
        DocumentType.INCIDENT_REPORT,
        SensitivityLevel.CONTROLLED_UNCLASSIFIED,
        RoutingQueue.SECURITY_TEAM,
    ),
    "sample_executive_correspondence.txt": (
        DocumentType.EXECUTIVE_CORRESPONDENCE,
        SensitivityLevel.FOR_OFFICIAL_USE_ONLY,
        RoutingQueue.CHIEF_OF_STAFF,
    ),
}


@pytest.fixture(autouse=True)
def demo_environment(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setenv("USE_COMPREHEND", "false")
    monkeypatch.delenv("ALLOW_CLASSIFIER_FALLBACK", raising=False)


@pytest.fixture
def scoped_auditor():
    token = open_audit_scope()
    try:
        yield get_auditor()
    finally:
        close_audit_scope(token)


def _classification(
    document_type=DocumentType.FOIA,
    sensitivity=SensitivityLevel.UNCLASSIFIED,
    urgency=Urgency.ROUTINE,
    confidence=0.99,
):
    return ClassificationResult(
        document_type=document_type,
        sensitivity_level=sensitivity,
        urgency=urgency,
        subject="Test subject",
        summary="Test summary",
        action_required="Review",
        originating_agency="Test Agency",
        keywords=["test"],
        confidence_score=confidence,
    )


def _routing():
    return RoutingDecision(
        primary_queue=RoutingQueue.LEGAL_COUNSEL,
        backup_queue=RoutingQueue.POLICY_OFFICE,
        primary_reviewer_id="legal-counsel-001",
        backup_reviewer_id="policy-officer-001",
        sla_deadline="2030-01-01T00:00:00+00:00",
        routing_rationale="test",
        rule_applied="test",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("filename", sorted(SAMPLE_EXPECTATIONS))
async def test_sample_documents_end_to_end(filename):
    content = (SAMPLES / filename).read_text(encoding="utf-8")
    supervisor = SupervisorAgent()

    state = await supervisor.process_document(
        document_id=f"TEST-{filename}",
        s3_key=f"s3://test-bucket/{filename}",
        content=content,
    )

    expected_type, expected_sensitivity, expected_queue = SAMPLE_EXPECTATIONS[filename]
    assert state["error"] is None
    assert state["processing_complete"] is True
    assert state["classification"]["document_type"] == expected_type
    assert state["classification"]["sensitivity_level"] == expected_sensitivity
    assert state["routing"]["primary_queue"] == expected_queue
    assert state["pii_detection"]["has_pii"] is True
    assert state["pii_detection"]["redaction_applied"] is True
    assert state["audit_persistence_mode"] == "in_memory_demo"
    assert state["audit_persisted"] is False
    assert len(state["audit_trail"]) >= 4

    # PII must not appear in the content sent to the classifier.
    assert "s.mitchell@research.gov" not in state["document_content_redacted"]
    assert "123-45-6789" not in state["document_content_redacted"]

    # Sensitive documents always require a human decision.
    if expected_sensitivity != SensitivityLevel.UNCLASSIFIED:
        assert state["approval_status"] == ApprovalStatus.IN_REVIEW
    assert all(
        event["metadata"]["document_id"] == f"TEST-{filename}"
        for event in state["audit_trail"]
    )


@pytest.mark.asyncio
async def test_concurrent_documents_have_isolated_audit_trails():
    content = (SAMPLES / "sample_foia_request.txt").read_text(encoding="utf-8")
    supervisor = SupervisorAgent()

    results = await supervisor.process_documents_batch(
        [
            {"document_id": "CONCURRENT-A", "s3_key": "s3://bucket/a.txt", "content": content},
            {"document_id": "CONCURRENT-B", "s3_key": "s3://bucket/b.txt", "content": content},
        ]
    )

    assert len(results) == 2
    for doc_id, state in zip(("CONCURRENT-A", "CONCURRENT-B"), results):
        assert state["error"] is None
        assert state["document_id"] == doc_id
        assert len(state["audit_trail"]) >= 4
        assert {
            event["metadata"]["document_id"] for event in state["audit_trail"]
        } == {doc_id}


@pytest.mark.asyncio
async def test_sensitive_document_never_auto_approved(scoped_auditor):
    state = initial_state("DOC-CUI", "s3://bucket/cui.txt", "content")
    state["classification"] = _classification(
        document_type=DocumentType.INCIDENT_REPORT,
        sensitivity=SensitivityLevel.CONTROLLED_UNCLASSIFIED,
        confidence=0.99,
    )
    state["routing"] = _routing()

    result = await nodes.approval_node(state)

    assert result["approval_status"] == ApprovalStatus.IN_REVIEW
    assert result["approval_reviewer"] == "legal-counsel-001"
    assert "requires human review" in result["approval_notes"]
    assert result["error"] is None


@pytest.mark.asyncio
async def test_unclassified_high_confidence_is_auto_approved(scoped_auditor):
    state = initial_state("DOC-UNCLASS", "s3://bucket/u.txt", "content")
    state["classification"] = _classification(confidence=0.99)
    state["routing"] = _routing()

    result = await nodes.approval_node(state)

    assert result["approval_status"] == ApprovalStatus.APPROVED
    assert result["approval_reviewer"] == "auto-approval-bot"
    assert result["approval_timestamp"] is not None


@pytest.mark.asyncio
async def test_unclassified_low_confidence_requires_review(scoped_auditor):
    state = initial_state("DOC-LOW", "s3://bucket/l.txt", "content")
    state["classification"] = _classification(confidence=0.85)
    state["routing"] = _routing()

    result = await nodes.approval_node(state)

    assert result["approval_status"] == ApprovalStatus.IN_REVIEW
    assert "does not exceed" in result["approval_notes"]


@pytest.mark.asyncio
async def test_failed_intake_retries_then_audits_without_classifying(monkeypatch):
    calls = {"intake": 0, "classify": 0}

    def failing_intake(document_id, content):
        calls["intake"] += 1
        raise RuntimeError("synthetic intake failure")

    def unexpected_classify(*args, **kwargs):
        calls["classify"] += 1
        return _classification()

    monkeypatch.setattr(nodes.intake_agent, "process_document", failing_intake)
    monkeypatch.setattr(nodes.classifier_agent, "classify_document", unexpected_classify)

    supervisor = SupervisorAgent()
    state = await supervisor.process_document(
        document_id="DOC-FAIL",
        s3_key="s3://bucket/fail.txt",
        content="content",
    )

    assert calls["intake"] == 4  # initial attempt + 3 retries
    assert calls["classify"] == 0
    assert state["processing_complete"] is False
    assert "Intake processing failed" in state["error"]
    assert state["classification"] is None
    assert state["audit_trail"]
    assert state["audit_trail"][-1]["action"] == "finalize_workflow"
    assert state["audit_trail"][-1]["outcome"] == "failure"


@pytest.mark.asyncio
async def test_audit_persistence_failure_fails_workflow(monkeypatch, scoped_auditor):
    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.setattr(
        "agents.auditor_agent.AuditorAgent.persist_to_dynamodb",
        lambda self, table_name, events=None: False,
    )
    state = initial_state("DOC-AUDIT", "s3://bucket/a.txt", "content")

    result = await nodes.audit_node(state)

    assert result["audit_persisted"] is False
    assert result["processing_complete"] is False
    assert "Audit persistence failed" in result["error"]
    assert result["audit_trail"]



def test_state_has_audit_fields():
    state: TriageState = initial_state("DOC", "s3://b/d", "c")
    assert state["audit_persisted"] is False
    assert state["audit_persistence_mode"] == "not_started"


@pytest.mark.asyncio
async def test_serialized_sensitivity_cannot_be_auto_approved(scoped_auditor):
    state = initial_state("DOC-STRING", "s3://bucket/s.txt", "content")
    state["classification"] = _classification(confidence=0.99)
    state["classification"]["sensitivity_level"] = "cui"  # type: ignore[typeddict-item]
    state["routing"] = _routing()

    result = await nodes.approval_node(state)

    assert result["approval_status"] == ApprovalStatus.IN_REVIEW
    assert "requires human review" in result["approval_notes"]


@pytest.mark.asyncio
async def test_unknown_sensitivity_fails_closed(scoped_auditor):
    state = initial_state("DOC-UNKNOWN-SENS", "s3://bucket/s.txt", "content")
    state["classification"] = _classification(confidence=0.99)
    state["classification"]["sensitivity_level"] = "not-a-level"  # type: ignore[typeddict-item]
    state["routing"] = _routing()

    result = await nodes.approval_node(state)

    assert result["approval_status"] == ApprovalStatus.IN_REVIEW


def test_get_workflow_status_accepts_serialized_values():
    state = initial_state("DOC-SERIALIZED", "s3://bucket/d.txt", "content")
    state["approval_status"] = "in_review"  # type: ignore[typeddict-item]
    state["classification"] = {
        "document_type": "foia",
        "sensitivity_level": "unclassified",
        "urgency": "routine",
        "subject": "s",
        "summary": "s",
        "action_required": "a",
        "originating_agency": None,
        "keywords": [],
        "confidence_score": 0.5,
    }
    state["routing"] = {
        "primary_queue": "legal_counsel",
        "backup_queue": "policy_office",
        "primary_reviewer_id": "legal-counsel-001",
        "backup_reviewer_id": "policy-officer-001",
        "sla_deadline": "2030-01-01T00:00:00+00:00",
        "routing_rationale": "test",
        "rule_applied": "test",
    }

    status = SupervisorAgent().get_workflow_status(state)

    assert status["status"] == "in_review"
    assert status["document_type"] == "foia"
    assert status["assigned_queue"] == "legal_counsel"
