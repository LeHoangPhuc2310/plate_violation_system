# Deploy to AWS
$config = Get-Content aws-config.json | ConvertFrom-Json
$region = $config.region
$accountId = $config.accountId
$keyPairName = $config.ec2.keyPairName

Write-Host "Deploy Plate Violation System to AWS" -ForegroundColor Cyan

# Check AWS
aws sts get-caller-identity | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "AWS not configured!" -ForegroundColor Red
    exit 1
}

# Get VPC
$vpcId = aws ec2 describe-vpcs --region $region --filters "Name=isDefault,Values=true" --query "Vpcs[0].VpcId" --output text
Write-Host "VPC: $vpcId" -ForegroundColor Green

# Create Security Group
$sgName = $config.ec2.securityGroupName
$sgId = aws ec2 describe-security-groups --region $region --filters "Name=group-name,Values=$sgName" "Name=vpc-id,Values=$vpcId" --query "SecurityGroups[0].GroupId" --output text 2>&1

if ($sgId -and $sgId -ne "None" -and $sgId -notlike "*error*") {
    Write-Host "Security Group exists: $sgId" -ForegroundColor Green
} else {
    $sgResult = aws ec2 create-security-group --region $region --group-name $sgName --description "Security group for Plate Violation System" --vpc-id $vpcId --output json | ConvertFrom-Json
    $sgId = $sgResult.GroupId
    aws ec2 authorize-security-group-ingress --region $region --group-id $sgId --protocol tcp --port 22 --cidr 0.0.0.0/0 | Out-Null
    aws ec2 authorize-security-group-ingress --region $region --group-id $sgId --protocol tcp --port 80 --cidr 0.0.0.0/0 | Out-Null
    aws ec2 authorize-security-group-ingress --region $region --group-id $sgId --protocol tcp --port 5000 --cidr 0.0.0.0/0 | Out-Null
    Write-Host "Created Security Group: $sgId" -ForegroundColor Green
}

# Get Subnet
$subnetId = aws ec2 describe-subnets --region $region --filters "Name=vpc-id,Values=$vpcId" --query "Subnets[0].SubnetId" --output text
Write-Host "Subnet: $subnetId" -ForegroundColor Green

# Get AMI
$ami = aws ec2 describe-images --region $region --owners 099720109477 --filters "Name=name,Values=ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*" "Name=state,Values=available" --query "Images | sort_by(@, &CreationDate) | [-1].ImageId" --output text
Write-Host "AMI: $ami" -ForegroundColor Green

# Create user data
$userData = @"
#!/bin/bash
apt-get update -y
apt-get install -y docker.io docker-compose
systemctl start docker
systemctl enable docker
usermod -aG docker ubuntu
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
unzip -q awscliv2.zip
./aws/install
sleep 10
aws ecr get-login-password --region $region | docker login --username AWS --password-stdin $accountId.dkr.ecr.$region.amazonaws.com
docker pull $accountId.dkr.ecr.$region.amazonaws.com/$($config.ecrRepository):latest
cat > /home/ubuntu/.env << 'EOF'
MYSQL_HOST=PLACEHOLDER_RDS_ENDPOINT
MYSQL_USER=$($config.rds.masterUsername)
MYSQL_PASSWORD=$($config.rds.masterPassword)
MYSQL_DB=$($config.rds.databaseName)
SECRET_KEY=$($config.application.secretKey)
TELEGRAM_TOKEN=$($config.application.telegramToken)
TELEGRAM_CHAT_ID=$($config.application.telegramChatId)
EOF
docker run -d --name plate-violation-app -p 5000:5000 --env-file /home/ubuntu/.env --restart unless-stopped $accountId.dkr.ecr.$region.amazonaws.com/$($config.ecrRepository):latest
"@

$userDataBase64 = [Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes($userData))

# Create EC2
Write-Host "Creating EC2 instance..." -ForegroundColor Yellow
$instanceJson = aws ec2 run-instances --region $region --image-id $ami --instance-type $config.ec2.instanceType --key-name $keyPairName --security-group-ids $sgId --subnet-id $subnetId --user-data $userDataBase64 --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=plate-violation-system}]" --output json | ConvertFrom-Json
$instanceId = $instanceJson.Instances[0].InstanceId
Write-Host "EC2 Instance created: $instanceId" -ForegroundColor Green

# Wait and get IP
Start-Sleep -Seconds 30
$publicIp = aws ec2 describe-instances --region $region --instance-ids $instanceId --query "Reservations[0].Instances[0].PublicIpAddress" --output text
Write-Host "Public IP: $publicIp" -ForegroundColor Green

# Create RDS
if ($config.rds.createNew) {
    Write-Host "Creating RDS..." -ForegroundColor Yellow
    $dbInstanceId = $config.rds.instanceIdentifier
    $subnetGroupName = $config.rds.subnetGroupName
    $subnets = aws ec2 describe-subnets --region $region --filters "Name=vpc-id,Values=$vpcId" --query "Subnets[*].SubnetId" --output text
    aws rds create-db-subnet-group --region $region --db-subnet-group-name $subnetGroupName --db-subnet-group-description "Subnet group for Plate Violation DB" --subnet-ids $subnets 2>&1 | Out-Null
    aws rds create-db-instance --region $region --db-instance-identifier $dbInstanceId --db-instance-class $config.rds.instanceClass --engine $config.rds.engine --engine-version $config.rds.engineVersion --master-username $config.rds.masterUsername --master-user-password $config.rds.masterPassword --allocated-storage $config.rds.allocatedStorage --db-name $config.rds.databaseName --vpc-security-group-ids $sgId --db-subnet-group-name $subnetGroupName --publicly-accessible --backup-retention-period 7 | Out-Null
    Write-Host "RDS instance created (starting, may take 5-10 minutes)" -ForegroundColor Green
}

Write-Host ""
Write-Host "Deploy completed!" -ForegroundColor Green
Write-Host "EC2 Instance ID: $instanceId" -ForegroundColor Yellow
Write-Host "Public IP: $publicIp" -ForegroundColor Yellow
Write-Host "Application URL: http://$publicIp:5000" -ForegroundColor Cyan
Write-Host "SSH: ssh -i your-key.pem ubuntu@$publicIp" -ForegroundColor Cyan

