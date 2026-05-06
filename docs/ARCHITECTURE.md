# System Architecture

## Multi-Agent Workflow

The Federal Document Triage Agent uses a **multi-agent orchestration** pattern with **LangGraph** to coordinate specialized agents:

```
Document Intake
     ↓
┌────────────────────────────────────────────────────────┐
│              LangGraph Workflow Orchestration            │
├────────────────────────────────────────────────────────┤
│                                                          │
│  [Intake Agent] → [Classifier Agent] → [Router Agent]  │
│       ↓                    ↓                    ↓        │
│  • PII Detection       • Document Type      • Queue      │
│  • Redaction          • Sensitivity          Assignment  │
│  • Normalization      • Urgency              • SLA       │
│  • Format Detection   • Confidence          • Reviewer   │
│                                                          │
│         ↓                                                │
│  [Approval Agent] ──→ [Escalation Agent] ──→ [Audit]   │
│       ↓                      ↓                    ↓       │
│  • Human Review        • SLA Monitoring      • Logging   │
│  • Decision Tracking   • Escalation          • Archive   │
│  • Status Updates      • Notifications       • Reports   │
│                                                          │
└────────────────────────────────────────────────────────┘
     ↓
Archive & Compliance Logging (CloudTrail + DynamoDB)
```

## Component Details

### 1. Intake Agent

**Responsibility:** Document parsing, normalization, and PII detection

**Inputs:**

- Raw document content (text)
- Document metadata (ID, source)

**Processing:**

1. Normalize whitespace and line breaks
2. Detect PII using AWS Comprehend (with regex fallback)
3. Redact sensitive information with `[REDACTED:TYPE]` placeholders
4. Extract document statistics (length, language, etc.)

**Outputs:**

- `document_content_redacted`: PII-safe content for LLM
- `pii_detection`: Metadata about PII found
  - `has_pii`: boolean
  - `entity_types`: list of detected types (SSN, EMAIL, PHONE, etc.)
  - `entity_count`: number of PII instances
  - `redaction_applied`: boolean

**Implementation:** `agents/intake_agent.py`

---

### 2. Classifier Agent

**Responsibility:** Document classification via AWS Bedrock

**Inputs:**

- Document ID
- Original content (for context)
- Redacted content (sent to LLM)

**Processing:**

1. Call AWS Bedrock API with Claude 3 Sonnet
2. Send structured JSON prompt requesting:
   - `document_type`: One of [contract, foia, policy_memo, incident_report, personnel_action, financial, executive_correspondence, legal, unknown]
   - `sensitivity_level`: One of [unclassified, cui, sbu, fouo]
   - `urgency`: One of [routine, priority, immediate, emergency]
   - `subject`: Brief subject line
   - `summary`: 2-3 sentence summary
   - `action_required`: Specific action needed
   - `originating_agency`: Agency name or null
   - `keywords`: List of relevant keywords
   - `confidence_score`: 0.0-1.0 confidence

**Outputs:**

- `ClassificationResult` with all above fields

**Implementation:** `agents/classifier_agent.py`

**FedRAMP Compliance:** Uses AWS Bedrock in GovCloud region, all requests encrypted in transit

---

### 3. Router Agent

**Responsibility:** Rule-based routing to appropriate queue and reviewer

**Routing Rules Matrix:**

| Document Type            | Sensitivity  | Primary Queue       | Backup Queue   | SLA                 |
| ------------------------ | ------------ | ------------------- | -------------- | ------------------- |
| Contract                 | CUI          | Contracting Officer | Legal Counsel  | 5 days              |
| FOIA                     | Unclassified | Legal Counsel       | Policy Office  | 10 days             |
| Policy Memo              | FOUO         | Chief of Staff      | Policy Office  | 5 days              |
| Incident Report          | CUI/FOUO     | Security Team       | Legal Counsel  | 4 hours (emergency) |
| Personnel Action         | CUI          | HR Office           | Legal Counsel  | 5 days              |
| Financial                | CUI          | Finance Office      | Chief of Staff | 5 days              |
| Executive Correspondence | FOUO         | Chief of Staff      | Policy Office  | 24 hours            |
| Legal                    | CUI/FOUO     | Legal Counsel       | Security Team  | 5 days              |

**SLA Mapping:**

| Urgency   | SLA Deadline     |
| --------- | ---------------- |
| Routine   | 10 business days |
| Priority  | 5 business days  |
| Immediate | 24 hours         |
| Emergency | 4 hours          |

**Implementation:** `agents/router_agent.py`

---

### 4. Approval Agent

**Responsibility:** Coordinate human review and decision

**Workflow:**

1. Notify assigned reviewer via SNS/SES
2. Wait for approval decision via API callback
3. Track review timestamp and notes
4. Update document status (approved/rejected/delegated)

**Integration Points:**

- AWS SNS for reviewer notification
- API Gateway for approval callbacks
- Step Functions for workflow state machine (future)

**Implementation:** `workflows/nodes.py` → `approval_node()`

---

### 5. Escalation Agent

**Responsibility:** Monitor SLA deadlines and escalate overdue items

**Triggers:**

- Current time > SLA deadline
- Approval still pending
- Multiple escalations (escalation_count > threshold)

**Actions:**

1. Log escalation event
2. Update approval status to ESCALATED
3. Notify backup reviewer
4. Increment escalation count
5. Flag for senior review

**Implementation:** `workflows/nodes.py` → `escalation_node()`

---

### 6. Auditor Agent

**Responsibility:** Compliance logging and audit trail creation

**Audit Events Logged:**

```json
{
  "event_id": "uuid",
  "timestamp": "ISO-8601",
  "document_id": "DOC-001",
  "agent": "classifier_agent",
  "action": "classify_document",
  "outcome": "success|failure",
  "metadata": {
    "document_type": "policy_memo",
    "sensitivity": "fouo",
    "confidence": 0.95
  }
}
```

**Storage:**

- CloudTrail: All AWS API calls
- DynamoDB: Document-specific audit trail
- S3: Long-term archive with Object Lock

**Implementation:** `agents/auditor_agent.py`

---

## Data Flow

### Document Processing Pipeline

```
1. Source Documents
   ├─ S3 Upload (S3 event trigger)
   ├─ API Gateway (HTTP POST)
   └─ Direct Lambda invocation (testing)

2. Intake Processing
   ├─ Read document from S3
   ├─ Normalize formatting
   ├─ Detect PII (Comprehend)
   ├─ Redact sensitive data
   └─ Store redacted content

3. Classification
   ├─ Send redacted content to Bedrock
   ├─ Claude 3 Sonnet processes
   ├─ Parse JSON response
   ├─ Validate response schema
   └─ Map to enums

4. Routing Decision
   ├─ Look up routing rule
   ├─ Assign primary queue
   ├─ Assign backup queue
   ├─ Calculate SLA deadline
   └─ Identify reviewers

5. Approval Workflow
   ├─ Notify reviewer (SNS)
   ├─ Wait for human decision
   ├─ Accept: approved/rejected/delegated
   └─ Update status

6. Monitoring & Escalation
   ├─ Check SLA deadline
   ├─ If overdue: escalate
   ├─ Notify backup reviewer
   └─ Increment escalation count

7. Compliance Logging
   ├─ Collect all audit events
   ├─ Store in DynamoDB (7-year retention)
   ├─ Archive to S3 with Object Lock
   └─ CloudTrail captures all API calls
```

---

## State Management

### TriageState TypedDict

The workflow state is managed as a TypedDict (Python 3.8+) passed between nodes:

```python
class TriageState(TypedDict):
    # Input
    document_id: str
    document_s3_key: str
    document_content: str
    document_content_redacted: str
    intake_timestamp: str  # ISO-8601

    # PII Detection
    pii_detection: Optional[PIIDetection]

    # Classification
    classification: Optional[ClassificationResult]

    # Routing
    routing: Optional[RoutingDecision]

    # Approval
    approval_status: ApprovalStatus
    approval_reviewer: Optional[str]
    approval_timestamp: Optional[str]
    approval_notes: Optional[str]
    escalation_count: int

    # Audit
    audit_trail: List[AuditEvent]

    # Error handling
    error: Optional[str]
    retry_count: int

    # Metadata
    processing_complete: bool
    workflow_version: str
```

**Implementation:** `workflows/state.py`

---

## Security & Compliance

### Encryption

**At Rest:**

- S3: AES-256 with customer-managed KMS keys
- DynamoDB: KMS encryption (optional)
- Secrets: AWS Secrets Manager (auto-rotated)

**In Transit:**

- All APIs: TLS 1.2+
- Bedrock: HTTPS encrypted
- S3: HTTPS enforced via bucket policy

### Audit Logging

**CloudTrail:**

- All AWS API calls logged
- 7-year retention (NARA compliance)
- Immutable with log file validation

**DynamoDB Audit Trail:**

- Document-specific events
- Full audit history preserved
- Query by document_id or timestamp

### Access Control

**IAM Policies:**

- Lambda execution role: S3 read/write, DynamoDB write, Bedrock invoke
- Reviewer role: DynamoDB read, API Gateway invoke
- Admin role: Full access (least needed)

**Network Security:**

- VPC endpoints for AWS services (no internet routing)
- Security groups restrict ingress to HTTPS (443)
- NACLs deny unnecessary protocols

---

## Performance Characteristics

### Throughput

- **Intake:** ~1000 docs/second (limited by Comprehend)
- **Classification:** ~50 docs/second (Bedrock API limit)
- **Routing:** ~10000 docs/second (in-memory rules)
- **Overall:** ~50 docs/second end-to-end

### Latency

| Phase                    | Latency       | Bottleneck                |
| ------------------------ | ------------- | ------------------------- |
| Intake (Comprehend)      | 500-2000ms    | AWS Comprehend API        |
| Classification (Bedrock) | 2000-5000ms   | Claude 3 Sonnet inference |
| Routing                  | 50-100ms      | DynamoDB lookup           |
| Approval (wait)          | Minutes-days  | Human decision            |
| Total                    | 2.5-7 seconds | Bedrock classification    |

### Storage

**Per Document:**

- Original content: ~100KB average
- Audit trail: ~2KB per event
- Workflow state: ~5KB

**7-Year Retention (10,000 docs/year):**

- S3 storage: ~7GB original content
- DynamoDB: ~700MB audit events
- Annual cost: ~$150-200

---

## Error Handling

### Retry Strategy

```python
if retry_count < 3:
    # Retry with exponential backoff
    wait_time = 2 ** retry_count  # 2s, 4s, 8s
    re_invoke_node()
else:
    # Escalate to manual review
    update_status(ApprovalStatus.ESCALATED)
    notify_admin()
```

### Graceful Degradation

- **Comprehend unavailable:** Fall back to regex PII detection
- **Bedrock timeout:** Retry 3x, then mark as "unknown" type
- **DynamoDB write failure:** Log to CloudWatch, retry via SQS queue

---

## Extensibility

### Adding New Document Types

1. Add to `DocumentType` enum in `workflows/state.py`
2. Add routing rule in `RouterAgent.ROUTING_RULES`
3. Update Bedrock prompt in `ClassifierAgent`
4. Add test case in `tests/test_classifier.py`

### Adding New Routing Queues

1. Add to `RoutingQueue` enum in `workflows/state.py`
2. Add queue-to-reviewer mapping in `RouterAgent._get_reviewer_for_queue()`
3. Update documentation

### Custom Classifiers

Replace Bedrock with any LLM:

```python
# Alternative: Use local model
from transformers import pipeline

classifier = pipeline("zero-shot-classification", model="facebook/bart-large-mnli")
result = classifier(text, candidate_labels=["contract", "foia", ...])
```

---

## Deployment Diagram

```
┌─────────────────────────────────────────────────────────┐
│               AWS GovCloud (us-gov-west-1)               │
├─────────────────────────────────────────────────────────┤
│                                                           │
│  ┌─ Internet Gateway ─┐                                  │
│  │                     │                                  │
│  ├─ Public Subnet (ALB)                                  │
│  │  └─ Application Load Balancer (HTTPS)                │
│  │                                                       │
│  ├─ Private Subnet (Lambda)                             │
│  │  ├─ Lambda: intake_handler                           │
│  │  ├─ Lambda: approval_handler                         │
│  │  └─ Lambda: escalation_handler                       │
│  │                                                       │
│  ├─ Database Subnet (DynamoDB)                          │
│  │  ├─ DynamoDB: audit_trail                            │
│  │  └─ DynamoDB: workflow_state                         │
│  │                                                       │
│  └─ Storage                                              │
│     ├─ S3: intake_bucket (encrypted)                    │
│     ├─ S3: archive_bucket (Object Lock, WORM)           │
│     └─ S3: cloudtrail_bucket (immutable)                │
│                                                           │
│  ┌─ Security Services ─┐                                │
│  ├─ CloudTrail (API logging)                            │
│  ├─ GuardDuty (threat detection)                        │
│  ├─ Security Hub (compliance)                           │
│  ├─ KMS (key management)                                │
│  └─ Secrets Manager (credential storage)                │
│                                                           │
└─────────────────────────────────────────────────────────┘

External Services (AWS)
├─ AWS Bedrock (Claude 3 Sonnet for classification)
├─ AWS Comprehend (PII detection)
├─ SNS (reviewer notifications)
└─ CloudWatch (monitoring & logging)
```

---

**Last Updated:** 2026-05-06  
**Architecture Version:** 1.0  
**FedRAMP Alignment:** Moderate Baseline (91.7% control coverage)
