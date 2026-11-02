# TRUST Engine Terraform deployment

Deploys DEV, QA, UAT and PROD into four dedicated AWS accounts. The AWS provider uses allowed_account_ids resolved from environment_account_ids; wrong-account credentials are rejected. This is an account guard, not authentication: use IAM Identity Center or an assumed deployment role.

## Components
- main.tf: component resources grouped as Network, S3 Storage, SQS Messaging, ECS Compute, WAF Security and CloudWatch Observability.
- variables.tf, locals.tf, providers.tf, outputs.tf and versions.tf are separate root configuration files.
- environments/*.tfvars hold per-environment sizing.
- Snowflake is the only database and persistent workflow store. No DynamoDB, RDS, Aurora, Redis or OpenSearch is provisioned.
- S3 stores original documents; SQS delivers work; ECS Fargate runs API and separate ingestion/recommendation services.

## Deploy
1. Copy account-map.example.tfvars to account-map.auto.tfvars and replace all four sample IDs with actual 12-digit account IDs. Keep the auto file uncommitted.
2. Set real ECR image URI, globally unique bucket name and existing Snowflake secret ARN in the selected environment tfvars.
3. Set actual API/worker commands if the repository entrypoints differ from the examples.
4. Initialize with an S3 remote backend and unique state key for each environment. S3 backend native lockfile is enabled; no DynamoDB lock table.

terraform -chdir=infra/terraform init -backend-config="bucket=YOUR_STATE_BUCKET" -backend-config="key=trust-engine/dev/terraform.tfstate" -backend-config="region=ap-south-1" -backend-config="use_lockfile=true"
terraform -chdir=infra/terraform validate
terraform -chdir=infra/terraform plan -var-file=account-map.auto.tfvars -var-file=environments/dev.tfvars
terraform -chdir=infra/terraform apply -var-file=account-map.auto.tfvars -var-file=environments/dev.tfvars

Repeat using qa, uat and prod environment files and separate state keys. Create the state bucket first with versioning, encryption and public access blocked. For PROD supply a valid ACM certificate ARN and verify HTTPS before exposing traffic.

The ECS services use the same container image with separate commands. Confirm the command entrypoints exist before deployment. Snowflake connection/network configuration and the Snowflake-backed LangGraph checkpoint implementation remain application/platform prerequisites. Load-test queue processing, workflow concurrency, Snowflake/Cortex throughput and API RPS before making any one-million-user capacity claim.

Run terraform fmt -recursive, terraform init, terraform validate and terraform plan in each target account. No resources have been deployed by committing these scripts.