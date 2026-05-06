"""Intake agent for document parsing and PII redaction."""

import re
import json
import boto3
from typing import Optional

from workflows.state import PIIDetection


class IntakeAgent:
    """Handles document parsing, format detection, and PII redaction."""

    def __init__(self, region: str = "us-gov-west-1"):
        self.region = region
        self.comprehend = boto3.client("comprehend", region_name=region)
        self.textract = boto3.client("textract", region_name=region)

    def process_document(self, document_id: str, content: str) -> tuple[str, PIIDetection]:
        """
        Process a document: detect PII and redact sensitive data.

        Args:
            document_id: Document identifier
            content: Raw document content

        Returns:
            Tuple of (redacted_content, pii_detection_metadata)
        """
        # Detect PII using AWS Comprehend
        pii_detection = self._detect_pii(content)

        # Redact PII from content
        redacted_content = self._redact_pii(content, pii_detection)

        return redacted_content, pii_detection

    def _detect_pii(self, text: str) -> PIIDetection:
        """
        Detect Personally Identifiable Information in text.

        Uses AWS Comprehend for ML-based detection with fallback to regex patterns.
        """
        try:
            # AWS Comprehend PII detection
            response = self.comprehend.detect_pii_entities(Text=text, LanguageCode="en")

            entity_types = list(set(entity["Type"] for entity in response.get("Entities", [])))
            entity_count = len(response.get("Entities", []))

            return PIIDetection(
                has_pii=entity_count > 0,
                entity_types=entity_types,
                entity_count=entity_count,
                redaction_applied=True,
            )
        except Exception:
            # Fallback: regex-based detection
            return self._detect_pii_regex(text)

    def _detect_pii_regex(self, text: str) -> PIIDetection:
        """Fallback PII detection using regex patterns."""
        patterns = {
            "SSN": r"\b\d{3}-\d{2}-\d{4}\b",
            "EMAIL": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
            "PHONE": r"\b(?:\+?1[-.\s]?)?\(?[0-9]{3}\)?[-.\s]?[0-9]{3}[-.\s]?[0-9]{4}\b",
            "CREDIT_CARD": r"\b(?:\d{4}[-\s]?){3}\d{4}\b",
            "DATE_OF_BIRTH": r"\b(?:0?[1-9]|1[0-2])/(?:0?[1-9]|[12][0-9]|3[01])/(?:19|20)\d{2}\b",
        }

        entity_types = []
        total_count = 0

        for entity_type, pattern in patterns.items():
            matches = re.findall(pattern, text)
            if matches:
                entity_types.append(entity_type)
                total_count += len(matches)

        return PIIDetection(
            has_pii=total_count > 0,
            entity_types=entity_types,
            entity_count=total_count,
            redaction_applied=True,
        )

    def _redact_pii(self, text: str, pii_detection: PIIDetection) -> str:
        """
        Redact PII from text based on detection results.

        Replaces identified PII patterns with [REDACTED] placeholders.
        """
        if not pii_detection["has_pii"]:
            return text

        redacted = text
        redaction_patterns = {
            "SSN": (r"\b\d{3}-\d{2}-\d{4}\b", "[REDACTED:SSN]"),
            "EMAIL": (r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b", "[REDACTED:EMAIL]"),
            "PHONE": (r"\b(?:\+?1[-.\s]?)?\(?[0-9]{3}\)?[-.\s]?[0-9]{3}[-.\s]?[0-9]{4}\b", "[REDACTED:PHONE]"),
            "CREDIT_CARD": (r"\b(?:\d{4}[-\s]?){3}\d{4}\b", "[REDACTED:CC]"),
            "DATE_OF_BIRTH": (r"\b(?:0?[1-9]|1[0-2])/(?:0?[1-9]|[12][0-9]|3[01])/(?:19|20)\d{2}\b", "[REDACTED:DOB]"),
        }

        for entity_type in pii_detection["entity_types"]:
            if entity_type in redaction_patterns:
                pattern, replacement = redaction_patterns[entity_type]
                redacted = re.sub(pattern, replacement, redacted, flags=re.IGNORECASE)

        return redacted

    def extract_text_from_pdf(self, document_id: str, s3_key: str) -> str:
        """Extract text from PDF using AWS Textract."""
        try:
            # Parse S3 path
            parts = s3_key.split("/", 1)
            bucket = parts[0]
            key = parts[1] if len(parts) > 1 else parts[0]

            response = self.textract.start_document_text_detection(
                DocumentLocation={"S3Object": {"Bucket": bucket, "Name": key}}
            )

            # Note: In production, would need to poll job status and retrieve results
            # This is a simplified example
            return f"[PDF extracted from {s3_key}]"
        except Exception as e:
            return f"[Error extracting PDF: {str(e)}]"

    def normalize_document(self, content: str) -> str:
        """Normalize document content for processing."""
        # Remove excessive whitespace
        normalized = re.sub(r"\n{3,}", "\n\n", content)
        normalized = re.sub(r"[ \t]{2,}", " ", normalized)

        return normalized.strip()
