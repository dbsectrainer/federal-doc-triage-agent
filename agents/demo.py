"""Demo runner for local testing of the triage workflow."""

import asyncio
import json
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()
# Demo runner works without AWS credentials
os.environ["DEMO_MODE"] = "true"
os.environ["USE_COMPREHEND"] = "false"
logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(levelname)s %(name)s: %(message)s",
)
# Avoid noisy SDK/credential-provider logs in the CLI demo.  Application logs
# remain at the configured LOG_LEVEL.
logging.getLogger("botocore").setLevel(logging.WARNING)
logging.getLogger("boto3").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)

from agents.supervisor import SupervisorAgent  # noqa: E402  (must follow demo env setup)


async def run_demo(document_path: str) -> int:
    """Run a demo triage workflow with a sample document."""

    # Read sample document
    doc_path = Path(document_path)
    if not doc_path.exists():
        print(f"Error: Document not found at {document_path}")
        return 1

    with open(doc_path, "r", encoding="utf-8") as f:
        content = f.read()

    print(f"\n{'='*60}")
    print("Federal Document Triage Agent - Demo")
    print(f"{'='*60}")
    print(f"Processing: {doc_path.name}")
    print(f"Content length: {len(content)} bytes\n")

    # Initialize supervisor
    supervisor = SupervisorAgent()

    # Process document
    try:
        final_state = await supervisor.process_document(
            document_id=f"DEMO-{doc_path.stem.upper()}",
            s3_key=f"s3://demo-bucket/{doc_path.name}",
            content=content,
        )

        # Display results
        status = supervisor.get_workflow_status(final_state)

        print(f"\n{'='*60}")
        print("WORKFLOW STATUS")
        print(f"{'='*60}")
        for key, value in status.items():
            print(f"{key:.<30} {value}")

        print(f"\n{'='*60}")
        print("CLASSIFICATION DETAILS")
        print(f"{'='*60}")
        if final_state["classification"]:
            classification = final_state["classification"]
            print(f"Subject:          {classification['subject']}")
            print(f"Summary:          {classification['summary']}")
            print(f"Action Required:  {classification['action_required']}")
            print(f"Agency:           {classification.get('originating_agency', 'Unknown')}")
            print(f"Keywords:         {', '.join(classification['keywords'])}")
            print(f"Confidence:       {classification['confidence_score']:.2%}")

        print(f"\n{'='*60}")
        print("ROUTING DETAILS")
        print(f"{'='*60}")
        if final_state["routing"]:
            routing = final_state["routing"]
            print(f"Primary Queue:    {routing['primary_queue'].value}")
            print(
                "Backup Queue:     "
                f"{routing['backup_queue'].value if routing['backup_queue'] else 'None'}"
            )
            print(f"Primary Reviewer: {routing['primary_reviewer_id']}")
            print(f"Backup Reviewer:  {routing['backup_reviewer_id'] or 'None'}")
            print(f"SLA Deadline:     {routing['sla_deadline']}")
            print(f"Rule Applied:     {routing['rule_applied']}")

        print(f"\n{'='*60}")
        print("PII DETECTION")
        print(f"{'='*60}")
        if final_state["pii_detection"]:
            pii = final_state["pii_detection"]
            print(f"PII Detected:     {pii['has_pii']}")
            if pii["has_pii"]:
                print(f"Entity Types:     {', '.join(pii['entity_types'])}")
                print(f"Entity Count:     {pii['entity_count']}")
            print(f"Redaction Applied: {pii['redaction_applied']}")

        if final_state.get("error"):
            print(f"\n{'='*60}")
            print("ERRORS")
            print(f"{'='*60}")
            print(f"Error: {final_state['error']}")

        # Save full state to JSON
        output_file = doc_path.stem + "_result.json"
        with open(output_file, "w", encoding="utf-8") as f:
            # Convert enums to strings for JSON serialization
            json_state = json.loads(json.dumps(final_state, default=str))
            json.dump(json_state, f, indent=2)

        print(f"\nFull result saved to: {output_file}")
        print(f"Audit events: {len(final_state.get('audit_trail', []))} "
              f"(persistence: {final_state.get('audit_persistence_mode')})")
        print(f"{'='*60}\n")

        if final_state.get("error") or not final_state.get("processing_complete"):
            print("DEMO RESULT: FAIL")
            return 1

        print("DEMO RESULT: PASS")
        return 0

    except Exception as e:
        print(f"Error processing document: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m agents.demo <document_path>")
        print("\nExample: python -m agents.demo samples/sample_foia_request.txt")
        sys.exit(1)

    sys.exit(asyncio.run(run_demo(sys.argv[1])))
