# Deploy to existing EC2 and RDS
# Usage: .\deploy-to-existing.ps1

param(
    [string]$ConfigFile = "aws-config.json",
    [string]$InfraConfigFile = "existing-infra-config.json"
)

Write-Host "Deploy to Existing EC2 and RDS" -ForegroundColor Cyan
Write-Host ""

# Read configs
if (-not (Test-Path $ConfigFile)) {
    Write-Host "Config file not found: $ConfigFile" -ForegroundColor Red
    exit 1
}

if (-not (Test-Path $InfraConfigFile)) {
    Write-Host "Infrastructure config file not found: $InfraConfigFile" -ForegroundColor Red
    Write-Host "Please create $InfraConfigFile with your EC2 and RDS information" -ForegroundColor Yellow
    exit 1
}

$config = Get-Content $ConfigFile | ConvertFrom-Json
$infraConfig = Get-Content $InfraConfigFile | ConvertFrom-Json

$region = $config.region
$accountId = $config.accountId
$instanceId = $infraConfig.ec2.instanceId
$publicIp = $infraConfig.ec2.publicIp
$ec2User = $infraConfig.ec2.username
$rdsEndpoint = $infraConfig.rds.endpoint
$rdsPort = $infraConfig.rds.port
$rdsDb = $infraConfig.rds.databaseName
$rdsUser = $infraConfig.rds.username
$rdsPassword = $infraConfig.rds.password

Write-Host "Configuration:" -ForegroundColor Yellow
Write-Host "  EC2 Instance ID: $instanceId" -ForegroundColor White
Write-Host "  EC2 Public IP: $publicIp" -ForegroundColor White
Write-Host "  RDS Endpoint: $rdsEndpoint" -ForegroundColor White
Write-Host "  RDS Database: $rdsDb" -ForegroundColor White
Write-Host ""

# Create deployment script
$deployScript = @"
#!/bin/bash
set -e

echo "=== Installing Docker ==="
if ! command -v docker &> /dev/null; then
    sudo apt-get update -y
    sudo apt-get install -y docker.io docker-compose
    sudo systemctl start docker
    sudo systemctl enable docker
    sudo usermod -aG docker `$USER
    echo "Docker installed successfully"
else
    echo "Docker already installed"
fi

echo ""
echo "=== Installing AWS CLI ==="
if ! command -v aws &> /dev/null; then
    curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
    unzip -q awscliv2.zip
    sudo ./aws/install
    echo "AWS CLI installed successfully"
else
    echo "AWS CLI already installed"
fi

echo ""
echo "=== Logging into ECR ==="
aws ecr get-login-password --region $region | docker login --username AWS --password-stdin $accountId.dkr.ecr.$region.amazonaws.com

echo ""
echo "=== Pulling latest image ==="
docker pull $accountId.dkr.ecr.$region.amazonaws.com/$($config.ecrRepository):latest

echo ""
echo "=== Stopping existing container ==="
docker stop plate-violation-app 2>/dev/null || true
docker rm plate-violation-app 2>/dev/null || true

echo ""
echo "=== Creating .env file ==="
cat > /home/$ec2User/.env << 'ENVEOF'
MYSQL_HOST=$rdsEndpoint
MYSQL_PORT=$rdsPort
MYSQL_USER=$rdsUser
MYSQL_PASSWORD=$rdsPassword
MYSQL_DB=$rdsDb
SECRET_KEY=$($config.application.secretKey)
TELEGRAM_TOKEN=$($config.application.telegramToken)
TELEGRAM_CHAT_ID=$($config.application.telegramChatId)
ENVEOF

echo "Environment variables configured:"
cat /home/$ec2User/.env | grep -v PASSWORD

echo ""
echo "=== Starting container ==="
docker run -d \
  --name plate-violation-app \
  -p 5000:5000 \
  --env-file /home/$ec2User/.env \
  --restart unless-stopped \
  $accountId.dkr.ecr.$region.amazonaws.com/$($config.ecrRepository):latest

echo ""
echo "=== Deployment completed! ==="
echo ""
echo "Container status:"
docker ps -f name=plate-violation-app
echo ""
echo "Application URL: http://$publicIp:5000"
echo ""
echo "Useful commands:"
echo "  View logs: docker logs -f plate-violation-app"
echo "  Stop: docker stop plate-violation-app"
echo "  Start: docker start plate-violation-app"
echo "  Restart: docker restart plate-violation-app"
"@

# Save script
$deployScript | Out-File -FilePath "deploy-to-ec2.sh" -Encoding UTF8 -NoNewline
Write-Host "Deployment script created: deploy-to-ec2.sh" -ForegroundColor Green
Write-Host ""

# Create instructions
Write-Host "=" * 60 -ForegroundColor Cyan
Write-Host "DEPLOYMENT INSTRUCTIONS" -ForegroundColor Cyan
Write-Host "=" * 60 -ForegroundColor Cyan
Write-Host ""
Write-Host "Option 1: Using AWS Systems Manager (Recommended - No SSH key needed)" -ForegroundColor Yellow
Write-Host ""
Write-Host "Run this command:" -ForegroundColor White
$ssmCommand = "aws ssm send-command --region $region --instance-ids $instanceId --document-name AWS-RunShellScript --parameters `"commands=[\`"bash -s\`"]`" --cli-binary-format raw-in-base64-out --query Command.CommandId --output text"
Write-Host "  $ssmCommand" -ForegroundColor Cyan
Write-Host ""
Write-Host "Or use interactive session:" -ForegroundColor White
Write-Host "  aws ssm start-session --region $region --target $instanceId" -ForegroundColor Cyan
Write-Host "  Then copy and paste the content of deploy-to-ec2.sh" -ForegroundColor Gray
Write-Host ""

Write-Host "Option 2: Using SSH (Requires key pair file)" -ForegroundColor Yellow
Write-Host ""
Write-Host "1. Upload script to EC2:" -ForegroundColor White
Write-Host "   scp -i your-key.pem deploy-to-ec2.sh ${ec2User}@${publicIp}:/home/$ec2User/" -ForegroundColor Cyan
Write-Host ""
Write-Host "2. SSH into EC2:" -ForegroundColor White
Write-Host "   ssh -i your-key.pem ${ec2User}@${publicIp}" -ForegroundColor Cyan
Write-Host ""
Write-Host "3. Run deployment:" -ForegroundColor White
Write-Host "   chmod +x deploy-to-ec2.sh" -ForegroundColor Cyan
Write-Host "   ./deploy-to-ec2.sh" -ForegroundColor Cyan
Write-Host ""

Write-Host "=" * 60 -ForegroundColor Green
Write-Host "SUMMARY" -ForegroundColor Green
Write-Host "=" * 60 -ForegroundColor Green
Write-Host "  EC2 Instance: $instanceId" -ForegroundColor White
Write-Host "  EC2 Public IP: $publicIp" -ForegroundColor White
Write-Host "  RDS Endpoint: $rdsEndpoint" -ForegroundColor White
Write-Host "  Application URL: http://$publicIp:5000" -ForegroundColor Cyan
Write-Host ""

