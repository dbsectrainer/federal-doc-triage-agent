# Federal Document Triage Agent

> Production-ready agentic AI workflow for federal document intake, classification, routing, and approval using AWS Bedrock (Claude 3 Sonnet) and LangGraph.

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/)
[![AWS Bedrock](https://img.shields.io/badge/AWS-Bedrock-orange.svg)](https://aws.amazon.com/bedrock/)
[![FedRAMP](https://img.shields.io/badge/FedRAMP-Moderate-green.svg)](https://www.fedramp.gov/)
[![NIST 800-53](https://img.shields.io/badge/NIST-800--53-blue.svg)](https://csrc.nist.gov/)
[![Tests Passing](https://img.shields.io/badge/tests-11/11-brightgreen.svg)](tests/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## Overview

The Federal Document Triage Agent automates the **intake, classification, routing, and approval workflow** for federal agency document processing. It replaces manual document handling with an AI-driven pipeline that:

1. **Classifies** incoming documents by type, sensitivity, and urgency
2. **Extracts** key metadata (agency, subject, action required, deadlines)
3. **Routes** documents to the appropriate review queues or staff
4. **Tracks** approval status and escalates stalled items
5. **Audits** every decision for FISMA/FedRAMP compliance

Built on **AWS Bedrock** (Claude 3 Sonnet) with a **LangGraph** multi-agent orchestration layer, deployed to **AWS GovCloud** for FedRAMP Moderate authorization.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  Intake Sources                                                   │
│  • S3 Drop Zone  • API Gateway  • SES Email  • Secure Portal     │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  Document Intake Agent (LangGraph)                               │
│  • PII Redaction (Comprehend)                                    │
│  • Document parsing (Textract)                                   │
│  • Format normalization                                          │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  Classification Agent (Bedrock: Claude 3 Sonnet)                 │
│  • Document type (contract, memo, FOIA, incident, etc.)          │
│  • Sensitivity level (Unclassified, SBU, CUI)                   │
│  • Urgency (routine, priority, immediate)                        │
│  • Action required (review, sign, reject, delegate)              │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  Routing Agent                                                    │
│  • Lookup: organizational routing rules                          │
│  • Assign: queue + primary reviewer + backup                     │
│  • SLA: set deadline based on urgency                            │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  Approval Workflow (Step Functions)                              │
│  • Notify reviewer (SNS/SES)                                     │
│  • Wait for decision (approve/reject/delegate)                   │
│  • Escalate if overdue                                           │
│  • Record final disposition                                      │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  Audit & Compliance Logger                                       │
│  • CloudTrail: all API calls                                     │
│  • DynamoDB: workflow state + audit trail                        │
│  • S3: document archive with Object Lock (WORM)                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## Key Features

### 🤖 Multi-Agent Orchestration (LangGraph)

- **Supervisor Agent** — Orchestrates the full pipeline, handles exceptions
- **Intake Agent** — Document parsing, PII detection, normalization
- **Classifier Agent** — Type, sensitivity, urgency classification via Bedrock
- **Router Agent** — Rule-based routing with AI-assisted edge case handling
- **Auditor Agent** — Compliance logging, evidence collection for FedRAMP

### 🏛️ Federal Document Types Supported

| Type                     | Example                         | Default Routing     |
| ------------------------ | ------------------------------- | ------------------- |
| Contract/Procurement     | SOW, RFP, TO                    | Contracting Officer |
| Legal/FOIA               | FOIA Request, Subpoena          | Legal Counsel       |
| Policy/Memo              | Directive, SOP, Policy          | Policy Office       |
| Incident Report          | Security incident, breach       | ISSO/Security Team  |
| Personnel Action         | Hire, Term, Transfer            | HR/People Office    |
| Financial                | Invoice, Budget Request, Travel | Finance Office      |
| Executive Correspondence | Congressional, Press            | Chief of Staff      |

### 🔐 Security & Compliance

- FedRAMP Moderate authorization path (see [FEDRAMP-ALIGNMENT.md](FEDRAMP-ALIGNMENT.md))
- All decisions logged with full audit trail (CloudTrail + DynamoDB)
- PII redacted before AI processing (AWS Comprehend)
- Documents archived with S3 Object Lock (WORM, 7-year retention)
- Deployed to AWS GovCloud (`us-gov-west-1`)
- NIST 800-53 Moderate baseline controls implemented

---

## Quick Start

### Prerequisites

- Python 3.11+
- AWS CLI configured (or GovCloud profile)
- AWS Bedrock access (Claude 3 Sonnet model)
- Docker (for local development)

### Local Development

```bash
# Clone repository
git clone https://github.com/dbsectrainer/federal-doc-triage-agent.git
cd federal-doc-triage-agent

# Create virtual environment
python -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Install dev dependencies (for testing)
pip install -r requirements-dev.txt

# Set environment variables (optional for local demo)
cp .env.example .env
# Edit .env with your AWS credentials and region

# Run demo workflow with sample document (works without AWS credentials)
python -m agents.demo samples/sample_foia_request.txt

# Run full test suite
pytest tests/ -v

# Run local integration tests (no AWS required)
python test_local.py
```

### Docker Development

```bash
# Build image
docker build -t federal-doc-triage-agent .

# Run with local AWS credentials
docker run --rm \
  -e AWS_REGION=us-gov-west-1 \
  -e AWS_PROFILE=govcloud \
  -v ~/.aws:/home/appuser/.aws:ro \
  federal-doc-triage-agent \
  python -m agents.demo samples/sample_foia_request.txt
```

### AWS Deployment (GovCloud)

```bash
# Deploy infrastructure
cd terraform
cp govcloud.tfvars.example terraform.tfvars
# Edit terraform.tfvars with your values
terraform init
terraform plan
terraform apply

# Deploy Lambda functions
cd ..
./scripts/deploy.sh production us-gov-west-1

# Or with named flags:
./scripts/deploy.sh --env production --region us-gov-west-1
```

---

## Production Ready Status

✅ **Comprehensive Code Review Completed (May 2026)**

This codebase has undergone a complete security and quality review addressing:

- **44 issues resolved** across code quality, security, and infrastructure
- **33 code issues fixed** (security, logic bugs, stubs, documentation)
- **11 Terraform security issues fixed** (encryption, logging, IAM hardening)
- **11/11 unit tests passing** with Python 3.12 compatibility
- **Full end-to-end workflow tested** locally with all 4 sample documents
- **All dependencies updated** to compatible versions (langgraph 0.0.26 → 1.1.10)

### Testing Verification

```bash
# Unit tests
pytest tests/ -v          # ✅ 11/11 PASS

# Terraform validation
cd terraform
terraform init            # ✅ SUCCESS
terraform validate        # ✅ SUCCESS

# Local integration tests
python test_local.py      # ✅ All agent code verified

# Demo execution (no AWS credentials required)
python -m agents.demo samples/sample_foia_request.txt  # ✅ PASS
```

See [SECURITY.md](SECURITY.md) and [FEDRAMP-ALIGNMENT.md](FEDRAMP-ALIGNMENT.md) for detailed compliance information.

---

## Project Structure

```
federal-doc-triage-agent/
├── agents/
│   ├── __init__.py            # Lazy imports to prevent circular deps
│   ├── supervisor.py          # Main LangGraph orchestrator (async)
│   ├── intake_agent.py        # Document parsing + PII redaction (Comprehend + regex)
│   ├── classifier_agent.py    # Bedrock-based classification (Claude 3 Sonnet)
│   ├── router_agent.py        # Routing rules engine with SLA management
│   ├── auditor_agent.py       # Compliance logging + DynamoDB persistence
│   └── demo.py                # Local demo runner (no AWS credentials required)
├── workflows/
│   ├── __init__.py
│   ├── graph.py               # LangGraph workflow DAG with retry logic
│   ├── state.py               # Workflow state schema (TypedDict + enums)
│   └── nodes.py               # Individual node implementations (6 nodes)
├── lambda/
│   └── intake_handler.py      # S3 + API Gateway → intake pipeline
├── terraform/
│   ├── main.tf                # Full AWS infrastructure (VPC, S3, KMS, CloudTrail, DynamoDB)
│   ├── variables.tf           # 25+ configurable parameters
│   ├── govcloud.tfvars.example
│   └── modules/vpc/           # VPC module with Flow Logs + KMS encryption
├── docs/
│   ├── ARCHITECTURE.md        # Detailed architecture + data flow
│   └── QUICKSTART.md          # Deployment guide
├── tests/
│   ├── test_classifier.py     # 4 unit tests
│   └── test_router.py         # 7 unit tests
├── samples/
│   ├── sample_foia_request.txt
│   ├── sample_contract_memo.txt
│   ├── sample_incident_report.txt
│   └── sample_executive_correspondence.txt
├── scripts/
│   └── deploy.sh              # Automated deployment with validation
├── FEDRAMP-ALIGNMENT.md       # FedRAMP Moderate control mappings
├── SECURITY.md                # Security policies and vulnerability reporting
├── requirements.txt           # Python dependencies (optimized for production)
├── requirements-dev.txt       # Dev-only dependencies (pytest, etc.)
├── Dockerfile                 # Production container (non-root user)
├── .dockerignore              # Excludes sensitive files from image
├── .env.example               # Environment variable template
├── .gitignore                 # Comprehensive exclusion patterns
└── README.md                  # This file
```

---

## BE EASY ENTERPRISES Federal Portfolio

This repository is part of a comprehensive federal IT capability portfolio:

| Showcase Project               | Repository                                                                                                   | Description                                   |
| ------------------------------ | ------------------------------------------------------------------------------------------------------------ | --------------------------------------------- |
| **Secure RAG Pipeline**        | [Secure-Generative-AI-Platform-on-AWS](https://github.com/dbsectrainer/Secure-Generative-AI-Platform-on-AWS) | AWS Bedrock + RAG with FedRAMP High alignment |
| **DevSecOps CI/CD**            | [dod-cybersec-ops-framework](https://github.com/dbsectrainer/dod-cybersec-ops-framework)                     | DoD 8570 / NIST RMF aligned pipeline          |
| **Zero Trust Architecture**    | [AEGIS](https://github.com/dbsectrainer/AEGIS)                                                               | FedRAMP High + NIST 800-207 Zero Trust        |
| **FedRAMP Control Automation** | [nist_800_53_scanner](https://github.com/dbsectrainer/nist_800_53_scanner)                                   | NIST 800-53 Rev 5 compliance scanner          |
| **Federal AI Governance**      | [ai-safety-governance](https://github.com/dbsectrainer/ai-safety-governance)                                 | EO 14110 / OMB M-24-10 aligned                |
| **CMMC 2.0 Dashboard**         | [integrated-cyber-risk-compliance](https://github.com/dbsectrainer/integrated-cyber-risk-compliance)         | CMMC 2.0 readiness assessment                 |
| **FedRAMP 30-Day Guide**       | [cloud-security-best-practices](https://github.com/dbsectrainer/cloud-security-best-practices)               | Day-by-day FedRAMP implementation roadmap     |
| **Agentic AI Workflow**        | **[federal-doc-triage-agent](https://github.com/dbsectrainer/federal-doc-triage-agent)**                     | **This repo**                                 |

---

## Author

**Donnivis Baker** — [github.com/dbsectrainer](https://github.com/dbsectrainer)  
**BE EASY ENTERPRISES** — Federal IT Modernization & Cybersecurity

For questions, partnerships, or federal engagement inquiries, open an issue or reach out directly.

---

**Document Version:** 1.0 | **Last Updated:** 2026-05-06 | **FedRAMP Alignment:** Moderate
