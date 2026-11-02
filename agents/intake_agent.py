"""Intake agent for document parsing and PII redaction."""

from __future__ import annotations

import logging
import os
import re

import boto3

from workflows.state import PIIDetection

logger = logging.getLogger(__name__)

# Comprehend's synchronous DetectPiiEntities API accepts at most 100 KB of
# UTF-8 text.  Larger documents use the regex fallback instead of failing the
# AWS call and waiting for an exception.
COMPREHEND_MAX_BYTES = 100_000

PII_PATTERNS = {
    "SSN": r"\b\d{3}-\d{2}-\d{4}\b",
    "EMAIL": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
    "PHONE": r"\b(?:\+?1[-.\s]?)?\(?[0-9]{3}\)?[-.\s]?[0-9]{3}[-.\s]?[0-9]{4}\b",
    "CREDIT_CARD": r"\b(?:\d{4}[-\s]?){3}\d{4}\b",
    "DATE_OF_BIRTH": r"\b(?:0?[1-9]|1[0-2])/(?:0?[1-9]|[12][0-9]|3[01])/(?:19|20)\d{2}\b",
}

REDACTION_PATTERNS = {
    "SSN": (r"\b\d{3}-\d{2}-\d{4}\b", "[REDACTED:SSN]"),
    "EMAIL": (r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", "[REDACTED:EMAIL]"),
    "PHONE": (
        r"\b(?:\+?1[-.\s]?)?\(?[0-9]{3}\)?[-.\s]?[0-9]{3}[-.\s]?[0-9]{4}\b",
        "[REDACTED:PHONE]",
    ),
    "CREDIT_CARD": (r"\b(?:\d{4}[-\s]?){3}\d{4}\b", "[REDACTED:CREDIT_CARD]"),
    "DATE_OF_BIRTH": (
        r"\b(?:0?[1-9]|1[0-2])/(?:0?[1-9]|[12][0-9]|3[01])/(?:19|20)\d{2}\b",
        "[REDACTED:DATE_OF_BIRTH]",
    ),
}


class IntakeAgent:
    """Handles document parsing, format detection, and PII redaction."""

    def __init__(self, region: str = None):
        self.region = (
            region
            or os.environ.get("AWS_REGION")
            or os.environ.get("BEDROCK_REGION")
            or "us-gov-west-1"
        )
        self.comprehend = boto3.client("comprehend", region_name=self.region)
        self.textract = boto3.client("textract", region_name=self.region)

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

    @staticmethod
    def _confidence_threshold() -> float:
        raw = os.environ.get("REDACTION_CONFIDENCE_THRESHOLD", "0.8")
        try:
            value = float(raw)
        except ValueError:
            return 0.8
        return min(max(value, 0.0), 1.0)

    def _detect_pii(self, text: str) -> PIIDetection:
        """
        Detect Personally Identifiable Information in text.

        Uses AWS Comprehend for ML-based detection with fallback to regex patterns.
        """
        use_comprehend = os.environ.get("USE_COMPREHEND", "true").lower() in (
            "true",
            "1",
            "yes",
        )
        if not use_comprehend:
            return self._detect_pii_regex(text)

        if len(text.encode("utf-8")) > COMPREHEND_MAX_BYTES:
            logger.info("Document exceeds Comprehend synchronous limit; using regex PII detection")
            return self._detect_pii_regex(text)

        try:
            # AWS Comprehend PII detection
            response = self.comprehend.detect_pii_entities(Text=text, LanguageCode="en")

            threshold = self._confidence_threshold()
            entities = [
                entity
                for entity in response.get("Entities", [])
                if float(entity.get("Score", 1.0)) >= threshold
            ]
            entity_types = list(set(entity["Type"] for entity in entities))
            entity_count = len(entities)

            # Convert Comprehend entities to dict format with text content
            detected_entities = [
                {
                    "text": text[entity["BeginOffset"] : entity["EndOffset"]],
                    "type": entity["Type"],
                    "start": entity["BeginOffset"],
                    "end": entity["EndOffset"],
                }
                for entity in entities
            ]

            return PIIDetection(
                has_pii=entity_count > 0,
                entity_types=entity_types,
                entity_count=entity_count,
                redaction_applied=entity_count > 0,
                detected_entities=detected_entities,
            )
        except Exception as exc:
            # Fallback: regex-based detection
            logger.warning("Comprehend failed, falling back to regex: %s", exc)
            return self._detect_pii_regex(text)

    def _detect_pii_regex(self, text: str) -> PIIDetection:
        """Fallback PII detection using regex patterns."""
        matches = []
        for entity_type, pattern in PII_PATTERNS.items():
            for match in re.finditer(pattern, text):
                matches.append(
                    {
                        "text": match.group(),
                        "type": entity_type,
                        "start": match.start(),
                        "end": match.end(),
                    }
                )

        # Resolve overlaps deterministically by preferring the longest match at
        # each position.  Without this, a phone number inside a credit-card
        # string (or vice versa) would produce overlapping replacements.
        matches.sort(key=lambda entity: (entity["start"], -(entity["end"] - entity["start"])))
        selected = []
        last_end = -1
        for entity in matches:
            if entity["start"] >= last_end:
                selected.append(entity)
                last_end = entity["end"]

        selected.sort(key=lambda entity: entity["start"])
        entity_types = sorted({entity["type"] for entity in selected})

        return PIIDetection(
            has_pii=bool(selected),
            entity_types=entity_types,
            entity_count=len(selected),
            redaction_applied=bool(selected),
            detected_entities=selected,
        )

    def _redact_pii(self, text: str, pii_detection: PIIDetection) -> str:
        """
        Redact PII from text based on detection results.

        Replaces identified PII spans with ``[REDACTED:TYPE]`` placeholders.
        Detected spans are applied from right to left so earlier offsets stay
        valid.
        """
        if not pii_detection["has_pii"]:
            return text

        entities = pii_detection.get("detected_entities") or []
        if entities:
            redacted = text
            for entity in sorted(entities, key=lambda item: item["start"], reverse=True):
                start = max(int(entity["start"]), 0)
                end = min(int(entity["end"]), len(redacted))
                if start >= end:
                    continue
                replacement = f"[REDACTED:{entity['type']}]"
                redacted = redacted[:start] + replacement + redacted[end:]
            return redacted

        # Defensive fallback for callers that supply entity types but no spans.
        redacted = text
        for entity_type in pii_detection["entity_types"]:
            pattern_and_replacement = REDACTION_PATTERNS.get(entity_type)
            if pattern_and_replacement:
                pattern, replacement = pattern_and_replacement
                redacted = re.sub(pattern, replacement, redacted, flags=re.IGNORECASE)
        return redacted

    def extract_text_from_pdf(self, document_id: str, s3_key: str) -> str:
        """
        Extract text from PDF using AWS Textract with polling.

        Args:
            document_id: Document identifier
            s3_key: S3 path in format "bucket/key"

        Returns:
            Extracted text from PDF, or error message if extraction fails
        """
        import time

        try:
            # Parse S3 path
            parts = s3_key.split("/", 1)
            if len(parts) != 2 or not parts[0] or not parts[1]:
                raise ValueError("s3_key must be in 'bucket/key' format")
            bucket, key = parts

            # Start async text detection job
            response = self.textract.start_document_text_detection(
                DocumentLocation={"S3Object": {"Bucket": bucket, "Name": key}}
            )
            job_id = response["JobId"]

            # Poll for job completion (5-minute timeout)
            start_time = time.time()
            timeout_seconds = 300
            poll_interval = 2

            while time.time() - start_time < timeout_seconds:
                result = self.textract.get_document_text_detection(JobId=job_id)
                job_status = result["JobStatus"]

                if job_status == "SUCCEEDED":
                    # Extract text from blocks
                    text_blocks = [
                        block["Text"]
                        for block in result.get("Blocks", [])
                        if block["BlockType"] == "LINE"
                    ]
                    extracted_text = "\n".join(text_blocks)
                    logger.info(
                        "Extracted %d characters from PDF %s",
                        len(extracted_text),
                        document_id,
                    )
                    return extracted_text

                if job_status == "FAILED":
                    error_msg = f"Textract job failed for {document_id}"
                    logger.error(error_msg)
                    return f"[Error: {error_msg}]"

                # Still processing, wait and retry
                time.sleep(poll_interval)

            # Timeout reached
            error_msg = f"Textract job timeout after {timeout_seconds}s for {document_id}"
            logger.error(error_msg)
            return f"[Error: {error_msg}]"

        except Exception as exc:
            error_msg = f"Error extracting PDF {document_id}: {exc}"
            logger.error(error_msg)
            return f"[Error: {error_msg}]"

    def normalize_document(self, content: str) -> str:
        """Normalize document content for processing."""
        # Remove excessive whitespace
        normalized = re.sub(r"\n{3,}", "\n\n", content)
        normalized = re.sub(r"[ \t]{2,}", " ", normalized)

        return normalized.strip()
