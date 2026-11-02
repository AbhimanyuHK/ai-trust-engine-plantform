provider "aws" {
  region = var.aws_region
  allowed_account_ids = [local.expected_account_id]
  default_tags { tags = local.tags }
}
data "aws_caller_identity" "current" {}
data "aws_availability_zones" "available" { state = "available" }