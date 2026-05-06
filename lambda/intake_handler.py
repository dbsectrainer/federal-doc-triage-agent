"""Lambda function for document intake via S3 trigger."""

import json
import os
import asyncio
import logging
import re
from typing import Any, Dict

import boto3

from agents.supervisor import SupervisorAgent

logger = logging.getLogger()
logger.setLevel(logging.INFO)

supervisor = SupervisorAgent()

# Document ID validation pattern: alphanumeric, hyphens, underscores only
DOCUMENT_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")


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
    if not document_id or len(document_id) > 256:
        raise ValueError("Document ID must be non-empty and under 256 characters")

    if not DOCUMENT_ID_PATTERN.match(document_id):
        raise ValueError("Document ID contains invalid characters")

    return document_id


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

        if not records:
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "No records in event"}),
            }

        # Process all records
        results = []
        for record in records:
            try:
                s3_bucket = record["s3"]["bucket"]["name"]
                s3_key = record["s3"]["object"]["key"]

                logger.info(f"Processing document: s3://{s3_bucket}/{s3_key}")

                # Read document from S3
                s3_client = boto3.client("s3")
                response = s3_client.get_object(Bucket=s3_bucket, Key=s3_key)
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
                table = dynamodb.Table(os.environ.get("STATE_DYNAMODB_TABLE", "document-triage-state"))

                # Convert enums to strings for JSON serialization
                result_json = json.loads(json.dumps(result, default=str))
                result_json["document_id"] = document_id

                table.put_item(Item=result_json)

                logger.info(f"Document processing complete: {document_id}")

                approval_status = result.get("approval_status", "pending")
                results.append({
                    "document_id": document_id,
                    "status": approval_status.value if hasattr(approval_status, "value") else str(approval_status),
                })

            except (KeyError, ValueError) as e:
                # KeyError: malformed S3 event; ValueError: invalid document_id
                logger.error(f"Error processing record: {str(e)}", exc_info=True)
                results.append({"error": "Document processing failed"})
            except Exception as e:
                logger.error(f"Error processing record: {str(e)}", exc_info=True)
                results.append({"error": "Document processing failed"})

        return {
            "statusCode": 200,
            "body": json.dumps({
                "message": "Batch processing complete",
                "results": results,
            }),
        }

    except Exception as e:
        logger.error("Error in lambda_handler: %s", str(e), exc_info=True)
        return {
            "statusCode": 500,
            "body": json.dumps({"error": "Document processing failed"}),
        }


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
        import base64

        # Parse request
        body = event.get("body", "")
        is_base64_encoded = event.get("isBase64Encoded", False)
        params = event.get("queryStringParameters", {}) or {}

        document_id = params.get("document_id", "API-REQUEST")

        # Decode body based on isBase64Encoded flag
        try:
            if is_base64_encoded:
                content = base64.b64decode(body).decode("utf-8") if body else ""
            else:
                content = body
        except (ValueError, TypeError) as e:
            logger.error("Error decoding request body: %s", str(e))
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "Invalid document encoding"}),
            }

        if not content:
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "Document content required"}),
            }

        # Validate document_id
        try:
            document_id = _validate_document_id(document_id)
        except ValueError as e:
            logger.error("Invalid document_id: %s", str(e))
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "Invalid document identifier"}),
            }

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
        table = dynamodb.Table(os.environ.get("STATE_DYNAMODB_TABLE", "document-triage-state"))

        result_json = json.loads(json.dumps(result, default=str))
        result_json["document_id"] = document_id

        table.put_item(Item=result_json)

        return {
            "statusCode": 200,
            "body": json.dumps(
                supervisor.get_workflow_status(result),
            ),
        }

    except Exception as e:
        logger.error("Error processing API request: %s", str(e), exc_info=True)
        return {
            "statusCode": 500,
            "body": json.dumps({"error": "Document processing failed"}),
        }
