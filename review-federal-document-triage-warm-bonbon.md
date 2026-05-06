# Federal Document Triage Agent — Code Review Plan

## Context

The repository claims to be a production-ready FedRAMP Moderate-aligned multi-agent document triage system. This review verifies whether the implementation matches those claims, identifies bugs, security gaps, and incomplete stubs, and provides a prioritized fix list.

---

## Critical Blockers (Will Break Deployment or Tests)

### 1. Terraform `modules/vpc` does not exist

- **File:** `terraform/main.tf`, line with `module.vpc`
- `terraform init` fails immediately because `./modules/vpc` is referenced but the directory does not exist.
- **Fix:** Either implement the VPC module under `terraform/modules/vpc/` or replace the module reference with inline VPC resources (`aws_vpc`, `aws_subnet`, `aws_internet_gateway`, etc.).

### 2. Archive S3 bucket missing `object_lock_enabled = true`

- **File:** `terraform/main.tf` — `aws_s3_bucket.archive_bucket`
- AWS provider v4+ requires `object_lock_enabled = true` on the bucket resource itself before an `aws_s3_bucket_object_lock_configuration` can be applied. Without it, `terraform apply` errors.
- **Fix:** Add `object_lock_enabled = true` to `aws_s3_bucket.archive_bucket`.

### 3. Classifier unit tests will all fail with `json.JSONDecodeError`

- **File:** `tests/test_classifier.py`
- The mock Bedrock response body is a byte-string containing a JSON object with a `"text"` value that contains literal newlines. JSON does not allow unescaped newlines inside string values. `json.loads()` raises `JSONDecodeError` before any assertion runs.
- **Fix:** Replace the multi-line string in the mock response body with a properly escaped single-line JSON string.

### 4. Docker AWS credential path is broken

- **File:** `Dockerfile`, `README.md`, `docs/QUICKSTART.md`
- All docs mount `~/.aws:/root/.aws:ro`, but the container runs as non-root user `appuser`. The AWS SDK looks at `/home/appuser/.aws`, not `/root/.aws`. AWS authentication silently fails.
- **Fix:** Change the mount point to `~/.aws:/home/appuser/.aws:ro` in all documentation examples.

### 5. `deploy.sh` argument parsing does not match documented usage

- **File:** `scripts/deploy.sh`
- Script reads `ENVIRONMENT="$1"` and `REGION="$2"` (positional), but all documentation shows `./scripts/deploy.sh --env production --region us-gov-west-1` (named flags). Running the documented command sets `ENVIRONMENT="--env"` and `REGION="production"`, breaking the deployment.
- **Fix:** Add named flag parsing (using `getopts` or a `case` loop) or update documentation to use positional syntax.

---

## Security Issues

### 6. Raw AWS exceptions returned to API Gateway callers

- **File:** `lambda/intake_handler.py`, lines ~91-93 and ~160-162
- Error responses return the raw exception message string, which can contain internal AWS ARNs, account IDs, and region info.
- **Fix:** Return generic error messages to callers; log the full exception server-side only.

### 7. Prompt injection via `document_id`

- **File:** `agents/classifier_agent.py`, line ~38
- The document ID is injected directly into the LLM prompt string without sanitization.
- **Fix:** Sanitize or validate `document_id` before embedding in the prompt (alphanumeric + hyphens only), or exclude it from the prompt body.

### 8. No encryption on archive and CloudTrail S3 buckets

- **File:** `terraform/main.tf`
- `aws_s3_bucket.archive_bucket` and `aws_s3_bucket.cloudtrail_bucket` have no `aws_s3_bucket_server_side_encryption_configuration`. Only the intake bucket has encryption configured.
- **Fix:** Add KMS-based SSE configuration to both buckets (reuse the existing `aws_kms_key.s3`).

### 9. No S3 bucket versioning for archive bucket

- **File:** `terraform/main.tf`
- S3 Object Lock requires versioning. The archive bucket has Object Lock configured but no `aws_s3_bucket_versioning` resource.
- **Fix:** Add `aws_s3_bucket_versioning` for the archive bucket with `status = "Enabled"`.

### 10. `.dockerignore` missing

- **File:** repository root
- `COPY . .` in the Dockerfile will copy `.env`, `.git/`, test files, and potentially secrets if they exist locally.
- **Fix:** Create a `.dockerignore` file excluding `.env`, `.git/`, `tests/`, `*.tfstate`, `*.tfvars`, and `.terraform/`.

---

## Logic Bugs

### 11. Approved/Rejected status is unreachable in the workflow

- **File:** `workflows/nodes.py` (approval_node), `workflows/graph.py` (conditional edges)
- `approval_node` is a stub that always sets `approval_status = IN_REVIEW`. The conditional edge routes `IN_REVIEW` → `escalation`. The direct `approval → audit` path is only reachable for `APPROVED`/`REJECTED`/`DELEGATED` status, which the stub never sets.
- **Fix:** Either implement real approval logic, or change the stub to cycle through states so the workflow can complete (e.g., set status to `APPROVED` for confidence > 0.8).

### 12. Escalation SLA check never triggers

- **File:** `workflows/nodes.py`, line ~186
- The SLA deadline is calculated seconds before it is checked. The check `if sla_deadline < datetime.utcnow()` will always be `False` since the deadline is 4 hours to 10 days in the future.
- **Fix:** The escalation check should compare against the deadline stored in state from a _previous_ processing run, not one just created. This requires persisting the routing decision across invocations.

### 13. `SensitivityLevel.SBU` has no routing rules

- **File:** `agents/router_agent.py`, `workflows/state.py`
- The `sbu` sensitivity level is a valid enum value returned by the classifier, but the router has no routing rules for it. Documents classified as SBU silently fall through to `GENERAL_QUEUE`, which is inappropriate for a federal compliance system.
- **Fix:** Add explicit routing rules for `SensitivityLevel.SENSITIVE_BUT_UNCLASSIFIED` to the appropriate queue (likely `SECURITY_TEAM` or `LEGAL_COUNSEL`).

### 14. Comprehend-detected entities are not redacted

- **File:** `agents/intake_agent.py`, `_redact_pii` method
- When Comprehend succeeds, it may detect entity types like `PERSON`, `ADDRESS`, `DATE_TIME`. These are tracked in the PII detection result, but `_redact_pii` only applies regex patterns by name. Comprehend entity types are not in `redaction_patterns`, so detected PII passes through unredacted.
- **Fix:** Add redaction logic for Comprehend entity types by scanning the text for matched entity strings returned in the Comprehend response.

### 15. `retry_count` increments but is never checked

- **File:** `agents/supervisor.py` (`max_retries = 3`), `workflows/nodes.py` (all error handlers)
- On node failure, `retry_count` is incremented in the state dict, but no conditional edge re-routes to retry the failed node. A document that fails intake still proceeds to classification with empty content.
- **Fix:** Add a `should_retry` conditional edge after each node that checks `retry_count < max_retries` and routes back to the failed node.

---

## Incomplete Stubs

### 16. PDF extraction returns placeholder text

- **File:** `agents/intake_agent.py`, `extract_text_from_pdf`
- Starts an async Textract job but immediately returns `"[PDF extracted from {s3_key}]"` without polling for results. PDF intake is non-functional.
- **Fix:** Implement polling loop using `textract.get_document_text_detection(JobId=job_id)` until `JobStatus == "SUCCEEDED"`.

### 17. Approval node is a stub with no human-in-the-loop

- **File:** `workflows/nodes.py`, `approval_node`
- No SNS, SQS, Step Functions, or any external notification. Always sets status to `IN_REVIEW`.
- This is a known limitation, but the README lists this as a completed feature. The README should clarify this is a planned integration.

### 18. Reviewer IDs are hardcoded placeholders

- **File:** `agents/router_agent.py`, `_get_reviewer_for_queue`
- Returns literal strings like `"contracting-officer-001"` for all queues.
- **Fix for production:** Replace with a staff directory lookup or at minimum make the IDs configurable via environment variables.

### 19. Audit trail has no durable persistence

- **File:** `agents/auditor_agent.py`, `workflows/nodes.py`
- Audit events are stored in a module-level in-memory list. Across Lambda cold starts, all events are lost. No CloudTrail, DynamoDB, or S3 write occurs from within the agent code itself.
- **Fix:** Add a `persist_to_dynamodb(table_name, audit_events)` method and call it in `audit_node` after collecting events.

---

## Missing Terraform Resources (Docs vs. Reality)

### 20. GuardDuty and Security Hub have no Terraform resources

- Variables `enable_guardduty` and `enable_security_hub` are declared but referenced by nothing in `main.tf`.
- Both are prominently advertised in FEDRAMP-ALIGNMENT.md as deployed.
- **Fix:** Add `aws_guardduty_detector` and `aws_securityhub_account` resources gated on the respective variables.

### 21. No IAM roles, Lambda functions, or CloudWatch log groups in Terraform

- Files listed in README (`terraform/iam.tf`, `terraform/lambda.tf`, `terraform/step_functions.tf`) do not exist.
- **Fix:** Implement at minimum an `aws_iam_role` and `aws_lambda_function` for the intake handler, plus `aws_cloudwatch_log_group` resources.

### 22. Dead Terraform variables

- `lambda_memory_size`, `lambda_timeout`, `bedrock_model_id`, `log_retention_days`, and ~10 others are declared but referenced nowhere in `main.tf`.

---

## Code Quality Issues

### 23. `datetime.utcnow()` used in 5+ locations (deprecated Python 3.12)

- **Files:** `workflows/state.py:141`, `agents/auditor_agent.py:38`, `agents/router_agent.py:109,138`, `workflows/nodes.py:186`
- **Fix:** Replace all with `datetime.now(timezone.utc)` (import `timezone` from `datetime`).

### 24. Unused imports across multiple agent files

- `Optional` imported but unused: `agents/classifier_agent.py`, `agents/router_agent.py`, `agents/intake_agent.py`
- `json` imported but unused: `agents/intake_agent.py`
- **Fix:** Remove unused imports.

### 25. Dead dependencies in `requirements.txt`

- `langchain==0.1.16`, `langchain-community==0.0.35`, and `requests==2.31.0` are listed but imported nowhere in the codebase.
- **Fix:** Remove these three dependencies. Split dev-only packages (`pytest`, `pytest-asyncio`, `pytest-cov`) into a separate `requirements-dev.txt`.

### 26. `__import__("boto3")` antipattern in Lambda handler

- **File:** `lambda/intake_handler.py`, lines ~51, 68, 144
- **Fix:** Replace all `__import__("boto3")` calls with a top-level `import boto3`.

### 27. `except Exception:` without logging in `_detect_pii`

- **File:** `agents/intake_agent.py`, line ~57
- Silently swallows all errors including programming mistakes, making debugging impossible.
- **Fix:** Add `except Exception as e: logger.warning("Comprehend failed, falling back to regex: %s", e)`.

### 28. `git` installed in Dockerfile with no purpose

- **File:** `Dockerfile`
- Increases image size and attack surface.
- **Fix:** Remove `git` from the `RUN apt-get install` command.

### 29. `CreatedAt = timestamp()` in Terraform default tags causes perpetual diffs

- **File:** `terraform/main.tf`
- `timestamp()` re-evaluates on every `terraform plan`, marking every tagged resource as changed.
- **Fix:** Remove `CreatedAt` from `default_tags` or use a static string.

---

## Documentation Accuracy Issues

### 30. README project tree lists ~15 non-existent files

Files documented but absent: `lambda/approval_handler.py`, `lambda/escalation_handler.py`, `terraform/outputs.tf`, `terraform/iam.tf`, `terraform/lambda.tf`, `terraform/step_functions.tf`, `terraform/s3.tf`, `terraform/dynamodb.tf`, `docs/routing-rules.md`, `docs/api-reference.md`, `tests/test_workflow.py`, `tests/fixtures/`, `scripts/local_dev.sh`.

### 31. FEDRAMP-ALIGNMENT.md references non-existent technology

- Claims Kubernetes RBAC (no k8s), Istio mTLS (no service mesh), RDS PostgreSQL (no RDS), and AWS WAF/ALB (no WAF or ALB resources).
- **Fix:** Remove or replace with accurate technology references.

### 32. SECURITY.md references non-existent scripts

- `./scripts/run_security_scan.sh` and `python scripts/generate_compliance_report.py` do not exist.

### 33. ARCHITECTURE.md Python exponentiation bug in code snippet

- `2 ^ retry_count` — `^` is bitwise XOR in Python. Should be `2 ** retry_count`.

---

## Files To Modify (Critical Path)

| File                               | Change Needed                                                                                         |
| ---------------------------------- | ----------------------------------------------------------------------------------------------------- |
| `terraform/main.tf`                | Add VPC module or inline VPC; add S3 encryption/versioning; fix Object Lock; remove `timestamp()` tag |
| `terraform/modules/vpc/`           | Create VPC module (new directory)                                                                     |
| `tests/test_classifier.py`         | Fix multi-line JSON in mock response body                                                             |
| `Dockerfile`                       | Remove `git`; fix AWS credential mount path in docs                                                   |
| `scripts/deploy.sh`                | Add named flag parsing OR fix documentation                                                           |
| `lambda/intake_handler.py`         | Fix `__import__`, fix base64 check, fix error responses                                               |
| `agents/intake_agent.py`           | Fix Comprehend redaction gap, add error logging, fix PDF stub                                         |
| `agents/auditor_agent.py`          | Add DynamoDB persistence                                                                              |
| `agents/router_agent.py`           | Add SBU routing rules, fix hardcoded reviewer stubs                                                   |
| `agents/classifier_agent.py`       | Remove unused import, add JSON validation                                                             |
| `workflows/nodes.py`               | Fix approval stub, fix escalation SLA logic                                                           |
| `workflows/graph.py`               | Add retry conditional edges                                                                           |
| `requirements.txt`                 | Remove dead deps; split dev requirements                                                              |
| `README.md` / `docs/QUICKSTART.md` | Fix Docker mount path, fix deploy.sh syntax, remove non-existent files from project tree              |
| `FEDRAMP-ALIGNMENT.md`             | Remove false technology claims                                                                        |
| `SECURITY.md`                      | Remove references to non-existent scripts                                                             |
| `docs/ARCHITECTURE.md`             | Fix `^` → `**` in code snippet                                                                        |

---

## Verification Steps

After fixes are applied:

1. `cd terraform && terraform init` — should succeed with no module errors
2. `terraform validate` — should pass with no undefined references
3. `pytest tests/ -v` — all 14 tests should pass (after fixing mock JSON)
4. `python -m agents.demo samples/sample_foia_request.txt` — end-to-end local run
5. `docker build -t triage-agent .` — image should build cleanly
6. `docker run --rm -e AWS_REGION=us-gov-west-1 -v ~/.aws:/home/appuser/.aws:ro triage-agent` — AWS auth should resolve
7. `grep -r "datetime.utcnow" .` — should return no results after fix
8. `grep -r "__import__" .` — should return no results after fix
9. `pip install -r requirements.txt && pip check` — no dependency conflicts
