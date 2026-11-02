"""Tests for classifier agent."""

from unittest.mock import Mock, patch

import pytest

from agents.classifier_agent import ClassifierAgent
from workflows.state import DocumentType, SensitivityLevel, Urgency


@pytest.fixture
def classifier(monkeypatch):
    """Create a classifier agent with mocked Bedrock client."""
    monkeypatch.delenv("BEDROCK_MODEL_ID", raising=False)
    monkeypatch.delenv("BEDROCK_REGION", raising=False)
    monkeypatch.delenv("AWS_REGION", raising=False)
    with patch("boto3.client"):
        return ClassifierAgent()


def test_classifier_initialization(monkeypatch):
    """Test classifier agent initialization."""
    monkeypatch.delenv("BEDROCK_MODEL_ID", raising=False)
    with patch("boto3.client"):
        classifier = ClassifierAgent(region="us-gov-west-1")
        assert classifier.bedrock is not None
        assert classifier.model_id == "anthropic.claude-3-sonnet-20240229-v1:0"


def test_classifier_initialization_custom_model():
    """Test classifier with custom model ID."""
    with patch("boto3.client"):
        classifier = ClassifierAgent(
            region="us-gov-west-1",
            model_id="custom-model-id"
        )
        assert classifier.model_id == "custom-model-id"


def test_classify_document_success(classifier):
    """Test successful document classification."""
    import json
    # Mock Bedrock response
    text_content = json.dumps({
        "document_type": "policy_memo",
        "sensitivity_level": "fouo",
        "urgency": "priority",
        "subject": "Cloud Security Policy Update",
        "summary": "Policy memo outlining updates to cloud security requirements",
        "action_required": "Review and approve",
        "originating_agency": "Federal Agency XYZ",
        "keywords": ["cloud", "security", "policy"],
        "confidence_score": 0.95
    })
    mock_response = {
        "body": Mock(read=Mock(return_value=json.dumps({
            "content": [{
                "type": "text",
                "text": text_content
            }]
        }).encode())),
    }

    classifier.bedrock.invoke_model = Mock(return_value=mock_response)

    result = classifier.classify_document(
        document_id="DOC-001",
        content="Full document content here",
        redacted_content="Redacted content here"
    )

    assert result["document_type"] == DocumentType.POLICY_MEMO
    assert result["sensitivity_level"] == SensitivityLevel.FOR_OFFICIAL_USE_ONLY
    assert result["urgency"] == Urgency.PRIORITY
    assert result["subject"] == "Cloud Security Policy Update"
    assert result["confidence_score"] == 0.95
    assert "cloud" in result["keywords"]


def test_classify_document_called_bedrock_correctly(classifier):
    """Test that classifier calls Bedrock with correct parameters."""
    import json
    text_content = json.dumps({
        "document_type": "unknown",
        "sensitivity_level": "unclassified",
        "urgency": "routine",
        "subject": "Test",
        "summary": "Test",
        "action_required": "None",
        "originating_agency": None,
        "keywords": [],
        "confidence_score": 0.5
    })
    mock_response = {
        "body": Mock(read=Mock(return_value=json.dumps({
            "content": [{
                "type": "text",
                "text": text_content
            }]
        }).encode())),
    }

    classifier.bedrock.invoke_model = Mock(return_value=mock_response)

    classifier.classify_document(
        document_id="DOC-002",
        content="Content",
        redacted_content="Redacted"
    )

    # Verify invoke_model was called
    assert classifier.bedrock.invoke_model.called
    call_args = classifier.bedrock.invoke_model.call_args

    # Check key parameters
    assert call_args.kwargs["modelId"] == classifier.model_id
    assert call_args.kwargs["contentType"] == "application/json"
    assert call_args.kwargs["accept"] == "application/json"


def test_classify_document_demo_mode(monkeypatch):
    """Test local rule-based classification when DEMO_MODE is enabled."""
    monkeypatch.setenv("DEMO_MODE", "true")

    with patch("boto3.client"):
        classifier = ClassifierAgent()

    foia_content = (
        "FREEDOM OF INFORMATION ACT REQUEST\n"
        "RE: Freedom of Information Act Request\n"
        "REQUEST FOR EXPEDITED PROCESSING"
    )
    result = classifier.classify_document(
        document_id="DOC-FOIA",
        content=foia_content,
        redacted_content=foia_content,
    )

    assert result["document_type"] == DocumentType.FOIA
    assert result["urgency"] == Urgency.IMMEDIATE
    assert result["confidence_score"] > 0
    assert not classifier.bedrock.invoke_model.called


def _mock_success_response(confidence=0.75):
    import json

    classification = json.dumps(
        {
            "document_type": "unknown",
            "sensitivity_level": "unclassified",
            "urgency": "routine",
            "subject": "Test",
            "summary": "Test",
            "action_required": "Review",
            "originating_agency": None,
            "keywords": [],
            "confidence_score": confidence,
        }
    )
    return {
        "body": Mock(
            read=Mock(
                return_value=json.dumps(
                    {"content": [{"type": "text", "text": classification}]}
                ).encode()
            )
        )
    }


def test_bedrock_failure_raises_without_explicit_fallback(classifier, monkeypatch):
    monkeypatch.delenv("DEMO_MODE", raising=False)
    monkeypatch.delenv("ALLOW_CLASSIFIER_FALLBACK", raising=False)
    classifier.bedrock.invoke_model = Mock(side_effect=RuntimeError("bedrock down"))

    with pytest.raises(RuntimeError, match="bedrock down"):
        classifier.classify_document("DOC-FAIL", "content", "content")


def test_explicit_local_fallback_is_used_when_enabled(classifier, monkeypatch):
    monkeypatch.delenv("DEMO_MODE", raising=False)
    monkeypatch.setenv("ALLOW_CLASSIFIER_FALLBACK", "true")
    classifier.bedrock.invoke_model = Mock(side_effect=RuntimeError("bedrock down"))

    result = classifier.classify_document(
        "DOC-FALLBACK",
        "FREEDOM OF INFORMATION ACT REQUEST",
        "FREEDOM OF INFORMATION ACT REQUEST",
    )

    assert result["document_type"] == DocumentType.FOIA


def test_confidence_is_clamped(classifier, monkeypatch):
    monkeypatch.delenv("DEMO_MODE", raising=False)
    monkeypatch.delenv("ALLOW_CLASSIFIER_FALLBACK", raising=False)
    classifier.bedrock.invoke_model = Mock(return_value=_mock_success_response(1.5))

    result = classifier.classify_document("DOC-CLAMP", "content", "content")

    assert result["confidence_score"] == 1.0


def test_prompt_wraps_untrusted_content_and_truncates(classifier, monkeypatch):
    import json

    monkeypatch.delenv("DEMO_MODE", raising=False)
    monkeypatch.setenv("MAX_CLASSIFICATION_CHARS", "10")
    classifier.bedrock.invoke_model = Mock(return_value=_mock_success_response())

    classifier.classify_document("DOC-PROMPT", "ignored", "0123456789ABCDEF")

    body = json.loads(classifier.bedrock.invoke_model.call_args.kwargs["body"])
    prompt = body["messages"][0]["content"]
    assert "<document>" in prompt
    assert "untrusted data" in prompt
    assert "0123456789ABCDEF" not in prompt
    assert "0123456789" in prompt


def test_output_enum_fallback_for_invalid_values(classifier, monkeypatch):
    import json

    monkeypatch.delenv("DEMO_MODE", raising=False)
    monkeypatch.delenv("ALLOW_CLASSIFIER_FALLBACK", raising=False)
    payload = json.dumps(
        {
            "document_type": "not-a-type",
            "sensitivity_level": "top-secret",
            "urgency": "someday",
            "subject": None,
            "summary": None,
            "action_required": None,
            "originating_agency": None,
            "keywords": "not-a-list",
            "confidence_score": "not-a-number",
        }
    )
    classifier.bedrock.invoke_model = Mock(
        return_value={
            "body": Mock(
                read=Mock(
                    return_value=json.dumps(
                        {"content": [{"type": "text", "text": payload}]}
                    ).encode()
                )
            )
        }
    )

    result = classifier.classify_document("DOC-INVALID", "content", "content")

    assert result["document_type"] == DocumentType.UNKNOWN
    assert result["sensitivity_level"] == SensitivityLevel.UNCLASSIFIED
    assert result["urgency"] == Urgency.ROUTINE
    assert result["keywords"] == []
    assert result["confidence_score"] == 0.0


def test_classifier_reads_environment_configuration(monkeypatch):
    monkeypatch.setenv("BEDROCK_REGION", "us-gov-east-1")
    monkeypatch.setenv("BEDROCK_MODEL_ID", "env-model-id")
    with patch("boto3.client") as client:
        classifier = ClassifierAgent()

    assert classifier.region == "us-gov-east-1"
    assert classifier.model_id == "env-model-id"
    client.assert_called_once_with("bedrock-runtime", region_name="us-gov-east-1")
