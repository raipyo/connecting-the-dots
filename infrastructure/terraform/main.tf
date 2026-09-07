# Terraform configuration for AWS infrastructure

terraform {
  required_version = ">= 1.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

# VPC Configuration
resource "aws_vpc" "connecting_dots_vpc" {
  cidr_block           = "10.0.0.0/16"
  enable_dns_hostnames = true
  enable_dns_support   = true
  
  tags = {
    Name        = "connecting-dots-vpc"
    Environment = var.environment
  }
}

# Subnets
resource "aws_subnet" "public_subnets" {
  count             = length(var.public_subnet_cidrs)
  vpc_id            = aws_vpc.connecting_dots_vpc.id
  cidr_block        = var.public_subnet_cidrs[count.index]
  availability_zone = var.availability_zones[count.index]
  
  tags = {
    Name        = "connecting-dots-public-subnet-${count.index + 1}"
    Environment = var.environment
  }
}

resource "aws_subnet" "private_subnets" {
  count             = length(var.private_subnet_cidrs)
  vpc_id            = aws_vpc.connecting_dots_vpc.id
  cidr_block        = var.private_subnet_cidrs[count.index]
  availability_zone = var.availability_zones[count.index]
  
  tags = {
    Name        = "connecting-dots-private-subnet-${count.index + 1}"
    Environment = var.environment
  }
}

# Internet Gateway
resource "aws_internet_gateway" "connecting_dots_igw" {
  vpc_id = aws_vpc.connecting_dots_vpc.id
  
  tags = {
    Name        = "connecting-dots-igw"
    Environment = var.environment
  }
}

# Route Tables
resource "aws_route_table" "public_route_table" {
  vpc_id = aws_vpc.connecting_dots_vpc.id
  
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.connecting_dots_igw.id
  }
  
  tags = {
    Name        = "connecting-dots-public-rt"
    Environment = var.environment
  }
}

resource "aws_route_table_association" "public_associations" {
  count          = length(var.public_subnet_cidrs)
  subnet_id      = aws_subnet.public_subnets[count.index].id
  route_table_id = aws_route_table.public_route_table.id
}

# RDS PostgreSQL with pgvector
resource "aws_db_instance" "postgres" {
  identifier     = "connecting-dots-db"
  engine         = "postgres"
  engine_version = "16.3"
  instance_class = var.db_instance_class
  
  allocated_storage     = 100
  storage_encrypted     = true
  storage_type          = "gp3"
  
  db_name  = var.db_name
  username = var.db_username
  password = var.db_password
  
  vpc_security_group_ids = [aws_security_group.rds_sg.id]
  db_subnet_group_name   = aws_db_subnet_group.rds_subnet_group.name
  
  backup_retention_period = 30
  backup_window          = "03:00-04:00"
  maintenance_window     = "Sun:04:00-Sun:05:00"
  
  skip_final_snapshot = false
  final_snapshot_identifier = "connecting-dots-final-snapshot"
  
  tags = {
    Name        = "connecting-dots-postgres"
    Environment = var.environment
  }
}

resource "aws_db_subnet_group" "rds_subnet_group" {
  name       = "connecting-dots-rds-subnet-group"
  subnet_ids = aws_subnet.private_subnets[*].id
  
  tags = {
    Name        = "connecting-dots-rds-subnet-group"
    Environment = var.environment
  }
}

# Elasticache Redis
resource "aws_elasticache_cluster" "redis" {
  cluster_id           = "connecting-dots-redis"
  engine               = "redis"
  node_type            = var.redis_node_type
  num_cache_nodes      = 1
  parameter_group_name = "default.redis7"
  port                 = 6379
  
  subnet_group_name = aws_elasticache_subnet_group.redis_subnet_group.name
  security_group_ids = [aws_security_group.redis_sg.id]
  
  tags = {
    Name        = "connecting-dots-redis"
    Environment = var.environment
  }
}

resource "aws_elasticache_subnet_group" "redis_subnet_group" {
  name       = "connecting-dots-redis-subnet-group"
  subnet_ids = aws_subnet.private_subnets[*].id
}

# S3 Bucket for storage
resource "aws_s3_bucket" "connecting_dots_bucket" {
  bucket = "connecting-dots-${var.environment}-${data.aws_caller_identity.current.account_id}"
  
  tags = {
    Name        = "connecting-dots-s3-bucket"
    Environment = var.environment
  }
}

resource "aws_s3_bucket_versioning" "connecting_dots_bucket_versioning" {
  bucket = aws_s3_bucket.connecting_dots_bucket.id
  versioning_configuration {
    status = "Enabled"
  }
}

# ECS Cluster
resource "aws_ecs_cluster" "connecting_dots_cluster" {
  name = "connecting-dots-cluster-${var.environment}"
  
  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

# ECS Task Definition for Backend
resource "aws_ecs_task_definition" "backend_task" {
  family                   = "connecting-dots-backend"
  network_mode            = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                     = var.backend_cpu
  memory                  = var.backend_memory
  execution_role_arn      = aws_iam_role.ecs_execution_role.arn
  task_role_arn           = aws_iam_role.ecs_task_role.arn
  
  container_definitions = jsonencode([
    {
      name  = "backend"
      image = "${aws_ecr_repository.backend_repository.repository_url}:latest"
      
      environment = [
        {
          name  = "DATABASE_URL"
          value = "postgresql://${var.db_username}:${var.db_password}@${aws_db_instance.postgres.address}:5432/${var.db_name}"
        },
        {
          name  = "REDIS_URL"
          value = "redis://${aws_elasticache_cluster.redis.cache_nodes[0].address}:6379/0"
        },
        {
          name  = "OPENAI_API_KEY"
          value = var.openai_api_key
        },
        {
          name  = "TAVILY_API_KEY"
          value = var.tavily_api_key
        }
      ]
      
      portMappings = [
        {
          containerPort = 8000
          hostPort      = 8000
          protocol      = "tcp"
        }
      ]
      
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = "/ecs/connecting-dots-backend"
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "ecs"
        }
      }
    }
  ])
}

# ECS Service
resource "aws_ecs_service" "backend_service" {
  name            = "connecting-dots-backend-service"
  cluster         = aws_ecs_cluster.connecting_dots_cluster.id
  task_definition = aws_ecs_task_definition.backend_task.arn
  desired_count   = var.backend_desired_count
  launch_type     = "FARGATE"
  
  network_configuration {
    subnets          = aws_subnet.private_subnets[*].id
    security_groups  = [aws_security_group.ecs_tasks_sg.id]
    assign_public_ip = false
  }
  
  load_balancer {
    target_group_arn = aws_lb_target_group.backend_tg.arn
    container_name   = "backend"
    container_port   = 8000
  }
}

# Application Load Balancer
resource "aws_lb" "connecting_dots_lb" {
  name               = "connecting-dots-lb"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.lb_sg.id]
  subnets           = aws_subnet.public_subnets[*].id
  
  tags = {
    Name        = "connecting-dots-lb"
    Environment = var.environment
  }
}

resource "aws_lb_target_group" "backend_tg" {
  name     = "connecting-dots-backend-tg"
  port     = 8000
  protocol = "HTTP"
  vpc_id   = aws_vpc.connecting_dots_vpc.id
  
  health_check {
    enabled             = true
    path                = "/api/health"
    interval            = 30
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 2
  }
}

resource "aws_lb_listener" "backend_listener" {
  load_balancer_arn = aws_lb.connecting_dots_lb.arn
  port              = "80"
  protocol          = "HTTP"
  
  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.backend_tg.arn
  }
}