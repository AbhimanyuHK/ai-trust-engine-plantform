output "account_id" { value = data.aws_caller_identity.current.account_id }
output "environment" { value = var.environment }
output "vpc_id" { value = aws_vpc.main.id }
output "contract_bucket_name" { value = aws_s3_bucket.contracts.bucket }
output "ingestion_queue_url" { value = aws_sqs_queue.ingestion.url }
output "recommendation_queue_url" { value = aws_sqs_queue.recommendation.url }
output "ecr_repository_url" { value = aws_ecr_repository.app.repository_url }
output "api_url" { value = var.acm_certificate_arn == null ? format("http://%s",aws_lb.api.dns_name) : format("https://%s",aws_lb.api.dns_name) }
output "ecs_cluster_name" { value = aws_ecs_cluster.main.name }
output "waf_arn" { value = var.enable_waf ? aws_wafv2_web_acl.alb[0].arn : null }