#!/usr/bin/env python3
"""Local smoke checks that do not require AWS credentials.

This is a human-readable companion to ``pytest``; it exercises imports,
router logic, audit logging, state initialization, sample documents, and the
Lambda handler's source-level contract.  It exits non-zero on the first
failure so it can be used in CI or a release checklist.
"""

from __future__ import annotations

import sys
from pathlib import Path

from agents.auditor_agent import AuditorAgent
from agents.router_agent import RouterAgent
from workflows.state import (
    ApprovalStatus,
    ClassificationResult,
    DocumentType,
    RoutingQueue,
    SensitivityLevel,
    Urgency,
    initial_state,
)


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"PASS: {message}")


def check_imports() -> None:
    from agents.classifier_agent import ClassifierAgent
    from agents.intake_agent import IntakeAgent
    from agents.supervisor import SupervisorAgent
    from workflows.graph import create_workflow

    for cls in (IntakeAgent, ClassifierAgent, RouterAgent, AuditorAgent, SupervisorAgent):
        check(cls is not None, f"imported {cls.__name__}")
    check(create_workflow() is not None, "compiled LangGraph workflow")


def check_router() -> None:
    router = RouterAgent()
    classification = ClassificationResult(
        document_type=DocumentType.CONTRACT,
        sensitivity_level=SensitivityLevel.SENSITIVE_BUT_UNCLASSIFIED,
        urgency=Urgency.PRIORITY,
        subject="Contract",
        summary="Contract",
        action_required="Review",
        originating_agency=None,
        keywords=["contract"],
        confidence_score=0.9,
    )
    result = router.route_document("SMOKE-001", classification)
    check(
        result["primary_queue"] == RoutingQueue.CONTRACTING_OFFICER,
        "SBU contract routes to contracting officer",
    )
    check(result["sla_deadline"].endswith("+00:00"), "SLA deadline is timezone-aware")


def check_auditor() -> None:
    auditor = AuditorAgent()
    auditor.log_pii_detection("SMOKE-001", ["EMAIL"], 1)
    auditor.log_classification("SMOKE-001", "contract", 0.9)
    check(len(auditor.get_audit_trail()) == 2, "audit trail records events")
    check(
        "SMOKE-001" in auditor.export_audit_trail_json(),
        "audit trail exports JSON",
    )


def check_state() -> None:
    state = initial_state("SMOKE-001", "s3://bucket/doc.txt", "Test content")
    check(state["approval_status"] == ApprovalStatus.PENDING, "initial status pending")
    check(state["retry_count"] == 0, "initial retry count zero")
    check(state["audit_persisted"] is False, "initial audit persistence flag")


def check_samples() -> None:
    samples = sorted(Path("samples").glob("*.txt"))
    check(len(samples) == 4, "four sample documents present")
    for sample in samples:
        content = sample.read_text(encoding="utf-8")
        check(len(content) > 100, f"{sample.name} readable ({len(content)} bytes)")


def check_lambda_source() -> None:
    source = Path("lambda/intake_handler.py").read_text(encoding="utf-8")
    check("def lambda_handler" in source, "S3 Lambda handler present")
    check("def lambda_handler_api_gateway" in source, "API Gateway handler present")
    check("_build_state_item" in source, "state persistence sanitizer present")
    check("document_content_redacted" in source, "redacted body is excluded from state")


def main() -> int:
    print("=" * 60)
    print("Federal Document Triage Agent - local smoke checks")
    print("=" * 60)
    try:
        check_imports()
        check_router()
        check_auditor()
        check_state()
        check_samples()
        check_lambda_source()
    except Exception as exc:
        print(f"\nFAIL: {exc}")
        return 1

    print("\nAll local smoke checks passed.")
    print("AWS services (Bedrock, Comprehend, DynamoDB) were not called.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
