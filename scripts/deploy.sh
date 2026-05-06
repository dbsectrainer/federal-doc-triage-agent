#!/bin/bash

# Federal Document Triage Agent - Deployment Script
# Deploys Lambda functions and supporting resources to AWS GovCloud

set -e

# Configuration
ENVIRONMENT=${1:-production}
REGION=${2:-us-gov-west-1}
PROJECT_NAME="federal-doc-triage-agent"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Functions
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Validate prerequisites
check_prerequisites() {
    log_info "Checking prerequisites..."

    # Check AWS CLI
    if ! command -v aws &> /dev/null; then
        log_error "AWS CLI is not installed"
        exit 1
    fi

    # Check Terraform
    if ! command -v terraform &> /dev/null; then
        log_warn "Terraform is not installed. Infrastructure deployment will be skipped."
        SKIP_TERRAFORM=1
    fi

    # Check Python
    if ! command -v python3 &> /dev/null; then
        log_error "Python 3 is not installed"
        exit 1
    fi

    log_info "All prerequisites satisfied"
}

# Deploy infrastructure with Terraform
deploy_infrastructure() {
    if [ "$SKIP_TERRAFORM" = "1" ]; then
        log_warn "Skipping Terraform deployment"
        return
    fi

    log_info "Deploying infrastructure with Terraform..."

    cd terraform

    # Initialize Terraform
    terraform init -upgrade

    # Validate configuration
    terraform validate

    # Plan deployment
    terraform plan -var-file="govcloud.tfvars" -out=tfplan

    # Apply configuration
    terraform apply tfplan

    cd ..

    log_info "Infrastructure deployment complete"
}

# Build Lambda packages
build_lambda_packages() {
    log_info "Building Lambda deployment packages..."

    # Create temp directory for build
    mkdir -p build

    # Copy source files
    cp -r agents build/
    cp -r workflows build/
    cp requirements.txt build/

    # Install dependencies in build directory
    pip install -r requirements.txt -t build/ --quiet

    # Create intake handler package
    cd build
    zip -r ../lambda_intake_handler.zip lambda/intake_handler.py agents/ workflows/ requirements.txt
    cd ..

    log_info "Lambda packages built successfully"
}

# Deploy Lambda functions
deploy_lambda_functions() {
    log_info "Deploying Lambda functions..."

    # Get Lambda function name from Terraform outputs
    LAMBDA_FUNCTION=$(aws lambda list-functions \
        --region "$REGION" \
        --query "Functions[?FunctionName=='${PROJECT_NAME}-intake'].FunctionName" \
        --output text)

    if [ -z "$LAMBDA_FUNCTION" ]; then
        log_warn "Lambda function not found. Ensure Terraform deployment completed successfully."
        return
    fi

    # Update function code
    aws lambda update-function-code \
        --function-name "$LAMBDA_FUNCTION" \
        --zip-file fileb://lambda_intake_handler.zip \
        --region "$REGION"

    # Wait for update to complete
    aws lambda wait function-updated \
        --function-name "$LAMBDA_FUNCTION" \
        --region "$REGION"

    log_info "Lambda functions deployed successfully"
}

# Run tests
run_tests() {
    log_info "Running test suite..."

    python3 -m pytest tests/ -v --cov=agents --cov=workflows

    log_info "Tests passed successfully"
}

# Validate deployment
validate_deployment() {
    log_info "Validating deployment..."

    # Check CloudTrail is enabled
    TRAIL_STATUS=$(aws cloudtrail describe-trails \
        --region "$REGION" \
        --query "trailList[?Name=='${PROJECT_NAME}-trail'].IsMultiRegionTrail" \
        --output text)

    if [ "$TRAIL_STATUS" = "True" ]; then
        log_info "CloudTrail enabled and logging"
    fi

    # Check S3 buckets exist
    INTAKE_BUCKET=$(aws s3api head-bucket \
        --bucket "${PROJECT_NAME}-intake-$(aws sts get-caller-identity --query Account --output text)" \
        --region "$REGION" 2>/dev/null && echo "exists" || echo "not-found")

    if [ "$INTAKE_BUCKET" = "exists" ]; then
        log_info "S3 intake bucket verified"
    fi

    # Check DynamoDB tables exist
    AUDIT_TABLE=$(aws dynamodb describe-table \
        --table-name "document-triage-audit" \
        --region "$REGION" \
        --query "Table.TableName" \
        --output text 2>/dev/null)

    if [ "$AUDIT_TABLE" = "document-triage-audit" ]; then
        log_info "DynamoDB audit table verified"
    fi

    log_info "Deployment validation complete"
}

# Main execution
main() {
    log_info "Federal Document Triage Agent - Deployment Script"
    log_info "Environment: $ENVIRONMENT"
    log_info "Region: $REGION"

    check_prerequisites
    run_tests
    deploy_infrastructure
    build_lambda_packages
    deploy_lambda_functions
    validate_deployment

    log_info "Deployment complete!"
    log_info "Next steps:"
    log_info "1. Upload sample documents to S3 intake bucket"
    log_info "2. Monitor CloudWatch logs for processing"
    log_info "3. Review audit trail in DynamoDB"
}

# Error handling
trap 'log_error "Deployment failed"; exit 1' ERR

# Execute main
main
