# Repository Audit and Verification Report

**Repository:** `federal-doc-triage-agent`
**Audit date:** 2026-11-01 (America/New_York)
**Auditor role:** senior software engineer / QA automation / DevOps / documentation
**Scope:** full tracked repository, local execution, tests, container build,
Terraform validation, documentation accuracy, and security review.

---

## 1. Executive Summary

The repository contains a working **Python 3.12 CLI/LangGraph** document-triage
workflow with optional AWS integrations. The local demo, automated tests,
linting, dependency audit, Docker build/run/health check, and Terraform static
validation all pass after remediation.

The AWS deployment path is **not** production-ready: Terraform provisions a
data/security baseline but does not create the Lambda function, API Gateway, S3
event notification, or human-in-the-loop notification workflow. A shared AWS
credentials file was present, but no authorization was given to make billable
AWS calls or change cloud resources, so live Bedrock/Comprehend/Textract/
DynamoDB calls and `terraform apply` were not executed. The prior documentation
overstated production/FedRAMP readiness; it has been corrected.

**Final verdict: PARTIAL PASS.** The locally executable application is verified;
the cloud deployment and live integrations remain incomplete/unverified.

---

## 2. Repository Assessment

### Stack and architecture

| Item | Finding |
| --- | --- |
| Language/runtime | Python 3.12.7 |
| Orchestration | LangGraph 1.2.19, LangChain Core 1.7.3 |
| AWS SDK | boto3/botocore 1.43.123 |
| Entry points | `python -m agents.demo`, `lambda/intake_handler.py` (`lambda_handler`, `lambda_handler_api_gateway`) |
| Interface | CLI + Lambda; **no HTTP server or frontend** |
| Data stores | DynamoDB (audit/state) in live mode; in-memory demo |
| Infrastructure | Terraform 1.x / AWS provider 5.100.0 |
| Tests | pytest, pytest-asyncio; 73 tests at final run |
| CI | Added `.github/workflows/ci.yml` (not executed on GitHub in this audit) |

### Baseline before changes

- `pytest tests/ -q`: 12 passed (only classifier/router tests).
- Demo: worked for all four samples.
- `ruff check`: 15 findings (unused imports, f-strings, E402).
- `terraform fmt -check`: 3 files needed formatting.
- `pip-audit`: **17 known vulnerabilities in 3 packages** (`python-dotenv`,
  `langgraph-sdk`, `urllib3`).
- Dockerfile health check queried `http://localhost:8080/health`, but the
  application has no HTTP server.
- `.dockerignore` was missing, so `COPY . .` could copy `.env` and `.git` into
  the image.
- Terraform did not create a Lambda function, despite docs/deploy script
  claiming otherwise.

---

## 3. Issues Found, Root Cause, and Remediation

Severity: **C** critical, **H** high, **M** medium, **L** low.

| # | Sev | Issue / impact | Root cause | Fix |
| --- | --- | --- | --- | --- |
| 1 | C | SBU contract memo routed to `general_queue` instead of contracting officer | Routing only had exact `(type, sensitivity)` rules; no type fallback | Added `TYPE_DEFAULT_ROUTING` fallback and rule/rationale reporting in `agents/router_agent.py`; regression tests |
| 2 | C | Sensitive CUI/SBU/FOUO documents could be auto-approved at high confidence | Approval policy checked confidence only | Auto-approve only `unclassified` above a strict threshold; sensitive docs always `IN_REVIEW` (`workflows/nodes.py`); tests |
| 3 | C | Failed intake could continue into classification/approval and finish "complete" | Conditional edges retried but always fell through; audit cleared errors | Retry budget then short-circuit to audit; reset retry count on success; audit preserves errors and sets `processing_complete=False` (`workflows/graph.py`, `workflows/nodes.py`); tests |
| 4 | C | Concurrent documents shared one auditor; trails interleaved and were cleared across runs | Module-level singleton `AuditorAgent` | Added `workflows/audit_context.py` ContextVar scope per `process_document`; concurrency test |
| 5 | C | DynamoDB audit persistence used `event_id` key, but Terraform table keyed `document_id` + `timestamp` | Schema drift between code and IaC | Persist `document_id`/`timestamp`; reject events without document ID (`agents/auditor_agent.py`); tests |
| 6 | C | Lambda state writes would fail on `None`/floats/empty values and persisted raw document bodies | Direct `put_item` of workflow state | Added recursive sanitizer + `_build_state_item` that strips raw/redacted content (`lambda/intake_handler.py`); tests |
| 7 | C | Docker health check always failed; image could include `.env`/git | HTTP health check for a CLI; missing `.dockerignore` | CLI-appropriate Python health check; added `.dockerignore`; removed ignored `.dockerignore` rule; verified image has no `.env` |
| 8 | C | 17 known dependency vulnerabilities | Stale pins | Upgraded boto3/botocore, langgraph, langchain-core, python-dotenv, urllib3; `pip-audit` clean |
| 9 | H | Bedrock failure silently substituted local heuristics | Blanket `except` fallback | Fallback only when `ALLOW_CLASSIFIER_FALLBACK=true`; otherwise raise; tests |
| 10 | H | PII regex detection could produce overlapping spans, corrupting redaction | No span merge; per-type regex replacement | Merge overlaps (longest wins), redact right-to-left; tests for credit card/phone overlap |
| 11 | H | Comprehend synchronous limit (100 KB) caused failures on large text | No size guard | Guard before API call; regex fallback; test |
| 12 | H | Comprehend-detected entities were not redacted by span | Old code redacted only named regex types | Redact Comprehend spans directly; test with PERSON/ADDRESS |
| 13 | H | Prompt injection exposure from document text | Text inserted verbatim | Sanitize ID, wrap untrusted text, instruct model to ignore embedded directions, truncate; tests |
| 14 | H | `.env` settings were partly ignored (`BEDROCK_MODEL_ID`, region, audit table, confidence threshold) | Hardcoded constructors/defaults | Wired env in intake/classifier/auditor; threshold + table fallback; tests |
| 15 | H | `deploy.sh` built an invalid Lambda zip (missing handler/dependencies) | Wrong paths/zip contents | Rebuilt package root with handler + deps; added zip prerequisite |
| 16 | H | `deploy.sh` reported success when Lambda was absent | Warning + return | Now exits non-zero with explicit explanation |
| 17 | H | Terraform CloudTrail data-resource ARNs used `arn:aws` in GovCloud | Hardcoded partition | Use `data.aws_partition.current.partition` |
| 18 | H | S3 server-access logging lacked a target bucket policy | Missing log-delivery authorization | Added archive bucket policy + dependencies |
| 19 | H | Terraform advertised GuardDuty/Security Hub variables but created neither | Dead variables | Added optional `aws_guardduty_detector` / `aws_securityhub_account` (static validation only) |
| 20 | H | Documentation claimed production/FedRAMP readiness and non-existent components (Lambda, ALB, RDS, Cognito, WAF, Istio, SNS, Step Functions) | Aspirational docs out of sync with code | Rewrote README/ARCHITECTURE/QUICKSTART/SECURITY/FEDRAMP/terraform docs with verification status and gaps |
| 21 | M | `test_local.py` always exited 0 and printed success even when checks failed | No assertions/exit code | Rewrote as failing smoke checks; added to CI |
| 22 | M | No CI, lint config, or dependency audit | Missing automation | Added `pyproject.toml`, ruff, `.github/workflows/ci.yml`, pip-audit |
| 23 | M | Lambda API handler accepted unbounded input | No size check | Added `MAX_DOCUMENT_SIZE_MB` enforcement + 413 response; test |
| 24 | M | Lambda error paths returned raw exception strings | Broad exception exposure | Generic JSON errors; server-side logs |
| 25 | M | Docker ran with no useful health signal | Health check mismatch | Python import/graph health check; verified healthy |
| 26 | M | `originating_agency` often captured the recipient (`TO:`) | Single first-match regex | Prefer reporting agency, then `FROM`, then `TO` |
| 27 | M | No tests for intake/Lambda/approval/concurrency/audit | Coverage gap | Added `tests/test_intake.py`, `test_workflow.py`, `test_auditor.py`, `test_lambda_handler.py`; 73 total |
| 28 | L | Unused imports/f-strings, Terraform formatting | Code hygiene | ruff + `terraform fmt` clean |
| 29 | L | No LICENSE despite README badge | Missing file | Added MIT LICENSE |
| 30 | L | Stale review document implied current status | Historical content | Added banner pointing to this report |

### Security scan

- `git grep` for AWS keys/private keys/passwords in tracked files: no obvious
  secrets.
- `.env` on disk is gitignored; it matched the old `.env.example` (no real
  credentials) and is excluded from Docker. It was not committed.
- `pip-audit` now reports **no known vulnerabilities** for `requirements.txt`.
- `gitleaks`/secret scanning was not installed; the manual regex scan is not a
  substitute for a full history scan.

---

## 4. Features and Workflows Tested

### End-to-end demo (actual execution)

Commands:

```bash
python -m agents.demo samples/sample_foia_request.txt
python -m agents.demo samples/sample_contract_memo.txt
python -m agents.demo samples/sample_incident_report.txt
python -m agents.demo samples/sample_executive_correspondence.txt
```

| Sample | Result | Type / sensitivity | Queue | Approval |
| --- | --- | --- | --- | --- |
| FOIA | PASS | `foia` / `unclassified` | `legal_counsel` | `in_review` |
| Contract memo | PASS | `contract` / `sbu` | `contracting_officer` | `in_review` |
| Incident report | PASS | `incident_report` / `cui` | `security_team` | `in_review` |
| Executive correspondence | PASS | `executive_correspondence` / `fouo` | `chief_of_staff` | `in_review` |

Each produced PII detections (email/phone), 5 audit events, a JSON result file,
and `DEMO RESULT: PASS` with exit code 0. Logs:
[`test-results/`](test-results/).

### Automated tests (70)

Coverage includes:

- PII: email/phone/SSN/credit card/DOB, overlap merge, Comprehend spans,
  confidence threshold, 100 KB fallback, no-PII path, Textract success/failure/
  timeout/exception.
- Classifier: init/model config, Bedrock request shape, demo mode, fallback
  policy, confidence clamp, prompt tagging/truncation, invalid response fields.
- Router: all documented types, exact SBU rules, type fallback, global default,
  serialized enum values, SLA env overrides/invalid values.
- Approval: sensitive never auto-approved; unclassified high confidence approved;
  unclassified at threshold requires review.
- Failure/retry: 4 attempts, no classification after exhausted intake, error
  preserved, incomplete workflow.
- Audit: key schema, missing document ID rejection, empty trail, copy semantics,
  persistence failure.
- Lambda: sanitizer, body stripping, missing/invalid/oversized input, success
  persistence, malformed S3 event, invalid env.
- Concurrency: two documents get disjoint audit trails.

### Commands and results

```text
python -m pytest tests/ -v --cov=agents --cov=workflows --cov-report=term-missing
→ 73 passed, ~79% total coverage

ruff check agents workflows tests lambda scripts test_local.py
→ All checks passed!

python test_local.py
→ All local smoke checks passed.

python -m pip_audit -r requirements.txt
→ No known vulnerabilities found
```

Raw logs:

- [pytest.txt](test-results/pytest.txt)
- [ruff.txt](test-results/ruff.txt)
- [pip-audit.txt](test-results/pip-audit.txt)
- [smoke.txt](test-results/smoke.txt)

### What was not testable locally

- Live AWS Bedrock, Comprehend, Textract, DynamoDB, S3, CloudTrail, KMS.
- `terraform apply` / AWS resource creation.
- Lambda deployment and S3 event triggering.
- Browser console/network (no web UI).
- Real mobile/responsive UI (no web UI).

---

## 5. Build and Deployment Verification

### Python

- `python -m compileall -q agents workflows lambda test_local.py` → exit 0
  ([compileall.txt](build-results/compileall.txt)).
- No packaging/build step exists; application runs from source.

### Docker

```bash
DOCKER_BUILDKIT=0 docker build -t federal-doc-triage-agent:audit .
docker run --rm federal-doc-triage-agent:audit
docker run --rm federal-doc-triage-agent:audit sh -c 'test ! -f /app/.env'
```

- Build: success ([docker-build.txt](build-results/docker-build.txt)).
- Run: exit 0, `DEMO RESULT: PASS` ([docker-run.txt](build-results/docker-run.txt)).
- Image contents: minimal; no `.env`
  ([docker-image-contents.txt](build-results/docker-image-contents.txt)).
- Health check: `healthy`
  ([docker-healthcheck.json](build-results/docker-healthcheck.json)).

A separate clean virtual environment was created from `requirements.txt` +
`requirements-dev.txt` and ran the suite successfully:
[fresh-venv.txt](build-results/fresh-venv.txt) (73 passed).

Note: BuildKit failed in the audit sandbox because it could not write
`~/.docker/buildx/activity`. The legacy builder was used successfully. CI uses
normal BuildKit in GitHub Actions; this is an environment limitation, not an
application defect.

### Terraform

```bash
terraform fmt -check -recursive terraform      # exit 0
cd terraform
terraform init -backend=false -input=false     # success
terraform validate                             # Success! The configuration is valid.
```

Logs: [terraform-fmt.txt](build-results/terraform-fmt.txt),
[terraform-validate.txt](build-results/terraform-validate.txt).

`terraform plan/apply` was not run: credentials were present, but no authorization
was given to make billable calls or modify a cloud account.

### CI

Added `.github/workflows/ci.yml` with lint, dependency audit, compile, tests,
smoke checks, all-sample demos, Docker build/run/`.env` check, and Terraform
format/validate. It was not executed by GitHub Actions during this audit; the
same commands were executed locally.

---

## 6. Screenshots (Genuine Execution Captures)

The app is CLI-only. Screenshots were rendered from captured stdout/stderr by
`scripts/render_evidence.py`; the renderer adds only a title and terminal frame.
No output was invented or edited.

| Screenshot | Demonstrates |
| --- | --- |
| [demo-foia-workflow.png](screenshots/demo-foia-workflow.png) | Full FOIA intake → classification → routing → approval → audit, PII redaction, `DEMO RESULT: PASS` |
| [demo-contract-routing.png](screenshots/demo-contract-routing.png) | Fixed SBU contract routing (`contract:type-default`) and human-review requirement |
| [test-suite-results.png](screenshots/test-suite-results.png) | 73 passing tests and coverage table |
| [docker-container-run.png](screenshots/docker-container-run.png) | Actual containerized demo run |
| [smoke-checks.png](screenshots/smoke-checks.png) | Local smoke checks without AWS |
| [demo-foia-narrow.png](screenshots/demo-foia-narrow.png) | 430 px terminal rendering (CLI, not a mobile web UI) |

---

## 7. Remaining Issues and Limitations

| Sev | Issue | Status |
| --- | --- | --- |
| C | Terraform does not provision Lambda/API Gateway/S3 notification; `deploy.sh` stops at the missing function | Open; documented |
| C | `terraform apply` and all live AWS calls unverified | Blocked by no authorization for cloud changes/billable calls |
| H | Escalation cannot trigger within one run; no state reload/scheduler | Open; documented |
| H | Reviewer IDs are hardcoded; no staff-directory/auth integration | Open |
| H | No authentication/authorization, SNS/SES/Step Functions, or archive writer | Open |
| H | CloudTrail/CloudWatch KMS key policy and apply-time behavior unverified | Open; static validation only |
| M | Security Hub enabled without standards subscription | Open |
| M | Several `.env.example` variables remain unused (`SUPPORTED_FORMATS`, `AUDIT_S3_BUCKET`, `AUDIT_RETENTION_DAYS`, `STATE_S3_PREFIX`, `DEBUG`) | Documented |
| M | Textract/Comprehend only mocked; no live accuracy/limit validation | Open |
| M | No performance/load test; no production sizing evidence | Open |
| M | CI workflow not run on GitHub in this audit | Open |
| L | Docker BuildKit could not run in the sandbox (legacy builder used) | Environment limitation |
| L | `gitleaks`/full git-history secret scan not run | Open; manual scan only |
| L | FedRAMP/security claims are design mappings, not assessments | Documented |

---

## 8. Final Quality Gate

| Gate | Result |
| --- | --- |
| Dependencies install from pinned requirements | **PASS** (venv + Docker) |
| Application executes | **PASS** (4/4 demos) |
| Production container build | **PASS** |
| Container runs and health check | **PASS** (`healthy`) |
| Type checking | **N/A** — no mypy/pyright configuration; Python typing is runtime/`TypedDict` only |
| Linting | **PASS** (ruff, 0 findings) |
| Existing + new tests | **PASS** (73 passed) |
| Critical workflows verified | **PASS for local workflow**; live AWS workflows **NOT VERIFIED** |
| Browser console/network | **N/A** — no web UI |
| Mobile/responsive layout | **N/A** — no web UI; narrow CLI capture provided |
| Terraform format/validate | **PASS** |
| Terraform apply / deployment | **NOT RUN** |
| Screenshots captured | **PASS** (6) |
| README reflects verified state | **PASS** |
| Verification report evidence | **PASS** |
| No secrets committed | **PASS for tracked files** (manual scan; full-history tooling not run) |
| Remaining issues documented | **PASS** |

## 9. Final Verdict

**PARTIAL PASS**

The local application, tests, lint, dependency audit, container build/run, and
Terraform static validation are verified. The repository is no longer presented
as production-ready or FedRAMP-authorized. The AWS deployment path (Lambda,
API Gateway, notifications, archive, live services) remains incomplete and was
not executed, so a full PASS is not justified.

**Recommended next steps:** implement and apply Lambda/API/IAM/notification
infrastructure in a non-production GovCloud account, add live integration tests,
replace hardcoded reviewers, implement persistent escalation, then re-run this
verification and a security assessment.

---

*All logs and screenshots in this directory were produced by the commands shown.
No test result, build result, or screenshot was fabricated.*
