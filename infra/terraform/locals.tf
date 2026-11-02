locals {
  expected_account_id = lookup(var.environment_account_ids,var.environment,"000000000000")
  prefix = format("%s-%s",var.project_name,var.environment)
  tags = merge(var.tags_extra,{ Project=var.project_name, Environment=var.environment, ManagedBy="Terraform", PersistentStore="Snowflake" })
  azs = slice(data.aws_availability_zones.available.names,0,2)
}