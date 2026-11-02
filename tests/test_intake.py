"""Tests for PII detection and redaction in the intake agent."""

from unittest.mock import patch

import pytest

from agents.intake_agent import IntakeAgent
from workflows.state import PIIDetection


@pytest.fixture
def intake(monkeypatch):
    monkeypatch.setenv("USE_COMPREHEND", "false")
    with patch("boto3.client"):
        return IntakeAgent()


def test_normalize_document(intake):
    raw = "Heading\n\n\n\nBody     with   spaces   \n"
    assert intake.normalize_document(raw) == "Heading\n\nBody with spaces"


def test_no_pii_detected(intake):
    redacted, detection = intake.process_document("DOC-1", "No sensitive data here.")
    assert detection["has_pii"] is False
    assert detection["entity_count"] == 0
    assert detection["redaction_applied"] is False
    assert redacted == "No sensitive data here."


def test_email_phone_and_ssn_are_redacted(intake):
    content = (
        "Contact jane.doe@example.gov or (202) 555-0198. "
        "SSN: 123-45-6789."
    )
    redacted, detection = intake.process_document("DOC-2", content)

    assert detection["has_pii"] is True
    assert set(detection["entity_types"]) == {"EMAIL", "PHONE", "SSN"}
    assert detection["entity_count"] == 3
    assert "jane.doe@example.gov" not in redacted
    assert "(202) 555-0198" not in redacted
    assert "123-45-6789" not in redacted
    assert "[REDACTED:EMAIL]" in redacted
    assert "[REDACTED:PHONE]" in redacted
    assert "[REDACTED:SSN]" in redacted


def test_overlapping_patterns_are_redacted_once(intake):
    # The phone and credit-card patterns can both match portions of this
    # string; the longer span must win and the result must stay well formed.
    content = "Card 4111 1111 1111 1111 on file"
    redacted, detection = intake.process_document("DOC-3", content)

    assert detection["has_pii"] is True
    assert detection["entity_count"] == 1
    assert "[REDACTED:CREDIT_CARD]" in redacted
    assert "4111" not in redacted
    assert redacted.count("[REDACTED:") == 1


def test_date_of_birth_is_redacted(intake):
    redacted, detection = intake.process_document("DOC-4", "DOB: 05/06/1980")
    assert "05/06/1980" not in redacted
    assert "[REDACTED:DATE_OF_BIRTH]" in redacted
    assert detection["has_pii"] is True


def test_comprehend_entities_are_redacted_by_span(monkeypatch):
    monkeypatch.setenv("USE_COMPREHEND", "true")
    with patch("boto3.client"):
        intake = IntakeAgent()

    text = "Alice Smith lives in Denver."
    intake.comprehend.detect_pii_entities.return_value = {
        "Entities": [
            {"Type": "PERSON", "BeginOffset": 0, "EndOffset": 11, "Score": 0.99},
            {"Type": "ADDRESS", "BeginOffset": 21, "EndOffset": 27, "Score": 0.90},
        ]
    }

    redacted, detection = intake.process_document("DOC-5", text)

    assert detection["entity_count"] == 2
    assert redacted == "[REDACTED:PERSON] lives in [REDACTED:ADDRESS]."
    assert "Alice" not in redacted


def test_large_text_skips_comprehend(monkeypatch):
    monkeypatch.setenv("USE_COMPREHEND", "true")
    with patch("boto3.client"):
        intake = IntakeAgent()
    text = ("x" * 100_001) + " jane@example.gov"

    redacted, detection = intake.process_document("DOC-6", text)

    assert detection["has_pii"] is True
    assert "jane@example.gov" not in redacted
    intake.comprehend.detect_pii_entities.assert_not_called()


def test_redaction_handles_entity_without_spans(intake):
    text = "SSN 123-45-6789"
    detection = PIIDetection(
        has_pii=True,
        entity_types=["SSN"],
        entity_count=1,
        redaction_applied=True,
        detected_entities=[],
    )
    assert intake._redact_pii(text, detection) == "SSN [REDACTED:SSN]"


def test_pdf_extraction_rejects_invalid_key(intake):
    result = intake.extract_text_from_pdf("DOC-7", "not-a-bucket-key")
    assert result.startswith("[Error:")


def test_pdf_extraction_success(intake):
    intake.textract.start_document_text_detection.return_value = {"JobId": "job-1"}
    intake.textract.get_document_text_detection.return_value = {
        "JobStatus": "SUCCEEDED",
        "Blocks": [
            {"BlockType": "LINE", "Text": "First line"},
            {"BlockType": "WORD", "Text": "ignored"},
            {"BlockType": "LINE", "Text": "Second line"},
        ],
    }

    text = intake.extract_text_from_pdf("DOC-PDF", "bucket/key.pdf")

    assert text == "First line\nSecond line"
    intake.textract.start_document_text_detection.assert_called_once_with(
        DocumentLocation={"S3Object": {"Bucket": "bucket", "Name": "key.pdf"}}
    )


def test_pdf_extraction_reports_failed_job(intake):
    intake.textract.start_document_text_detection.return_value = {"JobId": "job-2"}
    intake.textract.get_document_text_detection.return_value = {"JobStatus": "FAILED"}

    text = intake.extract_text_from_pdf("DOC-PDF", "bucket/key.pdf")

    assert text == "[Error: Textract job failed for DOC-PDF]"


def test_pdf_extraction_reports_timeout(intake):
    intake.textract.start_document_text_detection.return_value = {"JobId": "job-3"}
    intake.textract.get_document_text_detection.return_value = {"JobStatus": "IN_PROGRESS"}

    with patch("time.time", side_effect=[0, 0, 301, 0, 0, 0]), patch("time.sleep"):
        text = intake.extract_text_from_pdf("DOC-PDF", "bucket/key.pdf")

    assert text == "[Error: Textract job timeout after 300s for DOC-PDF]"


def test_pdf_extraction_reports_exception(intake):
    intake.textract.start_document_text_detection.side_effect = RuntimeError("aws error")

    text = intake.extract_text_from_pdf("DOC-PDF", "bucket/key.pdf")

    assert text.startswith("[Error: Error extracting PDF DOC-PDF:")


def test_comprehend_confidence_threshold_filters_low_score(monkeypatch):
    monkeypatch.setenv("USE_COMPREHEND", "true")
    monkeypatch.setenv("REDACTION_CONFIDENCE_THRESHOLD", "0.9")
    with patch("boto3.client"):
        intake = IntakeAgent()
    intake.comprehend.detect_pii_entities.return_value = {
        "Entities": [
            {"Type": "PERSON", "BeginOffset": 0, "EndOffset": 5, "Score": 0.5},
            {"Type": "EMAIL", "BeginOffset": 6, "EndOffset": 20, "Score": 0.99},
        ]
    }

    redacted, detection = intake.process_document("DOC-7", "Alice alice@example.gov")

    assert detection["entity_count"] == 1
    assert detection["entity_types"] == ["EMAIL"]
    assert "[REDACTED:EMAIL]" in redacted
    assert "Alice" in redacted
