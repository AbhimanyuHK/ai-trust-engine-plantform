variable "environment" {
  type = string
  validation {
    condition     = contains(["dev", "qa", "uat", "prod"], var.environment)
    error_message = "Use dev, qa, uat or prod."
  }
}
variable "environment_account_ids" {
  type        = map(string)
  description = "Dedicated AWS account ID for each environment."
  validation {
    condition     = alltrue([for e in ["dev", "qa", "uat", "prod"] : can(regex("^[0-9]{12}$", lookup(var.environment_account_ids, e, "")))])
    error_message = "Provide four valid 12-digit AWS account IDs."
  }
}
variable "aws_region" { type = string, default = "ap-south-1" }
variable "project_name" { type = string, default = "trust-engine" }
variable "container_image" { type = string, description = "Existing immutable ECR image URI." }
variable "snowflake_secret_arn" { type = string }
variable "contract_bucket_name" { type = string }
variable "acm_certificate_arn" { type = string, default = null }
variable "vpc_cidr" { type = string, default = "10.40.0.0/16" }
variable "single_nat_gateway" { type = bool, default = true }
variable "api_desired_count" { type = number, default = 1 }
variable "worker_desired_count" { type = number, default = 1 }
variable "api_min_capacity" { type = number, default = 1 }
variable "api_max_capacity" { type = number, default = 10 }
variable "worker_min_capacity" { type = number, default = 1 }
variable "worker_max_capacity" { type = number, default = 10 }
variable "api_cpu" { type = number, default = 1024 }
variable "api_memory" { type = number, default = 2048 }
variable "worker_cpu" { type = number, default = 2048 }
variable "worker_memory" { type = number, default = 4096 }
variable "api_command" {
  type    = list(string)
  default = ["uvicorn", "trust_engine.application.api:app", "--host", "0.0.0.0", "--port", "8000"]
}
variable "ingestion_command" {
  type    = list(string)
  default = ["python", "-m", "trust_engine.application.cli", "contract-ingestion-worker"]
}
variable "recommendation_command" {
  type    = list(string)
  default = ["python", "-m", "trust_engine.application.cli", "recommendation-worker"]
}
variable "enable_waf" { type = bool, default = true }
variable "log_retention_days" { type = number, default = 30 }
variable "tags_extra" { type = map(string), default = {} }
