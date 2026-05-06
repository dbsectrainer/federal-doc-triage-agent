# Quick Start Guide

## Prerequisites

- Python 3.11+
- AWS CLI configured with GovCloud credentials
- AWS Bedrock access (Claude 3 Sonnet model)
- Docker (optional, for containerized deployment)

## Local Development

### 1. Clone & Setup

```bash
git clone https://github.com/dbsectrainer/federal-doc-triage-agent.git
cd federal-doc-triage-agent

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Configure Environment

```bash
cp .env.example .env
# Edit .env with your AWS credentials and region
```

### 3. Run Demo Workflow

```bash
# Process a sample FOIA request
python -m agents.demo samples/sample_foia_request.txt

# Or process any of the sample documents:
python -m agents.demo samples/sample_contract_memo.txt
python -m agents.demo samples/sample_incident_report.txt
python -m agents.demo samples/sample_executive_correspondence.txt
```

### 4. Expected Output

The demo will:

1. **Intake Phase**: Detect PII (emails, phone numbers, SSNs) and redact them
2. **Classification Phase**: Use Bedrock to classify the document by type, sensitivity, and urgency
3. **Routing Phase**: Assign to appropriate queue (contracting officer, legal counsel, etc.)
4. **Approval Phase**: Mark for human review with SLA deadline
5. **Audit Phase**: Generate compliance audit trail

Results are saved to `<document>_result.json` with full workflow state.

## Running Tests

```bash
# Run all tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=agents --cov=workflows

# Run specific test file
pytest tests/test_classifier.py -v
```

## Docker Deployment

### Build Container

```bash
docker build -t federal-doc-triage-agent .
```

### Run Demo in Container

```bash
docker run --rm \
  -e AWS_REGION=us-gov-west-1 \
  -e AWS_PROFILE=default \
  -v ~/.aws:/root/.aws:ro \
  federal-doc-triage-agent
```

### Run with Local Sample

```bash
docker run --rm \
  -e AWS_REGION=us-gov-west-1 \
  -v ~/.aws:/root/.aws:ro \
  -v $(pwd)/samples:/app/samples:ro \
  federal-doc-triage-agent \
  python -m agents.demo samples/sample_foia_request.txt
```

## AWS GovCloud Deployment

### 1. Deploy Infrastructure

```bash
cd terraform
cp govcloud.tfvars.example terraform.tfvars
# Edit terraform.tfvars with your values

terraform init
terraform plan
terraform apply
```

### 2. Deploy Lambda Functions

```bash
cd ..
./scripts/deploy.sh --env production --region us-gov-west-1
```

### 3. Configure S3 Trigger

Documents uploaded to the S3 intake bucket will automatically trigger the workflow.

```bash
# Upload a test document
aws s3 cp samples/sample_foia_request.txt \
  s3://your-intake-bucket/documents/ \
  --region us-gov-west-1
```

## Architecture Overview

```
Document Intake (S3 / API)
        ↓
  PII Redaction (AWS Comprehend)
        ↓
  Classification (AWS Bedrock - Claude 3 Sonnet)
        ↓
  Routing Rules Engine
        ↓
  Queue Assignment + SLA Calculation
        ↓
  Approval Workflow (Human Review)
        ↓
  Compliance Audit Logging (CloudTrail + DynamoDB)
        ↓
  Archive (S3 with Object Lock - 7 year retention)
```

## Document Types Supported

- **Contract/Procurement** — Route to Contracting Officer
- **FOIA Request** — Route to Legal Counsel
- **Policy/Memo** — Route to Policy Office
- **Incident Report** — Route to Security Team (Emergency)
- **Personnel Action** — Route to HR Office
- **Financial** — Route to Finance Office
- **Executive Correspondence** — Route to Chief of Staff
- **Legal** — Route to Legal Counsel

## Troubleshooting

### Bedrock Access Error

```
Error: Access Denied to Bedrock model
```

**Solution:** Ensure your AWS IAM role has `bedrock:InvokeModel` permission for the Claude 3 Sonnet model in your region.

### PII Detection Not Working

```
Error: AWS Comprehend service not available
```

**Solution:** AWS Comprehend may not be available in all regions. Check region availability and fall back to regex-based detection by setting `USE_COMPREHEND=false` in `.env`.

### Workflow Stuck in Approval Phase

The approval phase is designed to wait for human decision. In demo/test mode, it returns immediately with `PENDING` status. In production, it integrates with Step Functions and SNS notifications.

## Environment Variables

See `.env.example` for all available configuration options:

| Variable                  | Purpose                   | Example                                 |
| ------------------------- | ------------------------- | --------------------------------------- |
| AWS_REGION                | AWS region for deployment | us-gov-west-1                           |
| BEDROCK_MODEL_ID          | Claude model version      | anthropic.claude-3-sonnet-20240229-v1:0 |
| MAX_DOCUMENT_SIZE_MB      | Max document size         | 100                                     |
| USE_COMPREHEND            | Enable AWS Comprehend     | true                                    |
| DEFAULT_SLA_PRIORITY_DAYS | SLA for priority docs     | 5                                       |

## Next Steps

1. Review `FEDRAMP-ALIGNMENT.md` for security control mappings
2. Explore `docs/` directory for detailed architecture documentation
3. Run test suite: `pytest tests/ -v`
4. Deploy to GovCloud: `terraform apply` in `terraform/` directory
5. Configure S3 intake bucket with Lambda trigger

## Support & Questions

For issues, questions, or contributions, open an issue on GitHub:
[https://github.com/dbsectrainer/federal-doc-triage-agent/issues](https://github.com/dbsectrainer/federal-doc-triage-agent/issues)

---

**Last Updated:** 2026-05-06  
**FedRAMP Alignment:** Moderate Baseline
