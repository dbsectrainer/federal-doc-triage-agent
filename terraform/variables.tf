variable "aws_region" {
  description = "AWS region for deployment (GovCloud: us-gov-west-1 or us-gov-east-1)"
  type        = string
  default     = "us-gov-west-1"
}

variable "environment" {
  description = "Environment name (dev, staging, production)"
  type        = string
  default     = "production"

  validation {
    condition     = contains(["dev", "staging", "production"], var.environment)
    error_message = "Environment must be dev, staging, or production."
  }
}

variable "project_name" {
  description = "Project name for resource naming"
  type        = string
  default     = "federal-doc-triage-agent"
}

variable "vpc_cidr" {
  description = "CIDR block for VPC"
  type        = string
  default     = "10.0.0.0/16"
}

variable "availability_zones" {
  description = "Availability zones for multi-AZ deployment"
  type        = list(string)
  default     = ["us-gov-west-1a", "us-gov-west-1b"]
}

variable "public_subnet_cidrs" {
  description = "CIDR blocks for public subnets"
  type        = list(string)
  default     = ["10.0.1.0/24", "10.0.2.0/24"]
}

variable "private_subnet_cidrs" {
  description = "CIDR blocks for private subnets"
  type        = list(string)
  default     = ["10.0.10.0/24", "10.0.11.0/24"]
}

variable "database_subnet_cidrs" {
  description = "CIDR blocks for database subnets"
  type        = list(string)
  default     = ["10.0.20.0/24", "10.0.21.0/24"]
}

variable "audit_table_name" {
  description = "DynamoDB table name for audit trail"
  type        = string
  default     = "document-triage-audit"
}

variable "state_table_name" {
  description = "DynamoDB table name for workflow state"
  type        = string
  default     = "document-triage-state"
}

variable "lambda_memory_size" {
  description = "Lambda function memory in MB"
  type        = number
  default     = 512
}

variable "lambda_timeout" {
  description = "Lambda function timeout in seconds"
  type        = number
  default     = 300
}

variable "bedrock_model_id" {
  description = "AWS Bedrock model ID for classification"
  type        = string
  default     = "anthropic.claude-3-sonnet-20240229-v1:0"
}

variable "document_retention_days" {
  description = "Number of days to retain documents in archive"
  type        = number
  default     = 2555  # 7 years for NARA compliance
}

variable "enable_guardduty" {
  description = "Enable AWS GuardDuty for threat detection"
  type        = bool
  default     = true
}

variable "enable_security_hub" {
  description = "Enable AWS Security Hub for compliance dashboard"
  type        = bool
  default     = true
}

variable "tags" {
  description = "Common tags for all resources"
  type        = map(string)
  default = {
    Project      = "federal-doc-triage-agent"
    Environment  = "production"
    CostCenter   = "compliance"
    DataClass    = "fouo"
    Compliance   = "fedramp-moderate"
    BackupPolicy = "nara-7year"
  }
}

variable "enable_logging" {
  description = "Enable detailed logging for troubleshooting"
  type        = bool
  default     = true
}

variable "log_retention_days" {
  description = "CloudWatch log retention period in days"
  type        = number
  default     = 365
}

variable "max_document_size_mb" {
  description = "Maximum document size in MB"
  type        = number
  default     = 100
}

variable "use_comprehend" {
  description = "Use AWS Comprehend for PII detection (true) or regex (false)"
  type        = bool
  default     = true
}

variable "sla_routine_days" {
  description = "SLA for routine documents (days)"
  type        = number
  default     = 10
}

variable "sla_priority_days" {
  description = "SLA for priority documents (days)"
  type        = number
  default     = 5
}

variable "sla_immediate_hours" {
  description = "SLA for immediate documents (hours)"
  type        = number
  default     = 24
}

variable "sla_emergency_hours" {
  description = "SLA for emergency documents (hours)"
  type        = number
  default     = 4
}
