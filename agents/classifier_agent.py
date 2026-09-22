"""Classifier agent using AWS Bedrock to classify federal documents."""

import json
import logging
import os
import re
import boto3

from workflows.state import (
    DocumentType,
    SensitivityLevel,
    Urgency,
    ClassificationResult,
)

logger = logging.getLogger(__name__)


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

    @staticmethod
    def _is_demo_mode() -> bool:
        return os.environ.get("DEMO_MODE", "").lower() in ("true", "1", "yes")

    def _classify_local(self, content: str, redacted_content: str) -> ClassificationResult:
        """Rule-based classification for local demo when Bedrock is unavailable."""
        text = (redacted_content or content).lower()

        doc_type_patterns = [
            (DocumentType.FOIA, ["freedom of information act", "foia request", " foia "]),
            (DocumentType.INCIDENT_REPORT, ["security incident report", "incident report", "incident id:"]),
            (DocumentType.CONTRACT, ["contract approval", "contract number", "procurement division", "contractual details"]),
            (DocumentType.EXECUTIVE_CORRESPONDENCE, ["memorandum for chief executive", "office of the director", "congressional"]),
            (DocumentType.POLICY_MEMO, ["policy memo", "directive", "standard operating procedure"]),
            (DocumentType.PERSONNEL_ACTION, ["personnel action", "termination of employment", "new hire"]),
            (DocumentType.FINANCIAL, ["invoice", "budget request", "financial report"]),
            (DocumentType.LEGAL, ["subpoena", "legal counsel"]),
        ]

        document_type = DocumentType.UNKNOWN
        matched_keywords = []
        for doc_type, keywords in doc_type_patterns:
            hits = [kw for kw in keywords if kw in text]
            if hits:
                document_type = doc_type
                matched_keywords.extend(hits)
                break

        if re.search(r"\bsbu\b|sensitive but unclassified", text):
            sensitivity_level = SensitivityLevel.SENSITIVE_BUT_UNCLASSIFIED
        elif re.search(r"\bcui\b|controlled unclassified information", text):
            sensitivity_level = SensitivityLevel.CONTROLLED_UNCLASSIFIED
        elif re.search(r"\bfouo\b|for official use only", text):
            sensitivity_level = SensitivityLevel.FOR_OFFICIAL_USE_ONLY
        else:
            sensitivity_level = SensitivityLevel.UNCLASSIFIED

        if re.search(r"emergency|immediate action required", text):
            urgency = Urgency.EMERGENCY
        elif re.search(r"expedited processing|severity level:\s*high|within 24 hours", text):
            urgency = Urgency.IMMEDIATE
        elif re.search(r"\bpriority\b", text):
            urgency = Urgency.PRIORITY
        else:
            urgency = Urgency.ROUTINE

        agency_match = re.search(
            r"(?:to:|from:|reporting agency:)\s*([^\n]+)",
            redacted_content or content,
            re.IGNORECASE,
        )
        originating_agency = agency_match.group(1).strip() if agency_match else None

        subject_match = re.search(
            r"(?:subject|re):\s*(.+)",
            redacted_content or content,
            re.IGNORECASE,
        )
        subject = subject_match.group(1).strip() if subject_match else f"{document_type.value.replace('_', ' ').title()} Document"

        summary = (
            f"Local demo classification identified this as a {document_type.value.replace('_', ' ')} "
            f"document with {sensitivity_level.value.upper()} sensitivity."
        )

        action_map = {
            DocumentType.FOIA: "Forward to legal counsel for FOIA processing",
            DocumentType.CONTRACT: "Review and approve contract recommendation",
            DocumentType.INCIDENT_REPORT: "Escalate to security team for investigation",
            DocumentType.EXECUTIVE_CORRESPONDENCE: "Route to Chief of Staff for review",
            DocumentType.POLICY_MEMO: "Review policy changes and approve",
            DocumentType.LEGAL: "Forward to legal counsel",
        }
        action_required = action_map.get(document_type, "Review and route appropriately")

        confidence_score = min(0.70 + (0.05 * len(matched_keywords)), 0.92)

        return ClassificationResult(
            document_type=document_type,
            sensitivity_level=sensitivity_level,
            urgency=urgency,
            subject=subject,
            summary=summary,
            action_required=action_required,
            originating_agency=originating_agency,
            keywords=matched_keywords or [document_type.value],
            confidence_score=confidence_score,
        )

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

        if self._is_demo_mode():
            logger.info("DEMO_MODE enabled — using local rule-based classification")
            return self._classify_local(content, redacted_content)

        try:
            return self._classify_with_bedrock(document_id, content, redacted_content)
        except Exception as exc:
            logger.warning("Bedrock classification failed, using local fallback: %s", exc)
            return self._classify_local(content, redacted_content)

    def _classify_with_bedrock(
        self, document_id: str, content: str, redacted_content: str
    ) -> ClassificationResult:
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
