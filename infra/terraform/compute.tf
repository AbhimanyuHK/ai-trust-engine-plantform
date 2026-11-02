resource "aws_ecr_repository" "app" {
  name                 = local.prefix
  image_tag_mutability = "IMMUTABLE"
  image_scanning_configuration {
    scan_on_push = true
  }
  tags = local.tags
}
resource "aws_ecs_cluster" "main" {
  name = format("%s-cluster", local.prefix)
  setting {
    name  = "containerInsights"
    value = "enabled"
  }
  tags = local.tags
}
resource "aws_cloudwatch_log_group" "api" {
  name              = format("/ecs/%s/api", local.prefix)
  retention_in_days = var.log_retention_days
  tags              = local.tags
}
resource "aws_cloudwatch_log_group" "ingestion" {
  name              = format("/ecs/%s/ingestion", local.prefix)
  retention_in_days = var.log_retention_days
  tags              = local.tags
}
resource "aws_cloudwatch_log_group" "recommendation" {
  name              = format("/ecs/%s/recommendation", local.prefix)
  retention_in_days = var.log_retention_days
  tags              = local.tags
}
resource "aws_iam_role" "execution" {
  name = format("%s-execution", local.prefix)
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{ Effect = "Allow", Principal = { Service = "ecs-tasks.amazonaws.com" }, Action = "sts:AssumeRole" }]
  })
  tags = local.tags
}
resource "aws_iam_role_policy_attachment" "execution" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}
resource "aws_iam_role_policy" "execution_secrets" {
  name = "read-snowflake-secret-for-ecs-injection"
  role = aws_iam_role.execution.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = ["secretsmanager:GetSecretValue"]
      Resource = [var.snowflake_secret_arn]
    }]
  })
}
resource "aws_iam_role" "task" {
  name = format("%s-task", local.prefix)
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{ Effect = "Allow", Principal = { Service = "ecs-tasks.amazonaws.com" }, Action = "sts:AssumeRole" }]
  })
  tags = local.tags
}
resource "aws_iam_role_policy" "task" {
  role = aws_iam_role.task.id
  name = "trust-application-access"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["s3:GetObject", "s3:PutObject"], Resource = [format("%s/*", aws_s3_bucket.contracts.arn)] },
      { Effect = "Allow", Action = ["s3:ListBucket"], Resource = [aws_s3_bucket.contracts.arn] },
      { Effect = "Allow", Action = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:ChangeMessageVisibility", "sqs:GetQueueAttributes", "sqs:SendMessage"], Resource = [aws_sqs_queue.ingestion.arn, aws_sqs_queue.recommendation.arn] },
      { Effect = "Allow", Action = ["secretsmanager:GetSecretValue"], Resource = [var.snowflake_secret_arn] },
      { Effect = "Allow", Action = ["kms:Decrypt", "kms:Encrypt", "kms:GenerateDataKey"], Resource = [aws_kms_key.documents.arn] },
      { Effect = "Allow", Action = ["textract:DetectDocumentText", "textract:AnalyzeDocument", "textract:StartDocumentTextDetection", "textract:GetDocumentTextDetection", "textract:StartDocumentAnalysis", "textract:GetDocumentAnalysis"], Resource = ["*"] }
    ]
  })
}
resource "aws_lb" "api" {
  name                       = substr(format("%s-alb", local.prefix), 0, 32)
  load_balancer_type         = "application"
  security_groups            = [aws_security_group.alb.id]
  subnets                    = aws_subnet.public[*].id
  enable_deletion_protection = var.environment == "prod"
  tags                       = local.tags
}
resource "aws_lb_target_group" "api" {
  name        = substr(format("%s-api", local.prefix), 0, 32)
  port        = 8000
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = aws_vpc.main.id
  health_check {
    path    = "/health"
    matcher = "200-399"
  }
  tags = local.tags
}
resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.api.arn
  port              = 80
  protocol          = "HTTP"
  default_action {
    type             = var.acm_certificate_arn == null ? "forward" : "redirect"
    target_group_arn = var.acm_certificate_arn == null ? aws_lb_target_group.api.arn : null
    dynamic "redirect" {
      for_each = var.acm_certificate_arn == null ? [] : [1]
      content {
        port        = "443"
        protocol    = "HTTPS"
        status_code = "HTTP_301"
      }
    }
  }
}
resource "aws_lb_listener" "https" {
  count             = var.acm_certificate_arn == null ? 0 : 1
  load_balancer_arn = aws_lb.api.arn
  port              = 443
  protocol          = "HTTPS"
  certificate_arn   = var.acm_certificate_arn
  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }
}
locals {
  common_environment = [
    { name = "TRUST_ENVIRONMENT", value = var.environment },
    { name = "INGESTION_QUEUE_URL", value = aws_sqs_queue.ingestion.url },
    { name = "RECOMMENDATION_QUEUE_URL", value = aws_sqs_queue.recommendation.url }
  ]
}
resource "aws_ecs_task_definition" "api" {
  family                   = format("%s-api", local.prefix)
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = tostring(var.api_cpu)
  memory                   = tostring(var.api_memory)
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn
  container_definitions = jsonencode([{
    name = "api", image = var.container_image, essential = true, command = var.api_command
    portMappings = [{ containerPort = 8000 }]
    environment = local.common_environment
    secrets = [{ name = "SNOWFLAKE_SECRET", valueFrom = var.snowflake_secret_arn }]
    logConfiguration = { logDriver = "awslogs", options = { awslogs-group = aws_cloudwatch_log_group.api.name, awslogs-region = var.aws_region, awslogs-stream-prefix = "api" } }
  }])
  tags = local.tags
}
resource "aws_ecs_task_definition" "ingestion" {
  family                   = format("%s-ingestion", local.prefix)
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = tostring(var.worker_cpu)
  memory                   = tostring(var.worker_memory)
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn
  container_definitions = jsonencode([{
    name = "ingestion", image = var.container_image, essential = true, command = var.ingestion_command
    environment = local.common_environment
    secrets = [{ name = "SNOWFLAKE_SECRET", valueFrom = var.snowflake_secret_arn }]
    logConfiguration = { logDriver = "awslogs", options = { awslogs-group = aws_cloudwatch_log_group.ingestion.name, awslogs-region = var.aws_region, awslogs-stream-prefix = "ingestion" } }
  }])
  tags = local.tags
}
resource "aws_ecs_task_definition" "recommendation" {
  family                   = format("%s-recommendation", local.prefix)
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = tostring(var.worker_cpu)
  memory                   = tostring(var.worker_memory)
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn
  container_definitions = jsonencode([{
    name = "recommendation", image = var.container_image, essential = true, command = var.recommendation_command
    environment = local.common_environment
    secrets = [{ name = "SNOWFLAKE_SECRET", valueFrom = var.snowflake_secret_arn }]
    logConfiguration = { logDriver = "awslogs", options = { awslogs-group = aws_cloudwatch_log_group.recommendation.name, awslogs-region = var.aws_region, awslogs-stream-prefix = "recommendation" } }
  }])
  tags = local.tags
}
resource "aws_ecs_service" "api" {
  name            = format("%s-api", local.prefix)
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.api.arn
  desired_count   = var.api_desired_count
  launch_type     = "FARGATE"
  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.tasks.id]
    assign_public_ip = false
  }
  load_balancer {
    target_group_arn = aws_lb_target_group.api.arn
    container_name   = "api"
    container_port   = 8000
  }
  depends_on = [aws_lb_listener.http, aws_iam_role_policy_attachment.execution]
  tags = local.tags
}
resource "aws_ecs_service" "ingestion" {
  name            = format("%s-ingestion", local.prefix)
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.ingestion.arn
  desired_count   = var.worker_desired_count
  launch_type     = "FARGATE"
  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.tasks.id]
    assign_public_ip = false
  }
  depends_on = [aws_iam_role_policy_attachment.execution, aws_iam_role_policy.execution_secrets]
  tags = local.tags
}
resource "aws_ecs_service" "recommendation" {
  name            = format("%s-recommendation", local.prefix)
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.recommendation.arn
  desired_count   = var.worker_desired_count
  launch_type     = "FARGATE"
  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.tasks.id]
    assign_public_ip = false
  }
  depends_on = [aws_iam_role_policy_attachment.execution, aws_iam_role_policy.execution_secrets]
  tags = local.tags
}
resource "aws_appautoscaling_target" "api" {
  max_capacity        = var.api_max_capacity
  min_capacity        = var.api_min_capacity
  resource_id         = format("service/%s/%s", aws_ecs_cluster.main.name, aws_ecs_service.api.name)
  scalable_dimension  = "ecs:service:DesiredCount"
  service_namespace   = "ecs"
}
resource "aws_appautoscaling_policy" "api_cpu" {
  name               = format("%s-api-cpu", local.prefix)
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.api.resource_id
  scalable_dimension = aws_appautoscaling_target.api.scalable_dimension
  service_namespace  = aws_appautoscaling_target.api.service_namespace
  target_tracking_scaling_policy_configuration {
    target_value = 60
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
  }
}
resource "aws_appautoscaling_target" "ingestion" {
  max_capacity        = var.worker_max_capacity
  min_capacity        = var.worker_min_capacity
  resource_id         = format("service/%s/%s", aws_ecs_cluster.main.name, aws_ecs_service.ingestion.name)
  scalable_dimension  = "ecs:service:DesiredCount"
  service_namespace   = "ecs"
}
resource "aws_appautoscaling_policy" "ingestion_cpu" {
  name               = format("%s-ingestion-cpu", local.prefix)
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.ingestion.resource_id
  scalable_dimension = aws_appautoscaling_target.ingestion.scalable_dimension
  service_namespace  = aws_appautoscaling_target.ingestion.service_namespace
  target_tracking_scaling_policy_configuration {
    target_value = 65
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
  }
}
resource "aws_appautoscaling_target" "recommendation" {
  max_capacity        = var.worker_max_capacity
  min_capacity        = var.worker_min_capacity
  resource_id         = format("service/%s/%s", aws_ecs_cluster.main.name, aws_ecs_service.recommendation.name)
  scalable_dimension  = "ecs:service:DesiredCount"
  service_namespace   = "ecs"
}
resource "aws_appautoscaling_policy" "recommendation_cpu" {
  name               = format("%s-recommendation-cpu", local.prefix)
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.recommendation.resource_id
  scalable_dimension = aws_appautoscaling_target.recommendation.scalable_dimension
  service_namespace  = aws_appautoscaling_target.recommendation.service_namespace
  target_tracking_scaling_policy_configuration {
    target_value = 65
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
  }
}
