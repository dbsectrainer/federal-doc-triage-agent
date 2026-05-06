"""Classifier agent using AWS Bedrock to classify federal documents."""

import json
import boto3
from typing import Optional

from workflows.state import (
    DocumentType,
    SensitivityLevel,
    Urgency,
    ClassificationResult,
)


class ClassifierAgent:
    """Uses Claude 3 Sonnet on Bedrock to classify documents."""

    def __init__(self, region: str = "us-gov-west-1", model_id: str = None):
        self.bedrock = boto3.client("bedrock-runtime", region_name=region)
        self.model_id = model_id or "anthropic.claude-3-sonnet-20240229-v1:0"

    def classify_document(
        self, document_id: str, content: str, redacted_content: str
    ) -> ClassificationResult:
        """
        Classify a federal document using Claude 3 Sonnet.

        Args:
            document_id: Document identifier
            content: Full document content (for context)
            redacted_content: PII-redacted content (sent to LLM)

        Returns:
            ClassificationResult with type, sensitivity, urgency, etc.
        """

        prompt = f"""You are a federal document classification expert. Analyze the following document and classify it using the schema provided.

DOCUMENT ID: {document_id}

DOCUMENT CONTENT:
{redacted_content}

Classify this document with the following schema:

{{
    "document_type": "<one of: contract, foia, policy_memo, incident_report, personnel_action, financial, executive_correspondence, legal, unknown>",
    "sensitivity_level": "<one of: unclassified, cui, sbu, fouo>",
    "urgency": "<one of: routine, priority, immediate, emergency>",
    "subject": "<brief subject line>",
    "summary": "<2-3 sentence summary of document content and purpose>",
    "action_required": "<specific action required: e.g., 'Review and sign', 'Forward to legal', 'No action required'>",
    "originating_agency": "<federal agency name or null if unknown>",
    "keywords": ["<keyword1>", "<keyword2>", ...],
    "confidence_score": <0.0-1.0>
}}

Respond ONLY with the JSON object. No other text."""

        response = self.bedrock.invoke_model(
            modelId=self.model_id,
            contentType="application/json",
            accept="application/json",
            body=json.dumps(
                {
                    "anthropic_version": "bedrock-2023-06-01",
                    "max_tokens": 1024,
                    "messages": [{"role": "user", "content": prompt}],
                }
            ),
        )

        # Parse response
        response_body = json.loads(response["body"].read())
        content_block = response_body["content"][0]
        classification_json = json.loads(content_block["text"])

        # Map string enums
        return ClassificationResult(
            document_type=DocumentType(classification_json["document_type"]),
            sensitivity_level=SensitivityLevel(classification_json["sensitivity_level"]),
            urgency=Urgency(classification_json["urgency"]),
            subject=classification_json["subject"],
            summary=classification_json["summary"],
            action_required=classification_json["action_required"],
            originating_agency=classification_json.get("originating_agency"),
            keywords=classification_json["keywords"],
            confidence_score=classification_json["confidence_score"],
        )
