"""Supervisor agent for multi-agent orchestration."""

import asyncio
import logging
from typing import Any, Dict

from workflows.audit_context import close_audit_scope, open_audit_scope
from workflows.graph import create_workflow
from workflows.state import TriageState, initial_state

logger = logging.getLogger(__name__)


class SupervisorAgent:
    """
    Main orchestrator that coordinates all other agents through LangGraph.

    Responsibilities:
    1. Initialize workflow state
    2. Invoke the compiled LangGraph
    3. Handle exceptions and return a final disposition

    Each call gets an isolated audit scope so concurrent documents cannot
    interleave or clear each other's audit trails.
    """

    def __init__(self):
        self.workflow = create_workflow()
        self.max_retries = 3

    async def process_document(
        self, document_id: str, s3_key: str, content: str
    ) -> Dict[str, Any]:
        """
        Execute the full document triage workflow.

        Args:
            document_id: Document identifier
            s3_key: S3 path to original document
            content: Document content (already extracted from file)

        Returns:
            Final workflow state with all classifications, routing, and audit trail
        """
        token = open_audit_scope()
        try:
            # Initialize workflow state
            state = initial_state(
                document_id=document_id,
                s3_key=s3_key,
                content=content,
            )

            logger.info("Starting document triage for %s", document_id)

            # Execute workflow
            final_state = await self.workflow.ainvoke(state)

            logger.info(
                "Document triage complete for %s: status=%s",
                document_id,
                final_state["approval_status"],
            )

            return final_state

        except Exception:
            logger.exception("Document triage failed for %s", document_id)
            raise
        finally:
            close_audit_scope(token)

    async def process_documents_batch(
        self, documents: list[Dict[str, str]]
    ) -> list[Dict[str, Any]]:
        """
        Process multiple documents concurrently.

        Args:
            documents: List of {document_id, s3_key, content} dicts

        Returns:
            List of final states for each document
        """
        tasks = [
            self.process_document(
                document_id=doc["document_id"],
                s3_key=doc["s3_key"],
                content=doc["content"],
            )
            for doc in documents
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Handle any exceptions
        final_results = []
        for i, result in enumerate(results):
            if isinstance(result, BaseException):
                logger.error("Batch processing error for doc %s: %s", i, result)
                final_results.append(
                    {
                        "error": str(result),
                        "document_id": documents[i].get("document_id"),
                    }
                )
            else:
                final_results.append(result)

        return final_results

    def get_workflow_status(self, state: TriageState) -> Dict[str, Any]:
        """Get human-readable workflow status from state."""

        def enum_value(value):
            return value.value if hasattr(value, "value") else value

        classification = state.get("classification")
        routing = state.get("routing")
        pii_detection = state.get("pii_detection")
        return {
            "document_id": state["document_id"],
            "status": enum_value(state["approval_status"]),
            "document_type": enum_value(classification["document_type"]) if classification else None,
            "sensitivity": enum_value(classification["sensitivity_level"]) if classification else None,
            "urgency": enum_value(classification["urgency"]) if classification else None,
            "assigned_queue": enum_value(routing["primary_queue"]) if routing else None,
            "assigned_reviewer": routing["primary_reviewer_id"] if routing else None,
            "sla_deadline": routing["sla_deadline"] if routing else None,
            "has_pii": pii_detection["has_pii"] if pii_detection else False,
            "escalations": state["escalation_count"],
            "complete": state["processing_complete"],
            "error": state.get("error"),
        }
