"""Tests for audit event persistence."""

from unittest.mock import MagicMock, patch

import pytest

from agents.auditor_agent import AuditorAgent


class FakeBatchWriter:
    def __init__(self, table):
        self.table = table

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def put_item(self, Item):
        self.table.items.append(Item)


@pytest.fixture
def auditor():
    table = MagicMock()
    table.items = []
    table.batch_writer.side_effect = lambda: FakeBatchWriter(table)
    dynamodb = MagicMock()
    dynamodb.Table.return_value = table

    with patch("boto3.resource", return_value=dynamodb):
        agent = AuditorAgent()
        agent.table = table
        return agent


def test_persist_uses_table_key_schema(auditor):
    auditor.log_classification("DOC-1", "foia", 0.9)
    auditor.log_routing("DOC-1", "legal_counsel", "policy_office", "2030-01-01T00:00:00+00:00")

    assert auditor.persist_to_dynamodb("document-triage-audit") is True

    assert len(auditor.table.items) == 2
    for item in auditor.table.items:
        assert item["document_id"] == "DOC-1"
        assert item["timestamp"]
        assert item["event_id"]
        assert item["event_type"] == "WORKFLOW_ACTION"
        assert isinstance(item["metadata"], str)


def test_persist_rejects_event_without_document_id(auditor):
    auditor.log_event(agent="test", action="test", outcome="success", metadata={})

    assert auditor.persist_to_dynamodb("document-triage-audit") is False
    assert auditor.table.items == []


def test_persist_empty_trail_is_success(auditor):
    assert auditor.persist_to_dynamodb("document-triage-audit") is True
    assert auditor.table.items == []


def test_get_audit_trail_returns_copy(auditor):
    auditor.log_event(agent="test", action="test", outcome="success", metadata={"document_id": "D"})
    trail = auditor.get_audit_trail()
    trail.clear()
    assert len(auditor.get_audit_trail()) == 1
