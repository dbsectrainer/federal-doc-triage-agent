# Terraform Infrastructure for Federal Document Triage Agent

This directory contains Terraform Infrastructure-as-Code (IaC) for deploying the Federal Document Triage Agent to AWS GovCloud with FedRAMP Moderate compliance.

## Architecture

```
AWS GovCloud (us-gov-west-1 or us-gov-east-1)
├── VPC (10.0.0.0/16)
│   ├── Public Subnets (ALB, NAT Gateway)
│   ├── Private Subnets (Lambda, API Gateway)
│   └── Database Subnets (RDS PostgreSQL - future)
├── Storage
│   ├── S3 Intake Bucket (encrypted with KMS)
│   ├── S3 Archive Bucket (encrypted + Object Lock, WORM)
│   └── S3 CloudTrail Bucket (audit logging)
├── Encryption
│   ├── KMS Key for S3 encryption
│   ├── KMS Key for DynamoDB encryption
│   └── TLS 1.2+ for all transit
├── Databases
│   ├── DynamoDB Audit Trail (7-year retention)
│   └── DynamoDB Workflow State
├── Logging & Monitoring
│   ├── CloudTrail (all API calls, immutable)
│   ├── CloudWatch Logs (application events)
│   └── Security Hub (compliance dashboard)
└── Security Services
    ├── GuardDuty (threat detection)
    ├── IAM Roles (least privilege)
    └── Security Groups (network isolation)
```

## Prerequisites

### Required Tools

```bash
# AWS CLI v2
aws --version

# Terraform >= 1.0
terraform --version

# AWS Credentials configured for GovCloud
aws configure --profile govcloud
```

### AWS Permissions

Your IAM user or role must have permissions for:

- VPC creation (EC2, route tables, security groups)
- S3 bucket creation and policies
- DynamoDB table creation
- KMS key creation and management
- CloudTrail setup
- CloudWatch Logs
- IAM role and policy creation

## Deployment Steps

### 1. Clone Repository

```bash
git clone https://github.com/dbsectrainer/federal-doc-triage-agent.git
cd federal-doc-triage-agent/terraform
```

### 2. Configure Variables

Copy the example Terraform variables file:

```bash
cp govcloud.tfvars.example terraform.tfvars
```

Edit `terraform.tfvars` with your specific configuration:

```hcl
aws_region = "us-gov-west-1"  # GovCloud region
environment = "production"
vpc_cidr = "10.0.0.0/16"
# ... other variables
```

### 3. Initialize Terraform

```bash
terraform init
```

This downloads the required AWS provider and sets up the Terraform backend.

### 4. Validate Configuration

```bash
terraform validate
```

Ensures the Terraform configuration is syntactically valid.

### 5. Plan Deployment

```bash
terraform plan -var-file="terraform.tfvars" -out=tfplan
```

Review the execution plan to see what resources will be created.

### 6. Apply Configuration

```bash
terraform apply tfplan
```

This deploys all infrastructure to AWS GovCloud.

### 7. Capture Outputs

After deployment completes, note the output values:

```bash
terraform output -json > deployment_outputs.json
```

## Post-Deployment Verification

### Verify CloudTrail Logging

```bash
# List CloudTrail trails
aws cloudtrail describe-trails --region us-gov-west-1

# Check CloudTrail is logging
aws cloudtrail get-trail-status --name federal-doc-triage-agent-trail --region us-gov-west-1
```

### Verify S3 Encryption

```bash
# Check intake bucket encryption
aws s3api get-bucket-encryption --bucket federal-doc-triage-agent-intake-ACCOUNT_ID --region us-gov-west-1

# Check archive bucket has Object Lock
aws s3api get-object-lock-configuration --bucket federal-doc-triage-agent-archive-ACCOUNT_ID --region us-gov-west-1
```

### Verify DynamoDB Configuration

```bash
# Check audit table
aws dynamodb describe-table --table-name document-triage-audit --region us-gov-west-1

# Check encryption
aws dynamodb describe-table --table-name document-triage-audit --region us-gov-west-1 | jq '.Table.SSEDescription'
```

## Monitoring & Logging

### CloudWatch Logs

View Lambda execution logs:

```bash
aws logs tail /aws/lambda/federal-doc-triage-agent-intake --follow --region us-gov-west-1
```

### CloudTrail Queries

Query CloudTrail logs for specific events:

```bash
# Find all Lambda invocations
aws cloudtrail lookup-events \
    --lookup-attributes AttributeKey=EventName,AttributeValue=InvokeFunction \
    --region us-gov-west-1 \
    --max-results 10
```

## Cost Optimization

### DynamoDB Billing

Currently using **Pay-Per-Request** billing. For high-volume deployments, consider:

```hcl
# Change to provisioned capacity
billing_mode = "PROVISIONED"
read_capacity_units  = 100
write_capacity_units = 100
```

### S3 Storage Classes

Archive old documents to Glacier after 90 days:

```hcl
lifecycle_rule {
  transitions = {
    days          = 90
    storage_class = "GLACIER"
  }
}
```

### VPC Endpoints

Replace NAT Gateway with VPC endpoints to reduce data transfer costs:

```bash
# Interface endpoint for S3
resource "aws_vpc_endpoint" "s3" {
  vpc_id            = module.vpc.vpc_id
  service_name      = "com.amazonaws.gov-west-1.s3"
  vpc_endpoint_type = "Gateway"
}
```

## Scaling

### Multi-Region Deployment

For disaster recovery, deploy to multiple regions:

```bash
# Deploy to us-gov-east-1
terraform apply -var="aws_region=us-gov-east-1" -var-file="terraform.tfvars"
```

### DynamoDB Global Tables

Enable cross-region replication for audit trail:

```hcl
stream_specification {
  stream_view_type = "NEW_AND_OLD_IMAGES"
}

replica {
  region_name = "us-gov-east-1"
}
```

## Troubleshooting

### Terraform State Lock

If deployment fails and state is locked:

```bash
terraform force-unlock <LOCK_ID>
```

### Roll Back Deployment

To destroy all infrastructure:

```bash
terraform destroy -var-file="terraform.tfvars"
```

**Warning:** This will delete all S3 buckets, DynamoDB tables, and VPC resources. Ensure backups are in place first.

### VPC Endpoint Issues

If Lambda cannot reach S3:

1. Verify security group allows HTTPS (443)
2. Check VPC endpoint policy allows S3 access
3. Verify S3 bucket policy allows access from the VPC endpoint

## Compliance Verification

### NIST 800-53 Control Verification

Run the compliance scanner:

```bash
cd ../
./scripts/compliance_check.sh --framework nist_800_53_moderate --region us-gov-west-1
```

### FedRAMP Baseline Checklist

- [x] VPC with private subnets
- [x] Encryption at rest (KMS) for all storage
- [x] Encryption in transit (TLS 1.2+)
- [x] CloudTrail logging with immutable storage
- [x] IAM least-privilege roles
- [x] Security groups restrict access
- [x] KMS key rotation enabled
- [x] CloudWatch monitoring enabled
- [ ] MFA for console access (manual)
- [ ] Security training (manual)

## Support

For issues or questions:

1. Check Terraform logs: `terraform apply -var-file="terraform.tfvars" -json | jq`
2. Review CloudTrail for API errors
3. Check CloudWatch Logs for Lambda errors
4. Open an issue: https://github.com/dbsectrainer/federal-doc-triage-agent/issues

---

**Last Updated:** 2026-05-06  
**Terraform Version:** >= 1.0  
**AWS Provider:** >= 5.0  
**FedRAMP Alignment:** Moderate Baseline
