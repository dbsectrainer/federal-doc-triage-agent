"""Classifier agent using AWS Bedrock to classify federal documents."""

import json
import re
import boto3

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

    @staticmethod
    def _sanitize_document_id(document_id: str) -> str:
        """
        Sanitize document ID to prevent prompt injection.

        Args:
            document_id: Document ID to sanitize

        Returns:
            Sanitized document ID (alphanumeric, hyphens, underscores only)

        Raises:
            ValueError: If document ID cannot be sanitized
        """
        if not document_id:
            raise ValueError("Document ID cannot be empty")

        # Keep only safe characters
        sanitized = re.sub(r"[^a-zA-Z0-9_-]", "", document_id)

        if not sanitized:
            raise ValueError("Document ID contains no valid characters")

        # Limit length to prevent abuse
        if len(sanitized) > 256:
            sanitized = sanitized[:256]

        return sanitized

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

        Raises:
            ValueError: If document_id is invalid or response parsing fails
        """
        # Sanitize document_id to prevent prompt injection
        document_id = self._sanitize_document_id(document_id)

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

        # Parse response with validation
        try:
            response_body = json.loads(response["body"].read())
        except json.JSONDecodeError as e:
            raise ValueError(f"Failed to parse Bedrock response: {str(e)}")

        # Validate response structure
        if "content" not in response_body or not response_body["content"]:
            raise ValueError("Bedrock response missing content block")

        content_block = response_body["content"][0]

        # Validate content block type
        if content_block.get("type") != "text":
            raise ValueError(f"Unexpected content block type: {content_block.get('type')}")

        # Parse classification JSON
        try:
            classification_json = json.loads(content_block["text"])
        except json.JSONDecodeError as e:
            raise ValueError(f"Failed to parse classification JSON: {str(e)}")

        # Map string enums with fallback to UNKNOWN/defaults
        try:
            document_type = DocumentType(classification_json.get("document_type", "unknown"))
        except ValueError:
            document_type = DocumentType.UNKNOWN

        try:
            sensitivity_level = SensitivityLevel(classification_json.get("sensitivity_level", "unclassified"))
        except ValueError:
            sensitivity_level = SensitivityLevel.UNCLASSIFIED

        try:
            urgency = Urgency(classification_json.get("urgency", "routine"))
        except ValueError:
            urgency = Urgency.ROUTINE

        return ClassificationResult(
            document_type=document_type,
            sensitivity_level=sensitivity_level,
            urgency=urgency,
            subject=classification_json.get("subject", ""),
            summary=classification_json.get("summary", ""),
            action_required=classification_json.get("action_required", ""),
            originating_agency=classification_json.get("originating_agency"),
            keywords=classification_json.get("keywords", []),
            confidence_score=float(classification_json.get("confidence_score", 0.0)),
        )
