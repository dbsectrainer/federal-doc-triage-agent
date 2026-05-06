"""Lambda function for document intake via S3 trigger."""

import json
import asyncio
import logging
from typing import Any, Dict

from agents.supervisor import SupervisorAgent

logger = logging.getLogger()
logger.setLevel(logging.INFO)

supervisor = SupervisorAgent()


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
            return {"statusCode": 400, "body": "No records in event"}

        # Process first record (typically only one per invocation)
        record = records[0]
        s3_bucket = record["s3"]["bucket"]["name"]
        s3_key = record["s3"]["object"]["key"]

        logger.info(f"Processing document: s3://{s3_bucket}/{s3_key}")

        # Read document from S3
        s3_client = __import__("boto3").client("s3")
        response = s3_client.get_object(Bucket=s3_bucket, Key=s3_key)
        content = response["Body"].read().decode("utf-8")

        # Extract document ID from S3 key
        document_id = s3_key.split("/")[-1].split(".")[0]

        # Execute workflow
        result = asyncio.run(
            supervisor.process_document(
                document_id=document_id,
                s3_key=f"s3://{s3_bucket}/{s3_key}",
                content=content,
            )
        )

        # Store result in DynamoDB
        dynamodb = __import__("boto3").resource("dynamodb")
        table = dynamodb.Table(__import__("os").environ.get("STATE_DYNAMODB_TABLE", "document-triage-state"))

        # Convert enums to strings for JSON serialization
        result_json = json.loads(json.dumps(result, default=str))
        result_json["document_id"] = document_id

        table.put_item(Item=result_json)

        logger.info(f"Document processing complete: {document_id}")

        return {
            "statusCode": 200,
            "body": json.dumps(
                {
                    "message": "Document processed successfully",
                    "document_id": document_id,
                    "status": result.get("approval_status", "pending"),
                }
            ),
        }

    except Exception as e:
        logger.error(f"Error processing document: {str(e)}", exc_info=True)
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)}),
        }


def lambda_handler_api_gateway(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Handle document upload via API Gateway.

    Event structure (API Gateway):
    {
        "body": "base64-encoded document content",
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
        params = event.get("queryStringParameters", {}) or {}

        document_id = params.get("document_id", "API-REQUEST")
        content = base64.b64decode(body).decode("utf-8") if body else ""

        if not content:
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "Document content required"}),
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
        dynamodb = __import__("boto3").resource("dynamodb")
        table = dynamodb.Table(__import__("os").environ.get("STATE_DYNAMODB_TABLE", "document-triage-state"))

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
        logger.error(f"Error processing API request: {str(e)}", exc_info=True)
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)}),
        }
