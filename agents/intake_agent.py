"""Intake agent for document parsing and PII redaction."""

import re
import logging
import boto3

from workflows.state import PIIDetection

logger = logging.getLogger(__name__)


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

            entities = response.get("Entities", [])
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
                redaction_applied=True,
                detected_entities=detected_entities,
            )
        except Exception as e:
            # Fallback: regex-based detection
            logger.warning("Comprehend failed, falling back to regex: %s", e)
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
        detected_entities = []
        total_count = 0

        for entity_type, pattern in patterns.items():
            for match in re.finditer(pattern, text):
                entity_types.append(entity_type)
                detected_entities.append({
                    "text": match.group(),
                    "type": entity_type,
                    "start": match.start(),
                    "end": match.end(),
                })
                total_count += 1

        # Remove duplicates from entity_types
        entity_types = list(set(entity_types))

        return PIIDetection(
            has_pii=total_count > 0,
            entity_types=entity_types,
            entity_count=total_count,
            redaction_applied=True,
            detected_entities=detected_entities,
        )

    def _redact_pii(self, text: str, pii_detection: PIIDetection) -> str:
        """
        Redact PII from text based on detection results.

        Replaces identified PII patterns with [REDACTED:TYPE] placeholders.
        Handles both Comprehend-detected entities and regex-based fallback patterns.
        """
        if not pii_detection["has_pii"]:
            return text

        redacted = text

        # If we have detected_entities from Comprehend, redact them directly by position
        if pii_detection.get("detected_entities"):
            # Sort entities by start position in reverse order to maintain positions
            sorted_entities = sorted(
                pii_detection["detected_entities"],
                key=lambda e: e["start"],
                reverse=True
            )
            # Replace from end to start to avoid position shifts
            for entity in sorted_entities:
                replacement = f"[REDACTED:{entity['type']}]"
                redacted = (
                    redacted[: entity["start"]]
                    + replacement
                    + redacted[entity["end"] :]
                )
        else:
            # Fallback: use regex patterns for entity types
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
        """
        Extract text from PDF using AWS Textract with polling.

        Args:
            document_id: Document identifier
            s3_key: S3 path in format "bucket/key" or "bucket"

        Returns:
            Extracted text from PDF, or error message if extraction fails
        """
        import time

        try:
            # Parse S3 path
            parts = s3_key.split("/", 1)
            bucket = parts[0]
            key = parts[1] if len(parts) > 1 else parts[0]

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

                elif job_status == "FAILED":
                    error_msg = f"Textract job failed for {document_id}"
                    logger.error(error_msg)
                    return f"[Error: {error_msg}]"

                # Still processing, wait and retry
                time.sleep(poll_interval)

            # Timeout reached
            error_msg = f"Textract job timeout after {timeout_seconds}s for {document_id}"
            logger.error(error_msg)
            return f"[Error: {error_msg}]"

        except Exception as e:
            error_msg = f"Error extracting PDF {document_id}: {str(e)}"
            logger.error(error_msg)
            return f"[Error: {error_msg}]"

    def normalize_document(self, content: str) -> str:
        """Normalize document content for processing."""
        # Remove excessive whitespace
        normalized = re.sub(r"\n{3,}", "\n\n", content)
        normalized = re.sub(r"[ \t]{2,}", " ", normalized)

        return normalized.strip()
