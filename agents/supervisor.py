"""Supervisor agent for multi-agent orchestration."""

import asyncio
import logging
from typing import Dict, Any

from workflows.state import TriageState, initial_state
from workflows.graph import create_workflow

logger = logging.getLogger(__name__)


class SupervisorAgent:
    """
    Main orchestrator that coordinates all other agents through LangGraph.

    Responsibilities:
    1. Initialize workflow state
    2. Invoke the compiled LangGraph
    3. Handle exceptions and retries
    4. Return final disposition
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
        try:
            # Initialize workflow state
            state = initial_state(
                document_id=document_id,
                s3_key=s3_key,
                content=content,
            )

            logger.info(f"Starting document triage for {document_id}")

            # Execute workflow
            final_state = await self.workflow.ainvoke(state)

            logger.info(
                f"Document triage complete for {document_id}: "
                f"status={final_state['approval_status']}"
            )

            return final_state

        except Exception as e:
            logger.error(f"Document triage failed for {document_id}: {str(e)}", exc_info=True)
            raise

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
            if isinstance(result, Exception):
                logger.error(f"Batch processing error for doc {i}: {result}")
                final_results.append({"error": str(result), "document_id": documents[i].get("document_id")})
            else:
                final_results.append(result)

        return final_results

    def get_workflow_status(self, state: TriageState) -> Dict[str, Any]:
        """Get human-readable workflow status from state."""
        return {
            "document_id": state["document_id"],
            "status": state["approval_status"].value,
            "document_type": state["classification"]["document_type"].value if state["classification"] else None,
            "sensitivity": state["classification"]["sensitivity_level"].value if state["classification"] else None,
            "urgency": state["classification"]["urgency"].value if state["classification"] else None,
            "assigned_queue": state["routing"]["primary_queue"].value if state["routing"] else None,
            "assigned_reviewer": state["routing"]["primary_reviewer_id"] if state["routing"] else None,
            "sla_deadline": state["routing"]["sla_deadline"] if state["routing"] else None,
            "has_pii": state["pii_detection"]["has_pii"] if state["pii_detection"] else False,
            "escalations": state["escalation_count"],
            "complete": state["processing_complete"],
        }
