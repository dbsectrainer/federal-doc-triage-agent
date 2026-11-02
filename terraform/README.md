# Terraform Infrastructure Baseline

> **Verified status (2026-11-01):** `terraform fmt -check` and
> `terraform validate` pass. **`terraform apply` was not run** because the audit
> environment had no authorization to make billable AWS calls or change cloud
> resources. This configuration is a
> data/security baseline, not a complete application deployment.

## What This Configuration Provisions

```text
AWS GovCloud (us-gov-west-1 default)
├── VPC 10.0.0.0/16
│   ├── 2 public / 2 private / 2 database subnets
│   ├── Internet + NAT gateways, route tables
│   └── VPC Flow Logs to CloudWatch (KMS-encrypted)
├── S3
│   ├── Intake bucket: KMS, versioned, public access blocked, access logging
│   ├── Archive bucket: KMS, versioned, Object Lock (GOVERNANCE, 2555 days),
│   │   public access blocked, access logging, log-delivery bucket policy
│   └── CloudTrail bucket: KMS, versioned, public access blocked, policy
├── DynamoDB
│   ├── document-triage-audit (document_id + timestamp, CMK, PITR, TTL field)
│   └── document-triage-state (document_id, CMK, PITR)
├── KMS keys for S3 and DynamoDB (rotation enabled)
├── CloudTrail (multi-region, log-file validation, CloudWatch Logs,
│   partition-aware S3/Lambda data resources)
└── Optional GuardDuty detector and Security Hub account
```

## What This Configuration Does **Not** Provision

- Lambda function or execution role
- API Gateway
- S3 event notification to Lambda
- SNS/SES/Step Functions approval workflow
- Application security groups or VPC endpoints
- Reviewer directory, authentication, or authorization
- Document archive uploads / Object Lock object writes
- CloudWatch alarms for application failures

`scripts/deploy.sh` builds a Lambda zip but stops with an explicit error because
the function does not exist. Do not describe the AWS path as deployed.

## Prerequisites

- Terraform >= 1.0 (verified with Terraform CLI on macOS; AWS provider 5.100.0)
- AWS CLI and credentials for a non-production account (not used in this audit)
- A configured GovCloud profile for `terraform apply`

## Validate (verified)

```bash
cd terraform
terraform init -backend=false -input=false
terraform validate
```

Expected:

```text
Success! The configuration is valid.
```

## Plan/Apply (not verified)

```bash
cp govcloud.tfvars.example terraform.tfvars
# Edit terraform.tfvars. Never commit terraform.tfvars.
terraform init
terraform plan -out=tfplan
terraform apply tfplan
```

Before applying, review at least:

- Region and availability zones (`us-gov-west-1a/b`).
- KMS key policies for CloudTrail and CloudWatch Logs use.
- S3 bucket names and account ID.
- DynamoDB table names must match `AUDIT_DYNAMODB_TABLE` and
  `STATE_DYNAMODB_TABLE` in the application environment.
- CloudTrail data-resource ARNs: the config uses `data.aws_partition.current`,
  producing `arn:aws-us-gov` in GovCloud.

Known unverified apply risks:

1. CloudTrail's CMK may need an explicit key-policy statement for
   `cloudtrail.amazonaws.com` in some accounts.
2. The CloudTrail CloudWatch Logs role may need `kms:GenerateDataKey*` and
   `kms:Decrypt` on the log-group key.
3. VPC NAT gateways and flow logs incur cost and were not created.
4. `enable_default_standards = false` means Security Hub is enabled but no
   standards subscription is created.

## Destroy

`terraform destroy` is destructive and not authorized in this audit. If used in
a disposable account, review the plan first; Object Lock and versioned buckets
may prevent immediate deletion.

## Variables

See `variables.tf` and `govcloud.tfvars.example`. Several variables
(`lambda_memory_size`, `lambda_timeout`, `bedrock_model_id`,
`document_retention_days`, `max_document_size_mb`, `use_comprehend`,
`enable_logging`, `sla_*`) are reserved for the unimplemented Lambda/application
deployment. Setting them currently has no infrastructure effect.

## Validation Evidence

- `docs/evidence/build-results/terraform-fmt.txt`
- `docs/evidence/build-results/terraform-validate.txt`

## Support

Open an issue at
https://github.com/dbsectrainer/federal-doc-triage-agent/issues.
