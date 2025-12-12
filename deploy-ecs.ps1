# Script PowerShell để deploy lên AWS ECS
# Usage: .\deploy-ecs.ps1

param(
    [string]$AWS_REGION = "ap-southeast-1",
    [string]$ECR_REPO_NAME = "plate-violation-system",
    [string]$CLUSTER_NAME = "plate-violation-cluster",
    [string]$SERVICE_NAME = "plate-violation-service",
    [string]$TASK_DEFINITION = "plate-violation-task"
)

Write-Host "🚀 Deploy lên AWS ECS" -ForegroundColor Cyan
Write-Host ""

# Lấy image URI
$accountId = aws sts get-caller-identity --query Account --output text
$imageUri = "$accountId.dkr.ecr.$AWS_REGION.amazonaws.com/$ECR_REPO_NAME`:latest"

Write-Host "📦 Image URI: $imageUri" -ForegroundColor Yellow
Write-Host ""

# Tạo task definition
Write-Host "📝 Tạo ECS Task Definition..." -ForegroundColor Yellow

$taskDefJson = @"
{
  "family": "$TASK_DEFINITION",
  "networkMode": "awsvpc",
  "requiresCompatibilities": ["FARGATE"],
  "cpu": "1024",
  "memory": "2048",
  "containerDefinitions": [
    {
      "name": "plate-violation",
      "image": "$imageUri",
      "essential": true,
      "portMappings": [
        {
          "containerPort": 5000,
          "protocol": "tcp"
        }
      ],
      "environment": [
        {
          "name": "MYSQL_HOST",
          "value": "your-mysql-host"
        },
        {
          "name": "MYSQL_USER",
          "value": "root"
        },
        {
          "name": "MYSQL_PASSWORD",
          "value": "your-password"
        },
        {
          "name": "MYSQL_DB",
          "value": "plate_violation"
        }
      ],
      "secrets": [
        {
          "name": "SECRET_KEY",
          "valueFrom": "arn:aws:secretsmanager:REGION:ACCOUNT:secret:plate-violation/secret"
        },
        {
          "name": "TELEGRAM_TOKEN",
          "valueFrom": "arn:aws:secretsmanager:REGION:ACCOUNT:secret:plate-violation/telegram-token"
        }
      ],
      "logConfiguration": {
        "logDriver": "awslogs",
        "options": {
          "awslogs-group": "/ecs/$TASK_DEFINITION",
          "awslogs-region": "$AWS_REGION",
          "awslogs-stream-prefix": "ecs"
        }
      }
    }
  ]
}
"@

$taskDefJson | Out-File -FilePath "task-definition.json" -Encoding UTF8
Write-Host "✅ Task definition đã được tạo: task-definition.json" -ForegroundColor Green
Write-Host ""
Write-Host "⚠️  LƯU Ý: Cần chỉnh sửa task-definition.json với:" -ForegroundColor Yellow
Write-Host "   - MySQL host, user, password" -ForegroundColor White
Write-Host "   - Secrets Manager ARN cho SECRET_KEY và TELEGRAM_TOKEN" -ForegroundColor White
Write-Host "   - VPC, Subnet, Security Group" -ForegroundColor White
Write-Host ""
Write-Host "Sau đó chạy:" -ForegroundColor Yellow
Write-Host "   aws ecs register-task-definition --cli-input-json file://task-definition.json --region $AWS_REGION" -ForegroundColor Cyan
Write-Host "   aws ecs create-service --cluster $CLUSTER_NAME --service-name $SERVICE_NAME --task-definition $TASK_DEFINITION --desired-count 1 --region $AWS_REGION" -ForegroundColor Cyan

