resource "aws_cloudwatch_metric_alarm" "api_cpu" {
  alarm_name          = format("%s-api-cpu-high", local.prefix)
  namespace           = "AWS/ECS"
  metric_name         = "CPUUtilization"
  statistic           = "Average"
  period              = 300
  evaluation_periods  = 2
  threshold           = 80
  comparison_operator = "GreaterThanThreshold"
  dimensions = {
    ClusterName = aws_ecs_cluster.main.name
    ServiceName = aws_ecs_service.api.name
  }
  tags = local.tags
}
resource "aws_cloudwatch_dashboard" "main" {
  dashboard_name = format("%s-operations", local.prefix)
  dashboard_body = jsonencode({
    widgets = [{
      type = "metric", x = 0, y = 0, width = 12, height = 6,
      properties = {
        title = "API CPU", region = var.aws_region,
        metrics = [["AWS/ECS", "CPUUtilization", "ClusterName", aws_ecs_cluster.main.name, "ServiceName", aws_ecs_service.api.name]]
      }
    }]
  })
}
resource "aws_cloudwatch_metric_alarm" "ingestion_queue_age" {
  alarm_name          = format("%s-ingestion-oldest-message", local.prefix)
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateAgeOfOldestMessage"
  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 2
  threshold           = 900
  comparison_operator = "GreaterThanThreshold"
  dimensions          = { QueueName = aws_sqs_queue.ingestion.name }
  tags                = local.tags
}
resource "aws_cloudwatch_metric_alarm" "recommendation_queue_age" {
  alarm_name          = format("%s-recommendation-oldest-message", local.prefix)
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateAgeOfOldestMessage"
  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 2
  threshold           = 900
  comparison_operator = "GreaterThanThreshold"
  dimensions          = { QueueName = aws_sqs_queue.recommendation.name }
  tags                = local.tags
}
