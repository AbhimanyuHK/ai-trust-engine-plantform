resource "aws_sqs_queue" "ingestion_dlq" {
  name                      = format("%s-ingestion-dlq", local.prefix)
  message_retention_seconds = 1209600
  sqs_managed_sse_enabled   = true
  tags                      = local.tags
}
resource "aws_sqs_queue" "recommendation_dlq" {
  name                      = format("%s-recommendation-dlq", local.prefix)
  message_retention_seconds = 1209600
  sqs_managed_sse_enabled   = true
  tags                      = local.tags
}
resource "aws_sqs_queue" "ingestion" {
  name                       = format("%s-ingestion", local.prefix)
  visibility_timeout_seconds = 900
  receive_wait_time_seconds  = 20
  sqs_managed_sse_enabled    = true
  redrive_policy = jsonencode({ deadLetterTargetArn = aws_sqs_queue.ingestion_dlq.arn, maxReceiveCount = 5 })
  tags = local.tags
}
resource "aws_sqs_queue" "recommendation" {
  name                       = format("%s-recommendation", local.prefix)
  visibility_timeout_seconds = 900
  receive_wait_time_seconds  = 20
  sqs_managed_sse_enabled    = true
  redrive_policy = jsonencode({ deadLetterTargetArn = aws_sqs_queue.recommendation_dlq.arn, maxReceiveCount = 5 })
  tags = local.tags
}
