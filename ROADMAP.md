# Federal Document Triage Agent — React Frontend Roadmap

**Status:** Planning Phase | **Last Updated:** 2026-05-06

---

## Executive Summary

This roadmap outlines the development of a production-grade React frontend for the Federal Document Triage Agent, enabling federal reviewers to approve/reject/delegate documents through a secure web UI rather than AWS console access. The frontend will integrate with the existing LangGraph backend, enforce FedRAMP Moderate controls, and support federal authentication (PIV/CAC + Cognito).

**Estimated Timeline:** 16-20 weeks  
**Team Size:** 2 FE + 1 backend engineer  
**Budget Category:** Medium (~$150-200K estimated)

---

## Phase 1: Foundation & Auth (Weeks 1-5)

### Goals

- Establish React project structure with security best practices
- Implement federal authentication (CAC/PIV + AWS Cognito)
- Create protected API integration layer
- Build CI/CD pipeline for GovCloud deployment

### Features

#### 1.1 Project Setup

- **React 18** with TypeScript (strict mode)
- **Vite** build tool (faster than CRA)
- **TailwindCSS** for styling (GDS-aligned components)
- **Redux Toolkit** for state management
- **React Query** for data fetching + caching
- **Sentry** for error tracking (FedRAMP-ready)
- **Husky** + **Lint-staged** for pre-commit hooks

**Deliverables:**

- `/frontend` directory structure
- `tsconfig.json` with strict settings
- `.eslintrc.json` + `.prettierrc.json`
- GitHub Actions workflow for lint/test/build
- Docker multi-stage build for GovCloud deployment

**Dependencies to Add:**

```json
{
  "react": "^18.2.0",
  "typescript": "^5.3.0",
  "vite": "^5.0.0",
  "@reduxjs/toolkit": "^1.9.7",
  "@tanstack/react-query": "^5.28.0",
  "axios": "^1.6.2",
  "@aws-amplify/ui-react": "^6.0.0",
  "@aws-amplify/auth": "^6.0.0",
  "tailwindcss": "^3.4.0",
  "sentry": "^7.89.0"
}
```

#### 1.2 Federal Authentication (CAC/PIV + Cognito)

- **CAC/PIV Support:**
  - Integrate with `@aws-amplify/auth` for Cognito federation
  - Client certificate authentication via API Gateway mutual TLS
  - Support smart card readers (macOS + Windows)
  - Fallback to temporary credentials for testing

- **AWS Cognito Setup (Terraform):**
  - User pool in GovCloud with MFA required
  - Federated identity provider (PIV/CAC via AWS IAM roles)
  - Refresh token rotation (24 hours)
  - Session timeout (15 minutes inactivity)

- **Components:**
  - `LoginPage` → smart card prompt + CAC certificate selection
  - `SessionManager` → token refresh + timeout handling
  - `ProtectedRoute` → wrapper for authenticated pages

**Security Requirements:**

- TLS 1.2+ only (no fallback)
- HTTP-only, Secure, SameSite cookies
- CSP headers (no unsafe-inline, strict script-src)
- X-Frame-Options: DENY
- X-Content-Type-Options: nosniff
- Certificate pinning for API calls

**Deliverables:**

- Cognito user pool + identity provider config (Terraform)
- `AuthContext` + `useAuth()` hook
- `LoginPage` with CAC prompt + error handling
- E2E tests for auth flow (Playwright)
- Auth security audit checklist

#### 1.3 API Integration Layer

- **Axios client** with interceptors:
  - Auto-attach auth tokens
  - Retry logic (exponential backoff)
  - Request/response logging (non-PII)
  - Error boundary handling
- **API wrapper** for backend endpoints:
  - `GET /api/documents/queue` — reviewer's pending queue
  - `GET /api/documents/{id}` — document details + classification
  - `POST /api/documents/{id}/approve` — submit approval
  - `GET /api/audit-trail` — compliance log viewer
  - `GET /health` — backend health check

- **Type-safe API client:**
  ```typescript
  // Generated from OpenAPI spec via Swagger Codegen
  export interface DocumentQueue { ... }
  export interface ClassificationResult { ... }
  export const apiClient = new ApiClient(baseURL, authToken)
  ```

**Deliverables:**

- `src/api/client.ts` — Axios instance + interceptors
- `src/api/endpoints.ts` — All API routes (typed)
- `src/hooks/useAPI.ts` — React Query integration
- API documentation (Swagger/OpenAPI)
- Mock API server for local development

#### 1.4 CI/CD & Deployment Pipeline

- **GitHub Actions:**
  - Lint (ESLint) + format (Prettier)
  - Type check (TypeScript)
  - Unit tests (Jest) → >80% coverage
  - E2E tests (Playwright) → login + approval flow
  - SAST (Snyk, Dependabot) for vulnerabilities
  - Build Docker image on main branch
  - Deploy to AWS GovCloud staging

- **Terraform for GovCloud Deployment:**
  - CloudFront CDN with custom domain
  - S3 bucket for SPA hosting (with WORM Object Lock)
  - KMS encryption at rest
  - WAF rules (rate limit, SQL injection, XSS)
  - CloudWatch logs + alarms
  - Cost: ~$200-300/month

**Deliverables:**

- `.github/workflows/ci.yml` (lint → test → build)
- `.github/workflows/deploy.yml` (merge to main → deploy to staging)
- `terraform/frontend/` — CloudFront + S3 + WAF config
- `Dockerfile` for frontend (multi-stage, non-root user)
- Deployment runbook

---

## Phase 2: Reviewer Dashboard & Approval Workflow (Weeks 6-11)

### Goals

- Build core reviewer interface: queue view, document preview, approval actions
- Implement real-time notifications (WebSocket or polling)
- Create audit trail viewer for compliance

### Features

#### 2.1 Reviewer Queue Dashboard

- **Queue View:**
  - Table of pending documents (sortable, filterable)
  - Columns: ID, type, sensitivity, urgency, SLA deadline, days pending
  - Color-coded urgency badges (routine=blue, priority=yellow, emergency=red)
  - Expandable rows for quick preview
  - Bulk actions (reassign, mark reviewed, escalate)
  - Search by document ID or subject
  - Filter: by sensitivity, urgency, queue, assigned_to

- **SLA Status Visualization:**
  - Progress bar: % of SLA deadline elapsed
  - "Overdue" badge if past deadline
  - Escalation counter (X escalations)
  - Next escalation due: HH:MM

- **Components:**
  - `QueueTable` — main table with React Table (TanStack)
  - `DocumentRow` — expandable preview
  - `SLABadge` — color-coded deadline indicator
  - `BulkActionBar` — checkboxes + action buttons

**Data Fetching:**

```typescript
// React Query hook
useDocumentQueue(options: {
  filters?: { sensitivity, urgency, queue }
  sort?: { field, direction }
  page: number
  limit: 50
})
```

**Deliverables:**

- `src/pages/QueueDashboard.tsx`
- `src/components/QueueTable/`
- `src/components/SLAIndicator.tsx`
- Storybook stories for all components
- Unit tests (>90% coverage)

#### 2.2 Document Review & Approval Workflow

- **Document View:**
  - Header: ID, type, classification confidence, SLA deadline
  - Metadata: document_type, sensitivity_level, urgency, originating_agency
  - PII-redacted content preview (syntax highlighting for code)
  - Classification results (with confidence scores)
  - Extracted metadata (subject, summary, keywords)
  - Recommended action (e.g., "Route to Legal Counsel")

- **Approval Actions:**
  - **Approve** → status=APPROVED, add reviewer signature
  - **Reject** → status=REJECTED, require rejection reason (free text)
  - **Delegate** → reassign to another reviewer (dropdown)
  - **Request More Info** → flag for intake agent (Bedrock reclassification)
  - **Escalate** → bump to senior reviewer + email notification

- **Components:**
  - `DocumentReview` — main page layout
  - `DocumentMetadata` — classification + extracted data
  - `DocumentContent` — PII-safe content viewer
  - `ApprovalActionBar` — buttons for approve/reject/delegate
  - `RejectionReasonDialog` — modal for rejection details
  - `DelegateDialog` — reassign to another reviewer

**API Integration:**

```typescript
POST /api/documents/{id}/approve
{
  status: "APPROVED" | "REJECTED" | "DELEGATED"
  reviewer_signature: string  // Base64 CAC certificate
  notes?: string
  delegated_to?: string  // Reviewer email
  timestamp: ISO-8601
}

Response: { approval_id, status, audit_event_id }
```

**Security:**

- Read-only document content (no copy/paste for SBU documents)
- Audit log every approval action (with user + timestamp)
- Session timeout → force re-authentication
- No caching of PII-redacted content on client

**Deliverables:**

- `src/pages/DocumentReview.tsx`
- `src/components/DocumentPreview/`
- `src/components/ApprovalWorkflow/`
- `src/hooks/useDocumentApproval.ts`
- Unit + integration tests
- Playwright E2E test: upload → classify → approve workflow

#### 2.3 Real-Time Notifications

- **WebSocket or Server-Sent Events (SSE):**
  - New document assigned to reviewer
  - Document reclassified → confidence changed significantly
  - SLA deadline approaching (30 min warning)
  - Escalation occurred → requires action
  - Another reviewer delegated to you

- **Notification Center:**
  - Bell icon (top nav) → shows pending notifications
  - Click → opens side panel with notification history
  - Mark as read / dismiss individual notifications
  - Notification preferences: email, in-app, push

- **Components:**
  - `NotificationCenter` — bell icon + dropdown
  - `NotificationPanel` — full notification feed
  - `NotificationItem` — individual notification card
  - `useNotifications()` — React hook for polling/WebSocket

**Backend Requirements:**

- SNS topic → Lambda → WebSocket API or HTTP polling
- Fallback: long-polling if WebSocket not available
- Message format: `{ type, document_id, message, timestamp, action_url }`

**Deliverables:**

- `src/hooks/useNotifications.ts`
- `src/components/NotificationCenter/`
- WebSocket / SSE integration (abstracted via Context)
- Notification preferences page
- Backend SNS → Lambda integration (Terraform)

#### 2.4 Audit Trail Viewer

- **Audit Log Table:**
  - Columns: timestamp, action (classify, route, approve), agent/user, outcome, document_id
  - Filter by: document_id, timestamp range, action type, user
  - Export to CSV (filtered results)
  - Full-text search (document ID, user email)

- **Compliance Report Generator:**
  - Generate PDF: document + full audit trail (7-year retention proof)
  - Signature field for reviewer attestation
  - QR code → links to CloudTrail record

- **Components:**
  - `AuditTrailViewer` — main audit log table
  - `AuditFilter` — date range + action filter
  - `ComplianceReportGenerator` — PDF export

**API:**

```typescript
GET /api/audit-trail
  ?document_id=DOC-001
  &start_date=2026-01-01
  &end_date=2026-05-06
  &action=approve,classify
  &limit=100

Response: AuditEvent[]
{
  event_id: UUID
  timestamp: ISO-8601
  document_id: string
  action: string
  agent: string
  user_email?: string
  outcome: "success" | "failure"
  metadata: object
}
```

**Deliverables:**

- `src/pages/AuditTrail.tsx`
- `src/components/AuditFilter.tsx`
- `src/components/ComplianceReport.tsx`
- `src/utils/pdfGenerator.ts` (jsPDF + html2pdf)
- Unit tests
- Playwright test: filter audit trail → export CSV

---

## Phase 3: Advanced Features & Hardening (Weeks 12-16)

### Goals

- Multi-factor approval workflows
- Analytics dashboard for compliance metrics
- Admin panel for reviewer management
- Performance optimization + security hardening

### Features

#### 3.1 Multi-Factor Approval (for CUI Documents)

- **Dual Reviewer Approval:**
  - CUI documents require approval from 2+ reviewers
  - First reviewer → "Pending Secondary Approval"
  - Second reviewer gets notification → approves/rejects
  - Both signatures captured (CAC certificates)

- **Approval Workflow State Machine:**
  - PENDING → FIRST_APPROVAL_SUBMITTED → SECOND_APPROVAL_PENDING → APPROVED/REJECTED

- **Components:**
  - `MultiApproverWorkflow` — shows pending approvers
  - `SecondaryApprovalQueue` — queue for second reviewer
  - `ApprovalHistory` — timeline of who approved when

**Deliverables:**

- Backend: Step Functions state machine for multi-approval
- Frontend: Components + hooks for multi-approval UX
- Tests: E2E Playwright test with 2 users

#### 3.2 Compliance Analytics Dashboard

- **Metrics:**
  - Documents processed (today, week, month)
  - Average time to approval (by document type)
  - SLA compliance rate (% on-time)
  - Document type distribution (pie chart)
  - Sensitivity distribution (stacked bar)
  - Top escalation reasons

- **Charts:**
  - Recharts for all visualizations
  - Drill-down: click bar → see documents in that category

- **Export:**
  - PDF report (daily/weekly summary)
  - CSV export of underlying data

**Components:**

- `ComplianceDashboard` — main page
- `MetricCard` — KPI with trend
- `TimeSeriesChart` — documents processed over time
- `DistributionChart` — pie/bar charts

**Backend API:**

```typescript
GET /api/analytics/metrics
  ?start_date=2026-01-01&end_date=2026-05-06
  &group_by=document_type|sensitivity|day

Response: {
  documents_processed: number
  avg_approval_time_hours: number
  sla_compliance_rate: 0.95
  by_type: { contract: 50, foia: 30, ... }
  timeline: [{ date, count }, ...]
}
```

**Deliverables:**

- `src/pages/Analytics.tsx`
- `src/components/MetricCard.tsx`
- Recharts integration
- Unit tests for calculations
- Playwright E2E test

#### 3.3 Admin Panel

- **Features:**
  - Manage reviewers: add, deactivate, change queue assignments
  - View all documents (not filtered to user's queue)
  - Override approvals (with audit trail flag: "ADMIN_OVERRIDE")
  - Manage routing rules (UI for adding/editing rules)
  - System health: Lambda errors, DynamoDB capacity, API latency

- **Access Control:**
  - Admin role (IAM: `admin` group)
  - Strict RBAC: reviewers vs. admins
  - All admin actions logged with rationale

- **Components:**
  - `AdminDashboard` — main page
  - `ReviewerManagement` — add/deactivate users
  - `SystemHealth` — CloudWatch metrics
  - `RoutingRulesEditor` — visual rule builder

**Deliverables:**

- `src/pages/Admin/`
- RBAC enforced at route level + API level
- Audit logging for all admin actions
- Tests for admin actions

#### 3.4 Security Hardening

- **Content Security Policy (CSP):**
  - Strict `script-src` (no inline scripts, only bundles)
  - `style-src` from Tailwind only
  - `connect-src` restricted to API backend + Cognito
  - Report-only mode initially → enforce after 1 week

- **CSRF Protection:**
  - Double-submit cookies (SameSite=Strict)
  - CSRF tokens in forms (generated server-side)

- **XSS Prevention:**
  - Sanitize all user input (DOMPurify)
  - Avoid dangerouslySetInnerHTML
  - Escape document content display

- **Rate Limiting:**
  - Client-side: debounce/throttle actions
  - Server-side: API Gateway rate limit (5000 req/min per user)
  - WAF rules in CloudFront

- **Dependency Security:**
  - Snyk scanning on every PR
  - Auto-remediate low/medium CVEs
  - Pin major versions in package.json

- **Secrets Management:**
  - No secrets in code (use AWS Secrets Manager)
  - Rotate OAuth tokens automatically
  - HTTPS everywhere (no fallback to HTTP)

**Deliverables:**

- `.env.example` with all required vars (no defaults)
- CSP headers in Terraform/Nginx config
- DOMPurify integration
- Snyk + Dependabot config
- Security audit checklist

#### 3.5 Performance Optimization

- **Code Splitting:**
  - Route-based: QueueDashboard, DocumentReview, Admin → separate chunks
  - Lazy load components (React.lazy + Suspense)

- **Data Caching:**
  - React Query cache: 5 min (queue), 10 min (audit trail), 1 min (notifications)
  - IndexedDB for offline queue (sync on reconnect)
  - Service Worker for offline support (read-only mode)

- **Image Optimization:**
  - WebP format with fallbacks
  - Lazy load images
  - Compress avatars

- **Bundle Size:**
  - Tree-shake unused code
  - Dynamic imports for heavy libraries (PDF generation)
  - Monitor with `bundle-analyzer`

**Metrics:**

- Lighthouse score: >90 on all pages
- FCP (First Contentful Paint): <1.5s
- LCP (Largest Contentful Paint): <2.5s
- CLS (Cumulative Layout Shift): <0.1
- TTI (Time to Interactive): <3.5s

**Deliverables:**

- Route-based code splitting
- Service Worker + offline queue
- Bundle analyzer report
- Lighthouse CI in GitHub Actions

---

## Phase 4: Production Readiness & Launch (Weeks 17-20)

### Goals

- FedRAMP compliance verification
- Load testing & optimization
- Documentation & runbooks
- User training & soft launch

### Checklist

#### 4.1 FedRAMP Compliance Audit

- [ ] Security Assessment Report (SAR) completed
- [ ] NIST 800-53 control mapping (>90% coverage)
- [ ] Vulnerability assessment (SAST + DAST)
- [ ] Penetration test (authorized, external)
- [ ] Supply chain risk assessment
- [ ] Data flow diagram reviewed
- [ ] Incident response plan documented
- [ ] Continuous monitoring configured (CloudWatch + GuardDuty)

**Expected Controls Mapped:**

- AC-2 (Account Management) → Cognito IAM
- AC-3 (Access Control) → RBAC enforcement
- AU-2/AU-12 (Audit Logging) → CloudTrail + DynamoDB
- SC-7 (Boundary Protection) → WAF + VPC
- SC-12 (Cryptography) → TLS 1.2+ + KMS
- SI-2 (Flaw Remediation) → Snyk scanning

#### 4.2 Load Testing

- **Scenario 1: Queue Load**
  - 100 concurrent reviewers accessing dashboard
  - 50 documents/sec ingestion
  - Target: <2s response time, <1% error rate

- **Scenario 2: Peak Approval Traffic**
  - 20 simultaneous approvals
  - Target: all complete within 5s

- **Tools:** Apache JMeter or Locust
- **Output:** Load test report + scaling recommendations

#### 4.3 Documentation

- **User Guide:** Screenshots + step-by-step for common workflows
  - How to log in with CAC
  - How to approve a document
  - How to view audit trail
  - FAQ (who to contact, how to report bugs)

- **Admin Guide:**
  - How to manage reviewers
  - How to view system health
  - Escalation procedures

- **Runbook:**
  - Deployment procedure
  - Rollback procedure
  - Common issues + troubleshooting
  - On-call escalation contacts

- **API Documentation:** OpenAPI/Swagger auto-generated

**Deliverables:**

- User guide (PDF + web pages)
- Admin guide (PDF + web pages)
- Runbook (markdown)
- Architecture diagram (C4 model)

#### 4.4 User Training

- **For Reviewers:**
  - 30-min video demo (narrated walkthrough)
  - Live training session (2 hours, Q&A)
  - Sandbox environment for practice

- **For Admins:**
  - Admin-specific training
  - System health monitoring overview

#### 4.5 Soft Launch

- **Week 1:** Invite 5-10 beta users (high-volume reviewers)
  - Monitor error rates, feedback
  - Track approval times, user satisfaction

- **Week 2:** Expand to full reviewer population
  - Monitor CloudWatch metrics
  - Gather feedback + iterate quickly

- **Week 3:** Production launch (notify all stakeholders)

---

## Technical Architecture

### Frontend Stack

```
┌─────────────────────────────────────────────┐
│  CloudFront (CDN) + WAF                      │
│  (GovCloud us-gov-west-1)                    │
└──────────────┬──────────────────────────────┘
               │
┌──────────────▼──────────────────────────────┐
│  S3 Bucket (Static SPA hosting)              │
│  - index.html + JS bundles                   │
│  - Object Lock (WORM, 7-year retention)      │
└──────────────┬──────────────────────────────┘
               │
┌──────────────▼──────────────────────────────┐
│  React 18 + TypeScript                       │
│  ├─ Vite (build tool)                        │
│  ├─ Redux Toolkit (state)                    │
│  ├─ React Query (data fetching)              │
│  ├─ TailwindCSS (styling)                    │
│  └─ Sentry (error tracking)                  │
└──────────────┬──────────────────────────────┘
               │ HTTPS (TLS 1.2+)
┌──────────────▼──────────────────────────────┐
│  API Gateway + Lambda (Backend)              │
│  ├─ Cognito Auth (CAC/PIV)                   │
│  ├─ Request validation                       │
│  └─ API endpoints (documented in OpenAPI)    │
└──────────────┬──────────────────────────────┘
               │
       ┌───────┴───────┐
       ▼               ▼
    DynamoDB        S3 Bucket
    (audit trail)   (documents)
```

### Directory Structure

```
frontend/
├── src/
│   ├── pages/
│   │   ├── LoginPage.tsx
│   │   ├── QueueDashboard.tsx
│   │   ├── DocumentReview.tsx
│   │   ├── AuditTrail.tsx
│   │   ├── Analytics.tsx
│   │   └── Admin/
│   ├── components/
│   │   ├── QueueTable/
│   │   ├── DocumentPreview/
│   │   ├── ApprovalWorkflow/
│   │   ├── NotificationCenter/
│   │   ├── Common/
│   │   └── Admin/
│   ├── hooks/
│   │   ├── useAuth.ts
│   │   ├── useAPI.ts
│   │   ├── useDocumentQueue.ts
│   │   ├── useNotifications.ts
│   │   └── useApproval.ts
│   ├── context/
│   │   ├── AuthContext.tsx
│   │   └── NotificationContext.tsx
│   ├── store/
│   │   ├── slices/
│   │   │   ├── authSlice.ts
│   │   │   ├── queueSlice.ts
│   │   │   └── notificationSlice.ts
│   │   └── index.ts
│   ├── api/
│   │   ├── client.ts
│   │   └── endpoints.ts
│   ├── types/
│   │   └── index.ts (API types)
│   ├── utils/
│   │   ├── auth.ts
│   │   ├── formatters.ts
│   │   └── validators.ts
│   ├── App.tsx
│   ├── main.tsx
│   └── index.css
├── public/
│   └── index.html
├── tests/
│   ├── unit/
│   ├── integration/
│   └── e2e/ (Playwright)
├── .storybook/
├── vite.config.ts
├── tsconfig.json
├── tailwind.config.js
├── .eslintrc.json
├── .prettierrc.json
├── package.json
└── README.md

terraform/
├── frontend/
│   ├── main.tf          # CloudFront + S3 + WAF
│   ├── variables.tf
│   ├── outputs.tf
│   └── cognito.tf       # Cognito user pool + IdP
```

### Security Checklist

- [ ] HTTPS/TLS 1.2+ enforced
- [ ] CSP headers configured (strict)
- [ ] CSRF token validation enabled
- [ ] XSS sanitization (DOMPurify)
- [ ] Session timeout (15 min inactivity)
- [ ] CAC/PIV certificate pinning
- [ ] Rate limiting enabled (API Gateway + WAF)
- [ ] Dependency scanning (Snyk) on every PR
- [ ] SAST scanning (SonarQube or similar)
- [ ] DAST scanning (OWASP ZAP)
- [ ] Pen test scheduled (Q3 2026)
- [ ] No secrets in code / environment vars in Secrets Manager
- [ ] Audit logging for all approval actions
- [ ] CloudWatch alarms configured
- [ ] GuardDuty enabled

---

## Success Metrics

### User Experience

- [ ] SLA compliance: >95% documents approved on time
- [ ] Average approval time: <30 min
- [ ] User satisfaction: >4.5/5 (after soft launch)
- [ ] Lighthouse score: >90 on all pages
- [ ] Load time: <2s for queue dashboard

### Operations

- [ ] API uptime: >99.95%
- [ ] Error rate: <0.1% of requests
- [ ] CloudWatch alerts: <1 false positive per week
- [ ] Deployment time: <15 min
- [ ] Rollback time: <5 min

### Compliance

- [ ] 0 unmitigated security findings (pen test)
- [ ] > 90% NIST 800-53 control coverage
- [ ] 100% audit trail completeness (zero lost events)
- [ ] 7-year document retention verified
- [ ] FedRAMP Moderate P-ATO achieved

---

## Risks & Mitigation

| Risk                                   | Impact | Probability | Mitigation                                                                 |
| -------------------------------------- | ------ | ----------- | -------------------------------------------------------------------------- |
| CAC/PIV auth delays deployment         | High   | Medium      | Start Cognito setup in Week 1; test with test certificates early           |
| FedRAMP SAR takes >6 weeks             | High   | Medium      | Engage 3PAO in Week 1; schedule assessment for Week 12                     |
| Performance issues under load          | Medium | Medium      | Load test in Week 14; use CDN + caching from day 1                         |
| User adoption resistance               | Medium | Low         | Extensive training + sandbox environment; collect feedback early           |
| Supply chain dependencies (React libs) | Medium | Low         | Snyk scanning + dependency pinning; evaluate security scores before adding |

---

## Dependencies

### Backend Requirements

- Stable API endpoints (OpenAPI spec available)
- CloudTrail + DynamoDB access for audit log queries
- SNS topic for notifications
- Cognito user pool in GovCloud
- S3 bucket access for document retrieval

### External Services

- AWS GovCloud region access (us-gov-west-1)
- GitHub Actions for CI/CD
- Sentry account (free tier ok for MVP)
- Figma (design) + Storybook (component library)

### Team Composition

- 1 Lead Frontend Engineer (React + TypeScript expert, FedRAMP familiar)
- 1 Junior Frontend Engineer (CSS + testing)
- 1 Backend Engineer (part-time, for API changes)
- 1 Security Engineer (audit + compliance, part-time)

---

## Budget Estimate

| Category                                   | Cost           | Notes                              |
| ------------------------------------------ | -------------- | ---------------------------------- |
| AWS GovCloud (CloudFront + S3 + WAF + KMS) | $250/month     | ~$3K/year                          |
| Sentry (error tracking)                    | $0 (free tier) | Or $29/mo for 10K events/mo        |
| Snyk (dependency scanning)                 | $0 (free tier) | Or $199/mo for CI integration      |
| 3PAO (FedRAMP assessment)                  | $20-40K        | One-time; see FEDRAMP-ALIGNMENT.md |
| Load testing tools                         | $0-5K          | JMeter (free) or Locust (free)     |
| Penetration testing                        | $15-25K        | Authorized security firm           |
| **Total Setup Cost**                       | **$35-70K**    | Infrastructure + security          |
| **Monthly Operating Cost**                 | **~$300**      | AWS + tools                        |
| **Team Cost (4 months, 3 people)**         | **~$120K**     | 2 FE eng + 1 backend eng           |
| **Total Project Cost**                     | **~$180-200K** | 16-20 weeks                        |

---

## Next Steps

1. **Week 0 (Now):**
   - Finalize tech stack choices (React 18, Vite, Redux Toolkit)
   - Start Cognito + CAC/PIV integration planning
   - Create detailed Figma designs for all pages
   - Set up GitHub org + repositories

2. **Week 1-2:**
   - Kick off project + team onboarding
   - Begin Phase 1 implementation (auth + API layer)
   - Draft OpenAPI spec for backend API

3. **Week 3-4:**
   - Phase 1 completion: deployable frontend with auth working
   - Begin Phase 2: queue dashboard development

4. **Ongoing:**
   - Weekly security reviews (dependency scanning + code review)
   - Bi-weekly demos to stakeholders
   - Monthly capacity planning + retrospectives

---

## Appendix: Figma Design System

- [ ] Component library (buttons, inputs, cards, modals)
- [ ] Color palette (primary, accent, status colors)
- [ ] Typography (font sizes, weights, line heights)
- [ ] Spacing system (4px grid)
- [ ] Responsive breakpoints (mobile, tablet, desktop)
- [ ] Dark mode variant (WCAG AA compliant)
- [ ] Accessibility guidelines (ARIA labels, focus states)

---

**Document Version:** 1.0 | **Last Updated:** 2026-05-06  
**Owner:** Donnivis Baker  
**Status:** Ready for Review
