# System Architecture

**Status:** describes the code that exists today. Infrastructure/AWS behavior
that was not executed is called out explicitly. For the audit evidence and
residual risks, see
[`evidence/verification-report.md`](evidence/verification-report.md).

## 1. Runtime Shape

The repository is a Python **CLI/Lambda backend**, not a web service.

```text
Local CLI                         AWS (reference, not deployed in audit)
─────────                         ──────────────────────────────────────
python -m agents.demo             S3 event / API Gateway
        │                                  │
        ▼                                  ▼
SupervisorAgent                   lambda/intake_handler.py
        │                                  │
        └──────────────┬───────────────────┘
                       ▼
              LangGraph workflow
                       │
      ┌────────────────┼────────────────┐
      ▼                ▼                ▼
  IntakeAgent     ClassifierAgent   RouterAgent
      │                │                │
  Comprehend/      Bedrock or       rule engine +
  Textract/regex   local demo       SLA mapping
                       │
                       ▼
              approval → escalation → audit
                       │
                       ▼
              AuditorAgent → DynamoDB (live)
```

- **Local demo:** `DEMO_MODE=true`, `USE_COMPREHEND=false`. No network calls.
- **Live:** Bedrock/Comprehend/Textract/DynamoDB are called via boto3. This path
  was not exercised because no authorization was given to make billable AWS
  calls or change cloud resources.

## 2. Workflow Graph

`workflows/graph.py` builds a LangGraph `StateGraph[TriageState]`:

```text
intake ──ok──▶ classify ──ok──▶ route ──ok──▶ approval
  │ error         │ error          │ error        │
  └──retry≤3──────┘                │              ├─ IN_REVIEW ─▶ escalation ─┐
  └──exhausted────▶ audit ◀────────┘              └─ else ───────────────────┤
                                                error ──────────────────────▶┘
                                                                              ▼
                                                                            audit
```

- Each processing node gets **3 retries (4 attempts total)**. On exhaustion the
  graph short-circuits to `audit` with the error preserved;
  `processing_complete` is `False`. It does not continue with empty state.
- Successful nodes reset `retry_count` to `0`, giving each node its own budget.
- `audit` is terminal.
- **Escalation is a no-op within one run.** The routing deadline is created
  immediately before the check, so only restored state can be overdue. Persistent
  scheduling/reload is not implemented.

## 3. State

`workflows/state.py` defines `TriageState` as a `TypedDict`, plus enums for
document type, sensitivity, urgency, approval status, and routing queue.

Key fields:

| Field | Meaning |
| --- | --- |
| `document_content` | Raw input (not persisted by Lambda state writes) |
| `document_content_redacted` | PII-redacted content sent to the classifier |
| `pii_detection` | Entity types/count/spans, redaction flag |
| `classification` | Type, sensitivity, urgency, subject, summary, action, agency, keywords, confidence |
| `routing` | Primary/backup queue, reviewers, SLA, rationale, applied rule |
| `approval_status` | `PENDING`, `IN_REVIEW`, `APPROVED`, `ESCALATED`, etc. |
| `audit_trail` | Per-document events |
| `audit_persisted` | Whether DynamoDB accepted the events |
| `audit_persistence_mode` | `in_memory_demo` or `dynamodb` |
| `error`, `retry_count` | Failure/retry state |
| `processing_complete` | True only when no error and audit handling succeeded |

## 4. Components

### IntakeAgent (`agents/intake_agent.py`)

1. Normalizes whitespace.
2. Detects PII with Comprehend (`detect_pii_entities`, confidence filtered by
   `REDACTION_CONFIDENCE_THRESHOLD`) or the regex fallback when
   `USE_COMPREHEND=false`, Comprehend raises, or the document exceeds 100 KB.
3. Merges overlapping regex spans, preferring the longest, then redacts from
   right to left with `[REDACTED:TYPE]`.
4. Provides Textract polling for PDFs from `bucket/key` S3 paths (mocked tests
   only; not live-verified).

### ClassifierAgent (`agents/classifier_agent.py`)

- Sanitizes `document_id` to `[A-Za-z0-9_-]{1,256}`.
- Uses a prompt with the document inside `<document>` tags, explicitly marked as
  untrusted data; truncates at `MAX_CLASSIFICATION_CHARS` (default 60,000).
- **Demo mode:** deterministic keyword rules for type, sensitivity, urgency,
  subject, agency, action, and confidence.
- **Live mode:** Bedrock Claude 3 Sonnet by default. On failure it **raises**
  unless `ALLOW_CLASSIFIER_FALLBACK=true`; this prevents silent heuristic
  substitution for controlled documents.
- Normalizes/clamps the model response (invalid enums fall back safely,
  confidence clamped to 0.0–1.0, keywords coerced to a list of strings).

### RouterAgent (`agents/router_agent.py`)

1. Exact `(document_type, sensitivity)` rule.
2. Document-type default (e.g., contract → contracting officer) when no exact
   sensitivity rule exists.
3. Global default (`general_queue` / legal counsel).

This fixes the prior bug where an SBU contract fell through to the general
queue. SLA overrides are read from `DEFAULT_SLA_*` environment variables.
Reviewer IDs are hardcoded placeholders and must be replaced before production.

### Approval (`workflows/nodes.py`)

Auto-approve **only** documents that are both:

- `sensitivity_level == unclassified`, and
- `confidence_score > AUTO_APPROVAL_CONFIDENCE_THRESHOLD` (default 0.85,
  strict `>`).

CUI, SBU, and FOUO documents always go to `IN_REVIEW` with the primary reviewer,
regardless of confidence. The approval event records whether auto-approval or
human review was chosen.

### Escalation (`workflows/nodes.py`)

Compares the stored `sla_deadline` plus a 1-hour grace period against current
UTC time, logs an escalation, increments `escalation_count`, and sets
`ESCALATED`. As noted above, a fresh run cannot trigger it.

### Auditor (`agents/auditor_agent.py`, `workflows/audit_context.py`)

- Every `SupervisorAgent.process_document()` call opens a fresh auditor in a
  `ContextVar`. This isolates audit trails for concurrent documents and prevents
  one document's `clear_audit_trail()` from deleting another's events.
- Live mode persists to DynamoDB using the Terraform table schema:
  `document_id` (partition), `timestamp` (sort). Events without a
  `document_id` are rejected.
- If persistence fails, the workflow stays incomplete (`processing_complete=False`)
  and the error is retained.
- Demo mode intentionally skips DynamoDB and reports
  `audit_persistence_mode=in_memory_demo`.

## 5. Lambda Handlers (`lambda/intake_handler.py`)

- **S3 handler:** reads an object, validates the document ID/size, runs the
  workflow, and writes sanitized state to `STATE_DYNAMODB_TABLE`.
- **API Gateway handler:** decodes plain or base64 JSON body, validates
  ID/encoding/size, runs the workflow, writes sanitized state, and returns
  `SupervisorAgent.get_workflow_status()`.
- State writes remove `document_content` and `document_content_redacted`.
  `None`/empty values are removed, floats become `Decimal`, enums become values.
- Errors return generic JSON messages; details stay in server logs.

## 6. Infrastructure (`terraform/`)

Implemented and statically validated:

- VPC, public/private/database subnets, NAT gateways, route tables, flow logs.
- KMS keys for S3 and DynamoDB; encrypted/versioned S3 buckets with public
  access blocks; archive bucket with Object Lock.
- DynamoDB audit table (`document_id` + `timestamp`) and state table.
- CloudTrail with log-file validation, CloudWatch Logs, S3 bucket policies,
  partition-aware data-resource ARNs.
- S3 server-access-log delivery policy for the archive bucket.
- Optional GuardDuty detector and Security Hub account.

**Not implemented:** Lambda function, API Gateway, S3 event notification, SNS/
SES notifications, Step Functions, reviewer directory, document archive writes,
and S3 Object Lock uploads. `terraform apply` was not run. See the deployment
status in the README.

## 7. Security-Relevant Behavior

| Control | Implementation | Verification |
| --- | --- | --- |
| PII redaction before LLM | Intake agent, Comprehend/regex | Unit + E2E tests |
| Sensitive docs require human review | Approval policy | Unit + E2E tests |
| Prompt injection hardening | Sanitized ID, tagged untrusted text, truncation | Classifier tests |
| No silent classifier fallback | `ALLOW_CLASSIFIER_FALLBACK` off by default | Classifier test |
| Audit isolation | ContextVar per workflow | Concurrency test |
| No document bodies in state table | Lambda sanitizer | Lambda test |
| Non-root container | Dockerfile `appuser` | Docker build/run |
| No secrets in image | `.dockerignore` | Image inspection |
| Dependency vulnerabilities | Upgraded pins; `pip-audit` clean | Audit log |

Not implemented/verified: IAM execution roles for Lambda, KMS grants for runtime,
SNS notifications, FedRAMP authorization, dynamic reviewer lookup, live PII
engine accuracy, and live AWS API behavior.

## 8. Performance

No load or latency benchmark was run. The code's per-document cost is dominated
by external AWS calls (Comprehend/Textract/Bedrock/DynamoDB) in live mode; demo
mode is in-memory Python. Do not rely on the unverified throughput numbers that
appeared in earlier documentation.

## 9. Extending the System

### New document type

1. Add the enum to `workflows/state.py`.
2. Add classifier keywords/prompt mapping and route defaults.
3. Add tests in `tests/test_classifier.py`, `tests/test_router.py`, and
   `tests/test_workflow.py`.
4. Update docs and sample expectations.

### New queue/reviewer source

1. Add the enum and mapping in `agents/router_agent.py`.
2. Replace `_get_reviewer_for_queue` with a staff-directory lookup and keep the
   current IDs as a test fallback.
3. Add routing and integration tests.

### Real human-in-the-loop

Implement persistence and notification outside the single-run graph (for example
Step Functions + SNS/SES + DynamoDB), then add a callback that records the
decision and re-enters the audit path. This is currently a documented gap, not a
working feature.

---

**Architecture version:** 2.0
**Last verified:** 2026-11-01
