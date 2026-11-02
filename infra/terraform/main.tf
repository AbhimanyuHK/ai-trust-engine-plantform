# Network component
resource "aws_vpc" "main" {
  cidr_block=var.vpc_cidr
  enable_dns_support=true
  enable_dns_hostnames=true
  tags=merge(local.tags,{Name=format("%s-vpc",local.prefix)})
}
resource "aws_internet_gateway" "main" { vpc_id=aws_vpc.main.id, tags=local.tags }
resource "aws_subnet" "public" {
  count=2
  vpc_id=aws_vpc.main.id
  availability_zone=local.azs[count.index]
  cidr_block=cidrsubnet(var.vpc_cidr,8,count.index)
  map_public_ip_on_launch=true
  tags=merge(local.tags,{Name=format("%s-public-%d",local.prefix,count.index+1),Tier="public"})
}
resource "aws_subnet" "private" {
  count=2
  vpc_id=aws_vpc.main.id
  availability_zone=local.azs[count.index]
  cidr_block=cidrsubnet(var.vpc_cidr,8,count.index+10)
  tags=merge(local.tags,{Name=format("%s-private-%d",local.prefix,count.index+1),Tier="private"})
}
resource "aws_eip" "nat" { count=var.single_nat_gateway ? 1 : 2, domain="vpc", depends_on=[aws_internet_gateway.main], tags=local.tags }
resource "aws_nat_gateway" "main" {
  count=var.single_nat_gateway ? 1 : 2
  allocation_id=aws_eip.nat[count.index].id
  subnet_id=aws_subnet.public[count.index].id
  depends_on=[aws_internet_gateway.main]
  tags=local.tags
}
resource "aws_route_table" "public" {
  vpc_id=aws_vpc.main.id
  route { cidr_block="0.0.0.0/0", gateway_id=aws_internet_gateway.main.id }
  tags=local.tags
}
resource "aws_route_table_association" "public" { count=2, subnet_id=aws_subnet.public[count.index].id, route_table_id=aws_route_table.public.id }
resource "aws_route_table" "private" {
  count=2
  vpc_id=aws_vpc.main.id
  route { cidr_block="0.0.0.0/0", nat_gateway_id=aws_nat_gateway.main[var.single_nat_gateway ? 0 : count.index].id }
  tags=local.tags
}
resource "aws_route_table_association" "private" { count=2, subnet_id=aws_subnet.private[count.index].id, route_table_id=aws_route_table.private[count.index].id }
resource "aws_security_group" "alb" {
  name=format("%s-alb",local.prefix), vpc_id=aws_vpc.main.id
  ingress { from_port=80,to_port=80,protocol="tcp",cidr_blocks=["0.0.0.0/0"] }
  ingress { from_port=443,to_port=443,protocol="tcp",cidr_blocks=["0.0.0.0/0"] }
  egress { from_port=0,to_port=0,protocol="-1",cidr_blocks=["0.0.0.0/0"] }
  tags=local.tags
}
resource "aws_security_group" "tasks" {
  name=format("%s-tasks",local.prefix), vpc_id=aws_vpc.main.id
  ingress { from_port=8000,to_port=8000,protocol="tcp",security_groups=[aws_security_group.alb.id] }
  egress { from_port=0,to_port=0,protocol="-1",cidr_blocks=["0.0.0.0/0"] }
  tags=local.tags
}

# S3 component: private, versioned, encrypted document bucket
resource "aws_s3_bucket" "contracts" { bucket=var.contract_bucket_name, force_destroy=var.environment!="prod", tags=local.tags }
resource "aws_s3_bucket_versioning" "contracts" { bucket=aws_s3_bucket.contracts.id, versioning_configuration { status="Enabled" } }
resource "aws_s3_bucket_server_side_encryption_configuration" "contracts" {
  bucket=aws_s3_bucket.contracts.id
  rule { apply_server_side_encryption_by_default { sse_algorithm="AES256" } }
}
resource "aws_s3_bucket_public_access_block" "contracts" {
  bucket=aws_s3_bucket.contracts.id
  block_public_acls=true, block_public_policy=true, ignore_public_acls=true, restrict_public_buckets=true
}

# Messaging component: queues plus dead-letter queues
resource "aws_sqs_queue" "ingestion_dlq" { name=format("%s-ingestion-dlq",local.prefix), message_retention_seconds=1209600, sqs_managed_sse_enabled=true, tags=local.tags }
resource "aws_sqs_queue" "recommendation_dlq" { name=format("%s-recommendation-dlq",local.prefix), message_retention_seconds=1209600, sqs_managed_sse_enabled=true, tags=local.tags }
resource "aws_sqs_queue" "ingestion" {
  name=format("%s-ingestion",local.prefix), visibility_timeout_seconds=900, receive_wait_time_seconds=20, sqs_managed_sse_enabled=true
  redrive_policy=jsonencode({deadLetterTargetArn=aws_sqs_queue.ingestion_dlq.arn,maxReceiveCount=5})
  tags=local.tags
}
resource "aws_sqs_queue" "recommendation" {
  name=format("%s-recommendation",local.prefix), visibility_timeout_seconds=900, receive_wait_time_seconds=20, sqs_managed_sse_enabled=true
  redrive_policy=jsonencode({deadLetterTargetArn=aws_sqs_queue.recommendation_dlq.arn,maxReceiveCount=5})
  tags=local.tags
}

# Compute component: ECR, ECS Fargate and public ALB
resource "aws_ecr_repository" "app" {
  name=local.prefix, image_tag_mutability="IMMUTABLE"
  image_scanning_configuration { scan_on_push=true }
  tags=local.tags
}
resource "aws_ecs_cluster" "main" {
  name=format("%s-cluster",local.prefix)
  setting { name="containerInsights",value="enabled" }
  tags=local.tags
}
resource "aws_cloudwatch_log_group" "api" { name=format("/ecs/%s/api",local.prefix), retention_in_days=var.log_retention_days, tags=local.tags }
resource "aws_cloudwatch_log_group" "ingestion" { name=format("/ecs/%s/ingestion",local.prefix), retention_in_days=var.log_retention_days, tags=local.tags }
resource "aws_cloudwatch_log_group" "recommendation" { name=format("/ecs/%s/recommendation",local.prefix), retention_in_days=var.log_retention_days, tags=local.tags }
resource "aws_iam_role" "execution" {
  name=format("%s-execution",local.prefix)
  assume_role_policy=jsonencode({Version="2012-10-17",Statement=[{Effect="Allow",Principal={Service="ecs-tasks.amazonaws.com"},Action="sts:AssumeRole"}]})
  tags=local.tags
}
resource "aws_iam_role_policy_attachment" "execution" {
  role=aws_iam_role.execution.name
  policy_arn="arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}
resource "aws_iam_role" "task" {
  name=format("%s-task",local.prefix)
  assume_role_policy=jsonencode({Version="2012-10-17",Statement=[{Effect="Allow",Principal={Service="ecs-tasks.amazonaws.com"},Action="sts:AssumeRole"}]})
  tags=local.tags
}
resource "aws_iam_role_policy" "task" {
  role=aws_iam_role.task.id, name="trust-application-access"
  policy=jsonencode({Version="2012-10-17",Statement=[
    {Effect="Allow",Action=["s3:GetObject","s3:PutObject"],Resource=[format("%s/*",aws_s3_bucket.contracts.arn)]},
    {Effect="Allow",Action=["s3:ListBucket"],Resource=[aws_s3_bucket.contracts.arn]},
    {Effect="Allow",Action=["sqs:ReceiveMessage","sqs:DeleteMessage","sqs:ChangeMessageVisibility","sqs:GetQueueAttributes","sqs:SendMessage"],Resource=[aws_sqs_queue.ingestion.arn,aws_sqs_queue.recommendation.arn]},
    {Effect="Allow",Action=["secretsmanager:GetSecretValue"],Resource=[var.snowflake_secret_arn]}
  ]})
}
resource "aws_lb" "api" {
  name=substr(format("%s-alb",local.prefix),0,32), load_balancer_type="application", security_groups=[aws_security_group.alb.id], subnets=aws_subnet.public[*].id, tags=local.tags
  enable_deletion_protection=var.environment=="prod"
}
resource "aws_lb_target_group" "api" {
  name=substr(format("%s-api",local.prefix),0,32), port=8000, protocol="HTTP", target_type="ip", vpc_id=aws_vpc.main.id
  health_check { path="/health", matcher="200-399" }
  tags=local.tags
}
resource "aws_lb_listener" "http" {
  load_balancer_arn=aws_lb.api.arn, port=80, protocol="HTTP"
  default_action { type="forward", target_group_arn=aws_lb_target_group.api.arn }
}
resource "aws_lb_listener" "https" {
  count=var.acm_certificate_arn==null ? 0 : 1
  load_balancer_arn=aws_lb.api.arn, port=443, protocol="HTTPS", certificate_arn=var.acm_certificate_arn
  default_action { type="forward", target_group_arn=aws_lb_target_group.api.arn }
}
resource "aws_ecs_task_definition" "api" {
  family=format("%s-api",local.prefix), requires_compatibilities=["FARGATE"], network_mode="awsvpc", cpu=tostring(var.api_cpu), memory=tostring(var.api_memory)
  execution_role_arn=aws_iam_role.execution.arn, task_role_arn=aws_iam_role.task.arn
  container_definitions=jsonencode([{name="api",image=var.container_image,essential=true,command=var.api_command,portMappings=[{containerPort=8000}],environment=[
    {name="TRUST_ENVIRONMENT",value=var.environment},{name="INGESTION_QUEUE_URL",value=aws_sqs_queue.ingestion.url},{name="RECOMMENDATION_QUEUE_URL",value=aws_sqs_queue.recommendation.url}
  ],secrets=[{name="SNOWFLAKE_SECRET",valueFrom=var.snowflake_secret_arn}],logConfiguration={logDriver="awslogs",options={awslogs-group=aws_cloudwatch_log_group.api.name,awslogs-region=var.aws_region,awslogs-stream-prefix="api"}}}])
  tags=local.tags
}
resource "aws_ecs_task_definition" "ingestion" {
  family=format("%s-ingestion",local.prefix), requires_compatibilities=["FARGATE"], network_mode="awsvpc", cpu=tostring(var.worker_cpu), memory=tostring(var.worker_memory)
  execution_role_arn=aws_iam_role.execution.arn, task_role_arn=aws_iam_role.task.arn
  container_definitions=jsonencode([{name="ingestion",image=var.container_image,essential=true,command=var.ingestion_command,secrets=[{name="SNOWFLAKE_SECRET",valueFrom=var.snowflake_secret_arn}],environment=[{name="TRUST_ENVIRONMENT",value=var.environment},{name="INGESTION_QUEUE_URL",value=aws_sqs_queue.ingestion.url}],logConfiguration={logDriver="awslogs",options={awslogs-group=aws_cloudwatch_log_group.ingestion.name,awslogs-region=var.aws_region,awslogs-stream-prefix="ingestion"}}}])
  tags=local.tags
}
resource "aws_ecs_task_definition" "recommendation" {
  family=format("%s-recommendation",local.prefix), requires_compatibilities=["FARGATE"], network_mode="awsvpc", cpu=tostring(var.worker_cpu), memory=tostring(var.worker_memory)
  execution_role_arn=aws_iam_role.execution.arn, task_role_arn=aws_iam_role.task.arn
  container_definitions=jsonencode([{name="recommendation",image=var.container_image,essential=true,command=var.recommendation_command,secrets=[{name="SNOWFLAKE_SECRET",valueFrom=var.snowflake_secret_arn}],environment=[{name="TRUST_ENVIRONMENT",value=var.environment},{name="RECOMMENDATION_QUEUE_URL",value=aws_sqs_queue.recommendation.url}],logConfiguration={logDriver="awslogs",options={awslogs-group=aws_cloudwatch_log_group.recommendation.name,awslogs-region=var.aws_region,awslogs-stream-prefix="recommendation"}}}])
  tags=local.tags
}
resource "aws_ecs_service" "api" {
  name=format("%s-api",local.prefix), cluster=aws_ecs_cluster.main.id, task_definition=aws_ecs_task_definition.api.arn, desired_count=var.api_desired_count, launch_type="FARGATE"
  network_configuration { subnets=aws_subnet.private[*].id, security_groups=[aws_security_group.tasks.id], assign_public_ip=false }
  load_balancer { target_group_arn=aws_lb_target_group.api.arn, container_name="api", container_port=8000 }
  depends_on=[aws_lb_listener.http,aws_iam_role_policy_attachment.execution]
  tags=local.tags
}
resource "aws_ecs_service" "ingestion" {
  name=format("%s-ingestion",local.prefix), cluster=aws_ecs_cluster.main.id, task_definition=aws_ecs_task_definition.ingestion.arn, desired_count=var.worker_desired_count, launch_type="FARGATE"
  network_configuration { subnets=aws_subnet.private[*].id, security_groups=[aws_security_group.tasks.id], assign_public_ip=false }
  depends_on=[aws_iam_role_policy_attachment.execution]
  tags=local.tags
}
resource "aws_ecs_service" "recommendation" {
  name=format("%s-recommendation",local.prefix), cluster=aws_ecs_cluster.main.id, task_definition=aws_ecs_task_definition.recommendation.arn, desired_count=var.worker_desired_count, launch_type="FARGATE"
  network_configuration { subnets=aws_subnet.private[*].id, security_groups=[aws_security_group.tasks.id], assign_public_ip=false }
  depends_on=[aws_iam_role_policy_attachment.execution]
  tags=local.tags
}
resource "aws_appautoscaling_target" "api" {
  max_capacity=var.api_max_capacity, min_capacity=var.api_min_capacity
  resource_id=format("service/%s/%s",aws_ecs_cluster.main.name,aws_ecs_service.api.name)
  scalable_dimension="ecs:service:DesiredCount", service_namespace="ecs"
}
resource "aws_appautoscaling_policy" "api_cpu" {
  name=format("%s-api-cpu",local.prefix), policy_type="TargetTrackingScaling"
  resource_id=aws_appautoscaling_target.api.resource_id, scalable_dimension=aws_appautoscaling_target.api.scalable_dimension, service_namespace="ecs"
  target_tracking_scaling_policy_configuration { target_value=60, predefined_metric_specification { predefined_metric_type="ECSServiceAverageCPUUtilization" } }
}
resource "aws_appautoscaling_target" "ingestion" {
  max_capacity=var.worker_max_capacity, min_capacity=var.worker_min_capacity
  resource_id=format("service/%s/%s",aws_ecs_cluster.main.name,aws_ecs_service.ingestion.name)
  scalable_dimension="ecs:service:DesiredCount", service_namespace="ecs"
}
resource "aws_appautoscaling_policy" "ingestion_cpu" {
  name=format("%s-ingestion-cpu",local.prefix), policy_type="TargetTrackingScaling"
  resource_id=aws_appautoscaling_target.ingestion.resource_id, scalable_dimension=aws_appautoscaling_target.ingestion.scalable_dimension, service_namespace="ecs"
  target_tracking_scaling_policy_configuration { target_value=65, predefined_metric_specification { predefined_metric_type="ECSServiceAverageCPUUtilization" } }
}
resource "aws_appautoscaling_target" "recommendation" {
  max_capacity=var.worker_max_capacity, min_capacity=var.worker_min_capacity
  resource_id=format("service/%s/%s",aws_ecs_cluster.main.name,aws_ecs_service.recommendation.name)
  scalable_dimension="ecs:service:DesiredCount", service_namespace="ecs"
}
resource "aws_appautoscaling_policy" "recommendation_cpu" {
  name=format("%s-recommendation-cpu",local.prefix), policy_type="TargetTrackingScaling"
  resource_id=aws_appautoscaling_target.recommendation.resource_id, scalable_dimension=aws_appautoscaling_target.recommendation.scalable_dimension, service_namespace="ecs"
  target_tracking_scaling_policy_configuration { target_value=65, predefined_metric_specification { predefined_metric_type="ECSServiceAverageCPUUtilization" } }
}

# Security component: regional AWS managed WAF rules
resource "aws_wafv2_web_acl" "alb" {
  count=var.enable_waf ? 1 : 0
  name=format("%s-waf",local.prefix), scope="REGIONAL"
  default_action { allow {} }
  rule {
    name="AWSManagedCommonRuleSet", priority=10
    override_action { none {} }
    statement { managed_rule_group_statement { name="AWSManagedRulesCommonRuleSet",vendor_name="AWS" } }
    visibility_config { cloudwatch_metrics_enabled=true,metric_name="common",sampled_requests_enabled=true }
  }
  visibility_config { cloudwatch_metrics_enabled=true,metric_name=format("%s-waf",local.prefix),sampled_requests_enabled=true }
  tags=local.tags
}
resource "aws_wafv2_web_acl_association" "alb" {
  count=var.enable_waf ? 1 : 0
  resource_arn=aws_lb.api.arn, web_acl_arn=aws_wafv2_web_acl.alb[0].arn
}

# Observability component
resource "aws_cloudwatch_metric_alarm" "api_cpu" {
  alarm_name=format("%s-api-cpu-high",local.prefix), namespace="AWS/ECS", metric_name="CPUUtilization", statistic="Average", period=300, evaluation_periods=2, threshold=80, comparison_operator="GreaterThanThreshold"
  dimensions={ClusterName=aws_ecs_cluster.main.name,ServiceName=aws_ecs_service.api.name}
  tags=local.tags
}
resource "aws_cloudwatch_dashboard" "main" {
  dashboard_name=format("%s-operations",local.prefix)
  dashboard_body=jsonencode({widgets=[{type="metric",x=0,y=0,width=12,height=6,properties={title="API CPU",region=var.aws_region,metrics=[["AWS/ECS","CPUUtilization","ClusterName",aws_ecs_cluster.main.name,"ServiceName",aws_ecs_service.api.name]]}}]})
}