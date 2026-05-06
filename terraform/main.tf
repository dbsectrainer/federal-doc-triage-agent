terraform {
  required_version = ">= 1.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # Configure backend for state management
  # backend "s3" {
  #   bucket         = "terraform-state-bucket"
  #   key            = "federal-doc-triage-agent/terraform.tfstate"
  #   region         = "us-gov-west-1"
  #   encrypt        = true
  #   dynamodb_table = "terraform-locks"
  # }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Environment = var.environment
      Project     = "federal-doc-triage-agent"
      ManagedBy   = "Terraform"
    }
  }
}

# VPC Configuration
module "vpc" {
  source = "./modules/vpc"

  project_name          = var.project_name
  vpc_cidr             = var.vpc_cidr
  availability_zones   = var.availability_zones
  public_subnet_cidrs  = var.public_subnet_cidrs
  private_subnet_cidrs = var.private_subnet_cidrs
  database_subnet_cidrs = var.database_subnet_cidrs

  tags = var.tags
}

# S3 Intake Bucket
resource "aws_s3_bucket" "intake_bucket" {
  bucket = "${var.project_name}-intake-${data.aws_caller_identity.current.account_id}"

  tags = merge(var.tags, {
    Name = "Intake Documents Bucket"
  })
}

# S3 Bucket Encryption
resource "aws_s3_bucket_server_side_encryption_configuration" "intake_bucket" {
  bucket = aws_s3_bucket.intake_bucket.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.s3.arn
    }
    bucket_key_enabled = true
  }
}

# Versioning for Intake Bucket
resource "aws_s3_bucket_versioning" "intake_bucket" {
  bucket = aws_s3_bucket.intake_bucket.id

  versioning_configuration {
    status = "Enabled"
  }
}

# Block Public Access
resource "aws_s3_bucket_public_access_block" "intake_bucket" {
  bucket = aws_s3_bucket.intake_bucket.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Archive Bucket with Object Lock
resource "aws_s3_bucket" "archive_bucket" {
  bucket              = "${var.project_name}-archive-${data.aws_caller_identity.current.account_id}"
  object_lock_enabled = true

  tags = merge(var.tags, {
    Name = "Document Archive with WORM"
  })
}

resource "aws_s3_bucket_versioning" "archive_bucket" {
  bucket = aws_s3_bucket.archive_bucket.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "archive_bucket" {
  bucket = aws_s3_bucket.archive_bucket.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.s3.arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "archive_bucket" {
  bucket = aws_s3_bucket.archive_bucket.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_object_lock_configuration" "archive_bucket" {
  bucket = aws_s3_bucket.archive_bucket.id

  rule {
    default_retention {
      mode = "GOVERNANCE"
      days = 2555  # 7 years per NARA
    }
  }

  depends_on = [aws_s3_bucket_versioning.archive_bucket]
}

# S3 Bucket Logging Configuration
resource "aws_s3_bucket_logging" "intake" {
  bucket = aws_s3_bucket.intake_bucket.id

  target_bucket = aws_s3_bucket.archive_bucket.id
  target_prefix = "intake-logs/"

  depends_on = [aws_s3_bucket_public_access_block.archive_bucket]
}

resource "aws_s3_bucket_logging" "archive" {
  bucket = aws_s3_bucket.archive_bucket.id

  target_bucket = aws_s3_bucket.archive_bucket.id
  target_prefix = "archive-logs/"

  depends_on = [aws_s3_bucket_public_access_block.archive_bucket]
}

resource "aws_s3_bucket_logging" "cloudtrail" {
  bucket = aws_s3_bucket.cloudtrail_bucket.id

  target_bucket = aws_s3_bucket.archive_bucket.id
  target_prefix = "cloudtrail-logs/"

  depends_on = [aws_s3_bucket_public_access_block.archive_bucket]
}

# KMS Key for Encryption
resource "aws_kms_key" "s3" {
  description             = "KMS key for S3 encryption in ${var.aws_region}"
  deletion_window_in_days = 30
  enable_key_rotation     = true

  tags = merge(var.tags, {
    Name = "S3 Encryption Key"
  })
}

resource "aws_kms_alias" "s3" {
  name          = "alias/${var.project_name}-s3-key"
  target_key_id = aws_kms_key.s3.key_id
}

# DynamoDB Table for Audit Trail
resource "aws_dynamodb_table" "audit_trail" {
  name             = var.audit_table_name
  billing_mode     = "PAY_PER_REQUEST"
  hash_key         = "document_id"
  range_key        = "timestamp"
  stream_enabled   = true
  stream_view_type = "NEW_AND_OLD_IMAGES"

  attribute {
    name = "document_id"
    type = "S"
  }

  attribute {
    name = "timestamp"
    type = "S"
  }

  server_side_encryption {
    enabled     = true
    kms_key_arn = aws_kms_key.dynamodb.arn
  }

  point_in_time_recovery {
    enabled = true
  }

  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }

  tags = merge(var.tags, {
    Name = "Audit Trail"
  })
}

# DynamoDB Table for Workflow State
resource "aws_dynamodb_table" "workflow_state" {
  name           = var.state_table_name
  billing_mode   = "PAY_PER_REQUEST"
  hash_key       = "document_id"
  stream_enabled = true

  attribute {
    name = "document_id"
    type = "S"
  }

  server_side_encryption {
    enabled     = true
    kms_key_arn = aws_kms_key.dynamodb.arn
  }

  point_in_time_recovery {
    enabled = true
  }

  tags = merge(var.tags, {
    Name = "Workflow State"
  })
}

# KMS Key for DynamoDB
resource "aws_kms_key" "dynamodb" {
  description             = "KMS key for DynamoDB encryption"
  deletion_window_in_days = 30
  enable_key_rotation     = true

  tags = merge(var.tags, {
    Name = "DynamoDB Encryption Key"
  })
}

# CloudTrail for API Logging
resource "aws_cloudtrail" "main" {
  name                          = "${var.project_name}-trail"
  s3_bucket_name                = aws_s3_bucket.cloudtrail_bucket.id
  include_global_service_events = true
  is_multi_region_trail         = true
  enable_log_file_validation    = true
  kms_key_id                    = aws_kms_key.s3.arn
  cloud_watch_logs_group_arn    = "${aws_cloudwatch_log_group.cloudtrail_logs.arn}:*"
  cloud_watch_logs_role_arn     = aws_iam_role.cloudtrail_cloudwatch.arn
  depends_on                    = [aws_s3_bucket_policy.cloudtrail]

  event_selector {
    read_write_type           = "All"
    include_management_events = true

    data_resource {
      type   = "AWS::S3::Object"
      values = ["arn:aws:s3:::*"]
    }

    data_resource {
      type   = "AWS::Lambda::Function"
      values = ["arn:aws:lambda:*:*:function/*"]
    }
  }

  tags = merge(var.tags, {
    Name = "CloudTrail Logging"
  })
}

# CloudWatch Log Group for CloudTrail
resource "aws_cloudwatch_log_group" "cloudtrail_logs" {
  name              = "/aws/cloudtrail/federal-doc-triage"
  retention_in_days = var.log_retention_days
  kms_key_id        = aws_kms_key.s3.arn

  tags = merge(var.tags, { Name = "cloudtrail-logs" })
}

# IAM Role for CloudTrail to CloudWatch Logs
resource "aws_iam_role" "cloudtrail_cloudwatch" {
  name = "${var.project_name}-cloudtrail-cloudwatch"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "cloudtrail.amazonaws.com"
      }
    }]
  })

  tags = merge(var.tags, { Name = "cloudtrail-cloudwatch-role" })
}

# IAM Policy for CloudTrail to write to CloudWatch Logs
resource "aws_iam_role_policy" "cloudtrail_cloudwatch" {
  name = "${var.project_name}-cloudtrail-cloudwatch-policy"
  role = aws_iam_role.cloudtrail_cloudwatch.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = [
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Effect   = "Allow"
        Resource = [
          aws_cloudwatch_log_group.cloudtrail_logs.arn,
          "${aws_cloudwatch_log_group.cloudtrail_logs.arn}:*"
        ]
      }
    ]
  })
}

# CloudTrail S3 Bucket
resource "aws_s3_bucket" "cloudtrail_bucket" {
  bucket = "${var.project_name}-cloudtrail-${data.aws_caller_identity.current.account_id}"

  tags = merge(var.tags, {
    Name = "CloudTrail Logs"
  })
}

resource "aws_s3_bucket_server_side_encryption_configuration" "cloudtrail_bucket" {
  bucket = aws_s3_bucket.cloudtrail_bucket.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.s3.arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "cloudtrail_bucket" {
  bucket = aws_s3_bucket.cloudtrail_bucket.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Versioning for CloudTrail Bucket
resource "aws_s3_bucket_versioning" "cloudtrail_bucket" {
  bucket = aws_s3_bucket.cloudtrail_bucket.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_policy" "cloudtrail" {
  bucket = aws_s3_bucket.cloudtrail_bucket.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AWSCloudTrailAclCheck"
        Effect = "Allow"
        Principal = {
          Service = "cloudtrail.amazonaws.com"
        }
        Action   = "s3:GetBucketAcl"
        Resource = aws_s3_bucket.cloudtrail_bucket.arn
      },
      {
        Sid    = "AWSCloudTrailWrite"
        Effect = "Allow"
        Principal = {
          Service = "cloudtrail.amazonaws.com"
        }
        Action   = "s3:PutObject"
        Resource = "${aws_s3_bucket.cloudtrail_bucket.arn}/*"
        Condition = {
          StringEquals = {
            "s3:x-amz-acl" = "bucket-owner-full-control"
          }
        }
      }
    ]
  })
}

# Data source for current AWS account
data "aws_caller_identity" "current" {}

# Outputs
output "intake_bucket_name" {
  value       = aws_s3_bucket.intake_bucket.id
  description = "S3 bucket for document intake"
}

output "archive_bucket_name" {
  value       = aws_s3_bucket.archive_bucket.id
  description = "S3 bucket for document archive with WORM"
}

output "audit_table_name" {
  value       = aws_dynamodb_table.audit_trail.id
  description = "DynamoDB table for audit trail"
}

output "state_table_name" {
  value       = aws_dynamodb_table.workflow_state.id
  description = "DynamoDB table for workflow state"
}

output "vpc_id" {
  value       = module.vpc.vpc_id
  description = "VPC ID"
}

output "kms_key_id" {
  value       = aws_kms_key.s3.id
  description = "KMS key ID for encryption"
}
