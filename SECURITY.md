# Security Policy

## Reporting Security Vulnerabilities

If you discover a security vulnerability in the Federal Document Triage Agent, please email security@beeasenterprises.com with:

- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if available)

**Please do not publicly disclose security vulnerabilities** until BE EASY ENTERPRISES has had time to address them.

---

## Security Controls

This project implements NIST SP 800-53 Moderate baseline security controls. See `FEDRAMP-ALIGNMENT.md` for detailed control mappings.

### Key Security Features

#### Authentication & Authorization

- AWS IAM with least-privilege service roles
- MFA enforcement via Cognito
- Service-to-service authentication via IAM
- No hardcoded credentials (use AWS Secrets Manager)

#### Data Protection

- AES-256 encryption at rest (S3, RDS, EBS via KMS)
- TLS 1.2+ encryption in transit
- PII redaction via AWS Comprehend + regex patterns
- S3 Object Lock for immutable audit logs (7-year NARA retention)

#### Logging & Auditing

- AWS CloudTrail for all API calls
- DynamoDB audit trail for all document processing
- CloudWatch Logs for application events
- Signed CloudTrail log file validation

#### Network Security

- VPC isolation with private subnets
- Security groups enforce least privilege
- Network ACLs restrict traffic
- VPC endpoints for AWS API calls (no internet routing)

#### Secrets Management

- AWS Secrets Manager for credential storage
- Automatic credential rotation
- No secrets in environment variables or code
- Least-privilege IAM for secrets access

#### Code Security

- No hardcoded AWS keys, API tokens, or credentials
- Input validation on all API endpoints
- Output encoding to prevent injection
- Dependency scanning (via pip-audit, Dependabot)

---

## Development Security Practices

### Pre-Commit Hooks

Enable pre-commit hooks to catch common security issues:

```bash
pip install pre-commit
pre-commit install
```

### Dependency Scanning

Regularly audit Python dependencies:

```bash
pip-audit
```

### Code Review

All code changes require review before merging. Reviewers should:

- Check for hardcoded secrets (AWS keys, passwords, tokens)
- Verify proper error handling (no stack traces to users)
- Confirm input validation is present
- Check for SQL injection / command injection vectors
- Verify encryption is used for sensitive data

### Testing

Run full test suite before committing:

```bash
pytest tests/ --cov=agents --cov=workflows
```

---

## FedRAMP Security Requirements

This implementation complies with FedRAMP Moderate baseline requirements:

### Control Categories

| Category                                | Controls | Status             |
| --------------------------------------- | -------- | ------------------ |
| Access Control (AC)                     | 22       | ✓ 91% implemented  |
| Audit & Accountability (AU)             | 13       | ✓ 100% implemented |
| Identification & Authentication (IA)    | 11       | ✓ 100% implemented |
| System & Communications Protection (SC) | 40       | ✓ 95% implemented  |
| System & Information Integrity (SI)     | 14       | ✓ 100% implemented |

See `FEDRAMP-ALIGNMENT.md` for complete control mapping.

---

## Deployment Security

### Pre-Deployment Checklist

- [ ] Enable CloudTrail logging to immutable S3 bucket
- [ ] Configure KMS customer-managed encryption keys
- [ ] Enable S3 block-public-access on all buckets
- [ ] Enable MFA for IAM root account
- [ ] Configure security groups with least-privilege rules
- [ ] Enable VPC Flow Logs for network monitoring
- [ ] Configure GuardDuty for threat detection
- [ ] Enable AWS Security Hub for compliance dashboard
- [ ] Enable automatic RDS backups
- [ ] Configure SNS alerts for security events

### Post-Deployment Verification

```bash
# Run NIST 800-53 baseline scan
./scripts/run_security_scan.sh --framework nist_800_53_moderate

# Generate compliance report
python scripts/generate_compliance_report.py --output fedramp_report.html

# Run automated tests
pytest tests/ -v
```

---

## Incident Response

If a security incident is detected:

1. **Isolate** — Disconnect affected systems
2. **Investigate** — Review CloudTrail and DynamoDB audit logs
3. **Remediate** — Apply fixes and patches
4. **Notify** — Contact US-CERT (per FISMA requirements)
5. **Report** — Submit incident report to OMB (per OMB M-24-10)

See `docs/incident-response.md` for detailed procedures.

---

## Compliance

This project aligns with:

- **NIST SP 800-53 Rev. 5** — Security and Privacy Controls
- **NIST SP 800-171 Rev. 2** — Protecting CUI in Nonfederal Systems
- **FedRAMP Security Requirements** — Moderate baseline
- **FISMA** — Federal Information Security Management Act
- **OMB M-24-10** — Memorandum for Federal AI Governance

---

## Questions?

For security questions or policy clarification, contact:

- **Security**: security@beeasenterprises.com
- **Compliance**: compliance@beeasenterprises.com
- **GitHub Issues**: [https://github.com/dbsectrainer/federal-doc-triage-agent/security](https://github.com/dbsectrainer/federal-doc-triage-agent/security)

---

**Last Updated:** 2026-05-06  
**Classification:** For Official Use Only (FOUO)
