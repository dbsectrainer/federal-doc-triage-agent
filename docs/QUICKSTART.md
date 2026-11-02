# Quick Start Guide

This is a **CLI/Lambda backend**. There is no web server, homepage, or HTTP
endpoint to open in a browser. The fastest verified path is the local demo,
which needs no AWS credentials.

## Prerequisites

- Python **3.12+**
- `pip`
- Optional: AWS CLI + credentials for live Bedrock/Comprehend/Textract/DynamoDB
- Optional: Docker for the container build
- Optional: Terraform >= 1.0 for infrastructure validation

## 1. Set Up

```bash
git clone https://github.com/dbsectrainer/federal-doc-triage-agent.git
cd federal-doc-triage-agent

python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

pip install -r requirements.txt
pip install -r requirements-dev.txt
```

## 2. Configure (Optional for Demo)

```bash
cp .env.example .env
```

The demo runner loads `.env` and then forces:

```text
DEMO_MODE=true
USE_COMPREHEND=false
```

You do not need AWS keys for the demo. For live mode, set `DEMO_MODE=false` and
configure AWS credentials and `AWS_REGION`/`BEDROCK_REGION`. See the environment
table in [../README.md](../README.md#environment-configuration).

## 3. Run the Demo

```bash
python -m agents.demo samples/sample_foia_request.txt
python -m agents.demo samples/sample_contract_memo.txt
python -m agents.demo samples/sample_incident_report.txt
python -m agents.demo samples/sample_executive_correspondence.txt
```

Expected output includes:

```text
WORKFLOW STATUS
document_id................... DEMO-SAMPLE_FOIA_REQUEST
status........................ in_review
document_type................. foia
sensitivity................... unclassified
...
assigned_queue................ legal_counsel
...
DEMO RESULT: PASS
```

The CLI writes `<sample>_result.json` in the current directory and exits non-zero
if the workflow fails or is incomplete.

### Verified demo outcomes

| Sample | Type | Sensitivity | Queue | Approval |
| --- | --- | --- | --- | --- |
| FOIA request | `foia` | `unclassified` | `legal_counsel` | `in_review` |
| Contract memo | `contract` | `sbu` | `contracting_officer` | `in_review` |
| Incident report | `incident_report` | `cui` | `security_team` | `in_review` |
| Executive correspondence | `executive_correspondence` | `fouo` | `chief_of_staff` | `in_review` |

Sensitive documents are never auto-approved, even at high confidence.

## 4. Run the Tests

```bash
python -m pytest tests/ -v --cov=agents --cov=workflows --cov-report=term-missing
python test_local.py
ruff check agents workflows tests lambda scripts test_local.py
python -m pip_audit -r requirements.txt
```

At the time of the audit: **73 tests passed**, coverage ~79%, lint clean, no
known dependency vulnerabilities. See
[`evidence/test-results/`](evidence/test-results/).

## 5. Run in Docker

```bash
docker build -t federal-doc-triage-agent .
docker run --rm federal-doc-triage-agent
```

Health check (the CLI has no HTTP server):

```bash
docker run -d --name triage federal-doc-triage-agent sleep 60
docker inspect --format '{{.State.Health.Status}}' triage
# healthy
docker rm -f triage
```

## 6. Terraform Validation

```bash
terraform fmt -check -recursive terraform
cd terraform
terraform init -backend=false
terraform validate
```

`validate` succeeds. `terraform apply` was **not** performed in this audit, and
the configuration does not create the Lambda function/API Gateway/SNS workflow.
See the deployment status in [../README.md](../README.md#aws-deployment-status).

## Expected Data Flow

```text
Document text
  → normalize + PII redaction
  → classification (local rules in demo, Bedrock in live mode)
  → routing (exact rule → document-type default → global default)
  → approval (unclassified + confidence > 0.85 → auto; else human review)
  → escalation check (single-run no-op unless deadline restored)
  → audit trail (DynamoDB in live mode; in-memory for demo)
```

## Troubleshooting

### `Error: Document not found at ...`

Run from the repository root, or pass an absolute path. The demo resolves the
path relative to the current working directory.

### `ModuleNotFoundError`

Activate the virtual environment and install both requirements files:

```bash
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
```

### Bedrock `AccessDeniedException`

The demo does not call Bedrock. In live mode, confirm the model ID is enabled in
your region and the caller has `bedrock:InvokeModel`. By design, a Bedrock
failure now raises instead of silently substituting local rules; set
`ALLOW_CLASSIFIER_FALLBACK=true` only if you explicitly accept that trade-off.

### `NoCredentialsError` / DynamoDB errors in live mode

Provide AWS credentials (or an instance/task role) and a reachable region. In
demo mode persistence is intentionally skipped and
`audit_persistence_mode=in_memory_demo`.

### Comprehend unavailable

Set `USE_COMPREHEND=false` to use regex detection. The code also falls back to
regex automatically if Comprehend raises or the document exceeds the synchronous
100 KB limit. This is a degraded mode, not equivalent to an ML PII engine.

### `deploy.sh` stops with "Lambda function ... was not found"

This is expected for the current repository: Terraform provisions the
data/security baseline only. The deploy script no longer reports success when
the Lambda function is absent. Complete the Lambda/API infrastructure first.

## Architecture and Evidence

- [ARCHITECTURE.md](ARCHITECTURE.md) — implemented components and limitations
- [evidence/verification-report.md](evidence/verification-report.md) — audit,
  fixes, commands, screenshots, residual risks
- [../README.md](../README.md) — full project overview

---

**Last verified:** 2026-11-01
