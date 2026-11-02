"""Lambda function for document intake via S3 trigger and API Gateway."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
from decimal import Decimal
from enum import Enum
from typing import Any, Dict

import boto3

from agents.supervisor import SupervisorAgent

logger = logging.getLogger()
logger.setLevel(logging.INFO)

supervisor = SupervisorAgent()

# Document ID validation pattern: alphanumeric, hyphens, underscores only
DOCUMENT_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")

DEFAULT_MAX_DOCUMENT_SIZE_MB = 100


def _validate_document_id(document_id: str) -> str:
    """
    Validate document ID to prevent injection attacks.

    Args:
        document_id: Document ID to validate

    Returns:
        Validated document ID

    Raises:
        ValueError: If document ID is invalid
    """
    if not isinstance(document_id, str) or not document_id or len(document_id) > 256:
        raise ValueError("Document ID must be a non-empty string under 256 characters")

    if not DOCUMENT_ID_PATTERN.match(document_id):
        raise ValueError("Document ID contains invalid characters")

    return document_id


def _max_document_bytes() -> int:
    raw = os.environ.get("MAX_DOCUMENT_SIZE_MB", str(DEFAULT_MAX_DOCUMENT_SIZE_MB))
    try:
        megabytes = float(raw)
    except ValueError:
        megabytes = DEFAULT_MAX_DOCUMENT_SIZE_MB
    if megabytes <= 0:
        megabytes = DEFAULT_MAX_DOCUMENT_SIZE_MB
    return int(megabytes * 1024 * 1024)


def _clean_for_dynamodb(value: Any) -> Any:
    """
    Convert a workflow state value into a DynamoDB-compatible value.

    DynamoDB rejects ``None`` and empty collections, and boto3 should receive
    numbers as ``Decimal`` (not float).  Enums are persisted by value.
    """
    if isinstance(value, Enum):
        value = value.value
    if value is None:
        return None
    if isinstance(value, (bool, int, str, bytes, Decimal)):
        return value
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, dict):
        cleaned = {
            str(key): _clean_for_dynamodb(item) for key, item in value.items()
        }
        return {
            key: item
            for key, item in cleaned.items()
            if item is not None and item != "" and item != [] and item != {}
        }
    if isinstance(value, (list, tuple, set)):
        cleaned_items = [_clean_for_dynamodb(item) for item in value]
        return [
            item
            for item in cleaned_items
            if item is not None and item != "" and item != [] and item != {}
        ]
    return str(value)


def _build_state_item(result: Dict[str, Any], document_id: str) -> Dict[str, Any]:
    """Build the DynamoDB item, excluding raw/redacted document bodies."""
    item = _clean_for_dynamodb(result)
    if not isinstance(item, dict):
        item = {}
    item["document_id"] = document_id

    # Do not persist document bodies in the workflow-state table.  The intake
    # bucket/archive remain the system of record for content, and the audit
    # trail already records PII metadata rather than raw values.
    item.pop("document_content", None)
    item.pop("document_content_redacted", None)
    return item


def _response(status_code: int, payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(payload),
    }


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Handle S3 events for document intake.

    Event structure (S3):
    {
        "Records": [{
            "s3": {
                "bucket": {"name": "intake-bucket"},
                "object": {"key": "documents/foia-request.txt"}
            }
        }]
    }

    Args:
        event: S3 event from Lambda
        context: Lambda context

    Returns:
        Lambda response with status and document processing result
    """
    try:
        records = event.get("Records", [])
        if not isinstance(records, list) or not records:
            return _response(400, {"error": "No records in event"})

        # Process all records
        results = []
        for record in records:
            try:
                s3_bucket = record["s3"]["bucket"]["name"]
                s3_key = record["s3"]["object"]["key"]

                logger.info("Processing document: s3://%s/%s", s3_bucket, s3_key)

                # Read document from S3
                s3_client = boto3.client("s3")
                response = s3_client.get_object(Bucket=s3_bucket, Key=s3_key)
                content_length = response.get("ContentLength")
                if content_length is not None and content_length > _max_document_bytes():
                    raise ValueError("Document exceeds size limit")
                content = response["Body"].read().decode("utf-8")

                # Extract document ID from S3 key and validate
                document_id = s3_key.split("/")[-1].split(".")[0]
                document_id = _validate_document_id(document_id)

                # Execute workflow
                result = asyncio.run(
                    supervisor.process_document(
                        document_id=document_id,
                        s3_key=f"s3://{s3_bucket}/{s3_key}",
                        content=content,
                    )
                )

                # Store result in DynamoDB
                dynamodb = boto3.resource("dynamodb")
                table = dynamodb.Table(
                    os.environ.get("STATE_DYNAMODB_TABLE", "document-triage-state")
                )
                table.put_item(Item=_build_state_item(result, document_id))

                logger.info("Document processing complete: %s", document_id)

                approval_status = result.get("approval_status", "pending")
                results.append(
                    {
                        "document_id": document_id,
                        "status": approval_status.value
                        if hasattr(approval_status, "value")
                        else str(approval_status),
                        "complete": bool(result.get("processing_complete")),
                    }
                )

            except (KeyError, ValueError):
                # KeyError: malformed S3 event; ValueError: invalid ID/size
                logger.error("Error processing record", exc_info=True)
                results.append({"error": "Document processing failed"})
            except Exception:
                logger.error("Error processing record", exc_info=True)
                results.append({"error": "Document processing failed"})

        return _response(
            200,
            {"message": "Batch processing complete", "results": results},
        )

    except Exception:
        logger.error("Error in lambda_handler", exc_info=True)
        return _response(500, {"error": "Document processing failed"})


def lambda_handler_api_gateway(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Handle document upload via API Gateway.

    Event structure (API Gateway):
    {
        "body": "base64-encoded document content or plain text",
        "isBase64Encoded": true|false,
        "queryStringParameters": {
            "document_id": "DOC-001",
            "document_type": "foia_request"
        }
    }

    Args:
        event: API Gateway event
        context: Lambda context

    Returns:
        Lambda response with processing result
    """
    try:
        # Parse request
        body = event.get("body", "") or ""
        is_base64_encoded = event.get("isBase64Encoded", False)
        params = event.get("queryStringParameters", {}) or {}

        document_id = params.get("document_id", "API-REQUEST")

        # Decode body based on isBase64Encoded flag
        try:
            if is_base64_encoded:
                content = base64.b64decode(body, validate=True).decode("utf-8") if body else ""
            else:
                content = body
        except (ValueError, TypeError, UnicodeDecodeError):
            logger.error("Error decoding request body", exc_info=True)
            return _response(400, {"error": "Invalid document encoding"})

        if not content:
            return _response(400, {"error": "Document content required"})

        if len(content.encode("utf-8")) > _max_document_bytes():
            return _response(413, {"error": "Document exceeds size limit"})

        # Validate document_id
        try:
            document_id = _validate_document_id(document_id)
        except ValueError:
            logger.error("Invalid document_id", exc_info=True)
            return _response(400, {"error": "Invalid document identifier"})

        # Execute workflow
        result = asyncio.run(
            supervisor.process_document(
                document_id=document_id,
                s3_key="api-gateway-upload",
                content=content,
            )
        )

        # Store result in DynamoDB
        dynamodb = boto3.resource("dynamodb")
        table = dynamodb.Table(
            os.environ.get("STATE_DYNAMODB_TABLE", "document-triage-state")
        )
        table.put_item(Item=_build_state_item(result, document_id))

        if result.get("error") or not result.get("processing_complete"):
            return _response(500, {"error": "Document processing failed"})

        return _response(200, supervisor.get_workflow_status(result))

    except Exception:
        logger.error("Error processing API request", exc_info=True)
        return _response(500, {"error": "Document processing failed"})
