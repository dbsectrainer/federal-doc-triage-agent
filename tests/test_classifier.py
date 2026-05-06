"""Tests for classifier agent."""

import pytest
from unittest.mock import Mock, patch

from agents.classifier_agent import ClassifierAgent
from workflows.state import DocumentType, SensitivityLevel, Urgency


@pytest.fixture
def classifier():
    """Create a classifier agent with mocked Bedrock client."""
    with patch("boto3.client"):
        return ClassifierAgent()


def test_classifier_initialization():
    """Test classifier agent initialization."""
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
