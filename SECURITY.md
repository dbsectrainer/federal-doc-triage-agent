# Security Policy

## Reporting Security Vulnerabilities

If you discover a security vulnerability in the Federal Document Triage Agent,
please email **security@beeasenterprises.com** with:

- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if available)

Please do not publicly disclose the issue until BE EASY ENTERPRISES has had time
to address it.

---

## Scope and Verification Status

This repository is a **reference implementation**, not an authorized federal
system. `FEDRAMP-ALIGNMENT.md` maps intended controls; it is **not** an
authorization, assessment, or evidence of FedRAMP compliance. No independent
penetration test, 3PAO assessment, or live AWS security review was performed.

The security properties below were verified locally by tests (see
[`docs/evidence/verification-report.md`](docs/evidence/verification-report.md)).
Properties marked **not verified** require a deployed AWS environment and were
not exercised in this audit.

---

## Implemented and Tested

### Data protection

- PII detection/redaction before classification:
  - AWS Comprehend when `USE_COMPREHEND=true` and the document is ≤100 KB;
  - regex fallback for demo mode, Comprehend failures, or oversized input.
  - Overlapping spans are merged (longest wins) before right-to-left redaction.
- Lambda workflow-state writes **exclude** raw and redacted document bodies.
- Audit events are scoped per workflow invocation via a `ContextVar`, preventing
  cross-document audit contamination under concurrent processing.
- Audit persistence failure marks the workflow incomplete instead of silently
  claiming success.

### Approval controls

- CUI, SBU, and FOUO documents **cannot** be auto-approved, regardless of model
  confidence.
- Auto-approval is limited to unclassified documents above the configured
  confidence threshold (default 0.85, strict `>`).

### AI input handling

- Document IDs are sanitized before being placed in the prompt.
- Document text is wrapped in `<document>` tags and explicitly labeled untrusted.
- Classifier input is truncated (`MAX_CLASSIFICATION_CHARS`, default 60,000).
- Local heuristic fallback after a Bedrock failure is **off by default**
  (`ALLOW_CLASSIFIER_FALLBACK=false`), so an AWS failure is visible rather than
  silently producing a heuristic decision.
- Model output enums/values are validated and clamped.

### API/Lambda input handling

- Document IDs are validated (`[A-Za-z0-9_-]{1,256}`).
- API Gateway request bodies are size-limited (`MAX_DOCUMENT_SIZE_MB`) and
  base64 decoding is strict.
- Error responses do not echo raw exception text to callers.
- DynamoDB items are sanitized (no `None`/empty collections, floats as
  `Decimal`, enums as values).

### Supply chain and container

- Dependencies are pinned; `pip-audit[^1]` reported **no known vulnerabilities**
  after the audit upgrades.
- The container runs as non-root `appuser`.
- `.dockerignore` excludes `.env`, virtualenvs, tests, docs, Terraform state, and
  git metadata. Verified: the built image does not contain `/app/.env`.
- The Docker health check imports and compiles the workflow graph; it does not
  expose an HTTP endpoint (there is no HTTP server).

[^1]: Verified 2026-11-01; re-run `python -m pip_audit -r requirements.txt`.

---

## Not Implemented or Not Verified

Do **not** claim these controls based on this repository alone:

| Area | Gap |
| --- | --- |
| Lambda execution IAM | No Lambda function/role is provisioned in Terraform; least-privilege runtime policies were not created or tested |
| Network isolation | Terraform creates a VPC and flow logs, but Lambda/VPC endpoints/security groups for the application are not wired |
| Reviewer notifications | No SNS/SES/Step Functions human-in-the-loop implementation |
| Secrets management | No Secrets Manager integration; environment variables are used for settings, AWS SDK credentials come from the standard provider chain |
| Authentication/authorization | No Cognito/MFA/API authorization layer exists |
| Archive/WORM | Terraform creates an Object Lock bucket, but no code writes processed documents to it |
| CloudTrail integration | CloudTrail is infrastructure-only; the app does not query it |
| PII engine accuracy | Comprehend and Textract paths were mocked, not live-validated |
| Incident response | No `docs/incident-response.md` or tested runbook exists |
| FedRAMP/FISMA | No authorization, assessment, or continuous-monitoring evidence |

`RDS`, `EBS`, `Cognito`, `Secrets Manager`, `WAF`, and `Istio` are not used by
this repository. Older documentation that referenced them was inaccurate.

---

## Development Security Practices

### Dependency audit

```bash
python -m pip_audit -r requirements.txt
```

### Tests and lint

```bash
python -m pytest tests/ -v --cov=agents --cov=workflows
ruff check agents workflows tests lambda test_local.py
```

### Code review checklist

- No hardcoded AWS keys, passwords, tokens, or account-specific values.
- No raw document content in logs, DynamoDB state items, or error responses.
- PII redaction happens before any external LLM call.
- Sensitive documents remain human-reviewed.
- New external calls have timeouts/error handling and tests with mocks.
- `.env` is never committed; `.env.example` contains placeholders only.

### Container

```bash
docker build -t federal-doc-triage-agent .
docker run --rm federal-doc-triage-agent sh -c 'test ! -f /app/.env'
```

---

## Deployment Security Checklist (Future Work)

These are **requirements**, not claims of completion:

- [ ] Implement the Lambda IAM role with least-privilege S3/DynamoDB/Bedrock/
      Comprehend/Textract/KMS permissions.
- [ ] Add VPC endpoints/security groups or explicitly document the network path.
- [ ] Provision the Lambda function, API Gateway, and S3 event notification.
- [ ] Replace hardcoded reviewer IDs with an authenticated directory lookup.
- [ ] Add SNS/SES/Step Functions approval notifications and state persistence.
- [ ] Add CloudWatch alarms, retention, and audit-failure alerting.
- [ ] Run live integration tests in a non-production AWS account.
- [ ] Complete a FedRAMP/security assessment before any production use.

---

## Compliance

The repository is *designed with alignment to* NIST SP 800-53 Rev. 5, NIST SP
800-171 Rev. 2, FedRAMP Moderate concepts, FISMA, and OMB M-24-10. See
[`FEDRAMP-ALIGNMENT.md`](FEDRAMP-ALIGNMENT.md) for the control mapping and its
implementation-status banner. Alignment is not authorization.

---

## Questions

- **Security:** security@beeasenterprises.com
- **Compliance:** compliance@beeasenterprises.com
- **GitHub Security:** https://github.com/dbsectrainer/federal-doc-triage-agent/security

---

**Last verified:** 2026-11-01
**Classification:** Unclassified / public repository
