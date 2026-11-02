"""Tests for the Lambda intake handlers."""

import importlib.util
import json
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from workflows.state import (
    ApprovalStatus,
    DocumentType,
    RoutingQueue,
    SensitivityLevel,
    Urgency,
)


@pytest.fixture(scope="module")
def handler_module():
    path = Path(__file__).resolve().parent.parent / "lambda" / "intake_handler.py"
    spec = importlib.util.spec_from_file_location("intake_handler_under_test", path)
    module = importlib.util.module_from_spec(spec)
    with patch("boto3.client"), patch("boto3.resource"):
        spec.loader.exec_module(module)
    return module


def test_clean_for_dynamodb_removes_unsupported_values(handler_module):
    cleaned = handler_module._clean_for_dynamodb(
        {
            "none": None,
            "empty_string": "",
            "empty_list": [],
            "empty_dict": {},
            "float": 0.95,
            "enum": ApprovalStatus.IN_REVIEW,
            "nested": {"keep": "yes", "drop": None},
            "list": [1, None, ""],
        }
    )

    assert "none" not in cleaned
    assert "empty_string" not in cleaned
    assert "empty_list" not in cleaned
    assert "empty_dict" not in cleaned
    assert cleaned["float"] == Decimal("0.95")
    assert cleaned["enum"] == "in_review"
    assert cleaned["nested"] == {"keep": "yes"}
    assert cleaned["list"] == [1]


def test_build_state_item_excludes_document_bodies(handler_module):
    item = handler_module._build_state_item(
        {
            "document_id": "DOC-1",
            "document_content": "raw PII",
            "document_content_redacted": "redacted PII",
            "processing_complete": True,
        },
        "DOC-1",
    )

    assert item["document_id"] == "DOC-1"
    assert item["processing_complete"] is True
    assert "document_content" not in item
    assert "document_content_redacted" not in item


def _api_event(body, document_id="DOC-1", base64_encoded=False):
    return {
        "body": body,
        "isBase64Encoded": base64_encoded,
        "queryStringParameters": {"document_id": document_id},
    }


def _completed_state():
    return {
        "document_id": "DOC-1",
        "approval_status": ApprovalStatus.IN_REVIEW,
        "classification": {
            "document_type": DocumentType.FOIA,
            "sensitivity_level": SensitivityLevel.UNCLASSIFIED,
            "urgency": Urgency.ROUTINE,
        },
        "routing": {
            "primary_queue": RoutingQueue.LEGAL_COUNSEL,
            "primary_reviewer_id": "legal-counsel-001",
            "sla_deadline": "2030-01-01T00:00:00+00:00",
        },
        "pii_detection": {"has_pii": False},
        "escalation_count": 0,
        "processing_complete": True,
        "error": None,
        "document_content": "raw body",
    }


def test_api_handler_rejects_missing_body(handler_module):
    response = handler_module.lambda_handler_api_gateway(_api_event(""), None)
    assert response["statusCode"] == 400
    assert json.loads(response["body"])["error"] == "Document content required"


def test_api_handler_rejects_invalid_document_id(handler_module):
    response = handler_module.lambda_handler_api_gateway(
        _api_event("hello", document_id="../etc/passwd"), None
    )
    assert response["statusCode"] == 400
    assert json.loads(response["body"])["error"] == "Invalid document identifier"


def test_api_handler_rejects_oversized_document(handler_module, monkeypatch):
    monkeypatch.setenv("MAX_DOCUMENT_SIZE_MB", "0.0001")
    response = handler_module.lambda_handler_api_gateway(
        _api_event("x" * 200), None
    )
    assert response["statusCode"] == 413


def test_api_handler_success_persists_without_content(handler_module):
    table = MagicMock()
    dynamodb = MagicMock()
    dynamodb.Table.return_value = table
    state = _completed_state()

    with patch.object(
        handler_module.supervisor, "process_document", new=AsyncMock(return_value=state)
    ), patch.object(handler_module.boto3, "resource", return_value=dynamodb):
        response = handler_module.lambda_handler_api_gateway(
            _api_event("A FOIA request body"), None
        )

    assert response["statusCode"] == 200
    payload = json.loads(response["body"])
    assert payload["status"] == "in_review"
    assert payload["complete"] is True

    item = table.put_item.call_args.kwargs["Item"]
    assert item["document_id"] == "DOC-1"
    assert "document_content" not in item


def test_s3_handler_reports_malformed_record(handler_module):
    response = handler_module.lambda_handler({"Records": [{}]}, None)

    assert response["statusCode"] == 200
    payload = json.loads(response["body"])
    assert payload["results"] == [{"error": "Document processing failed"}]


def test_s3_handler_rejects_empty_event(handler_module):
    response = handler_module.lambda_handler({}, None)
    assert response["statusCode"] == 400


def test_max_document_bytes_invalid_env_uses_default(handler_module, monkeypatch):
    monkeypatch.setenv("MAX_DOCUMENT_SIZE_MB", "not-a-number")
    assert handler_module._max_document_bytes() == 100 * 1024 * 1024


def test_api_handler_returns_500_for_incomplete_workflow(handler_module):
    table = MagicMock()
    dynamodb = MagicMock()
    dynamodb.Table.return_value = table
    state = _completed_state()
    state["processing_complete"] = False
    state["error"] = "internal detail should not leak"

    with patch.object(
        handler_module.supervisor, "process_document", new=AsyncMock(return_value=state)
    ), patch.object(handler_module.boto3, "resource", return_value=dynamodb):
        response = handler_module.lambda_handler_api_gateway(
            _api_event("A FOIA request body"), None
        )

    assert response["statusCode"] == 500
    body = json.loads(response["body"])
    assert body["error"] == "Document processing failed"
    assert "internal detail" not in response["body"]


def test_s3_handler_success_without_content_in_state(handler_module):
    s3 = MagicMock()
    s3.get_object.return_value = {
        "ContentLength": 9,
        "Body": MagicMock(read=MagicMock(return_value=b"FOIA body")),
    }
    table = MagicMock()
    dynamodb = MagicMock()
    dynamodb.Table.return_value = table
    state = _completed_state()

    event = {
        "Records": [
            {
                "s3": {
                    "bucket": {"name": "intake-bucket"},
                    "object": {"key": "documents/foia-request.txt"},
                }
            }
        ]
    }

    with patch.object(
        handler_module.supervisor, "process_document", new=AsyncMock(return_value=state)
    ), patch.object(handler_module.boto3, "client", return_value=s3), patch.object(
        handler_module.boto3, "resource", return_value=dynamodb
    ):
        response = handler_module.lambda_handler(event, None)

    assert response["statusCode"] == 200
    result = json.loads(response["body"])["results"][0]
    assert result == {
        "document_id": "foia-request",
        "status": "in_review",
        "complete": True,
    }
    item = table.put_item.call_args.kwargs["Item"]
    assert "document_content" not in item
    assert "document_content_redacted" not in item
