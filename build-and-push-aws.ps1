# Script PowerShell để build Docker image và push lên AWS ECR
# Usage: .\build-and-push-aws.ps1

param(
    [string]$AWS_REGION = "ap-southeast-1",  # Singapore region (gần Việt Nam)
    [string]$ECR_REPO_NAME = "plate-violation-system"
)

Write-Host "🐳 Build và Push Docker Image lên AWS ECR" -ForegroundColor Cyan
Write-Host ""

# Kiểm tra AWS CLI
Write-Host "📋 Kiểm tra AWS CLI..." -ForegroundColor Yellow
try {
    $awsVersion = aws --version 2>&1
    Write-Host "✅ AWS CLI: $awsVersion" -ForegroundColor Green
} catch {
    Write-Host "❌ AWS CLI chưa được cài đặt!" -ForegroundColor Red
    Write-Host "Cài đặt: https://aws.amazon.com/cli/" -ForegroundColor Yellow
    exit 1
}

# Kiểm tra AWS credentials
Write-Host "`n🔐 Kiểm tra AWS credentials..." -ForegroundColor Yellow
try {
    $awsIdentity = aws sts get-caller-identity 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host "❌ Chưa đăng nhập AWS! Chạy: aws configure" -ForegroundColor Red
        exit 1
    }
    Write-Host "✅ AWS credentials OK" -ForegroundColor Green
    Write-Host $awsIdentity -ForegroundColor Gray
} catch {
    Write-Host "❌ Lỗi kiểm tra AWS credentials" -ForegroundColor Red
    exit 1
}

# Tạo ECR repository (nếu chưa có)
Write-Host "`n📦 Kiểm tra ECR repository..." -ForegroundColor Yellow
$repoExists = aws ecr describe-repositories --repository-names $ECR_REPO_NAME --region $AWS_REGION 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "📝 Tạo ECR repository mới..." -ForegroundColor Yellow
    aws ecr create-repository --repository-name $ECR_REPO_NAME --region $AWS_REGION
    if ($LASTEXITCODE -ne 0) {
        Write-Host "❌ Không thể tạo ECR repository!" -ForegroundColor Red
        exit 1
    }
    Write-Host "✅ ECR repository đã được tạo" -ForegroundColor Green
} else {
    Write-Host "✅ ECR repository đã tồn tại" -ForegroundColor Green
}

# Lấy ECR login token
Write-Host "`n🔑 Đăng nhập vào ECR..." -ForegroundColor Yellow
$ecrUri = "$(aws sts get-caller-identity --query Account --output text).dkr.ecr.$AWS_REGION.amazonaws.com"
$fullImageName = "$ecrUri/$ECR_REPO_NAME`:latest"

aws ecr get-login-password --region $AWS_REGION | docker login --username AWS --password-stdin $ecrUri
if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Không thể đăng nhập ECR!" -ForegroundColor Red
    exit 1
}
Write-Host "✅ Đã đăng nhập ECR" -ForegroundColor Green

# Build Docker image
Write-Host "`n🔨 Đang build Docker image (có thể mất 5-10 phút)..." -ForegroundColor Yellow
docker build -f Dockerfile.cpu -t $ECR_REPO_NAME`:latest .
if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Build Docker image thất bại!" -ForegroundColor Red
    exit 1
}
Write-Host "✅ Build thành công!" -ForegroundColor Green

# Tag image
Write-Host "`n🏷️  Tagging image..." -ForegroundColor Yellow
docker tag $ECR_REPO_NAME`:latest $fullImageName
if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Tag image thất bại!" -ForegroundColor Red
    exit 1
}
Write-Host "✅ Tag thành công: $fullImageName" -ForegroundColor Green

# Push image lên ECR
Write-Host "`n📤 Đang push image lên ECR (có thể mất vài phút)..." -ForegroundColor Yellow
docker push $fullImageName
if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Push image thất bại!" -ForegroundColor Red
    exit 1
}
Write-Host "✅ Push thành công!" -ForegroundColor Green

# Hiển thị thông tin
Write-Host "`n" -NoNewline
Write-Host "=" * 60 -ForegroundColor Cyan
Write-Host "✅ HOÀN THÀNH!" -ForegroundColor Green
Write-Host "=" * 60 -ForegroundColor Cyan
Write-Host ""
Write-Host "📦 Image URI:" -ForegroundColor Yellow
Write-Host "   $fullImageName" -ForegroundColor White
Write-Host ""
Write-Host "🔗 ECR Repository:" -ForegroundColor Yellow
Write-Host "   https://console.aws.amazon.com/ecr/repositories/private/$AWS_REGION/$ECR_REPO_NAME" -ForegroundColor Cyan
Write-Host ""
Write-Host "📝 Bước tiếp theo:" -ForegroundColor Yellow
Write-Host "   1. Tạo ECS Task Definition hoặc EC2 instance" -ForegroundColor White
Write-Host "   2. Deploy container từ ECR image" -ForegroundColor White
Write-Host "   3. Xem hướng dẫn trong README_AWS.md" -ForegroundColor White
Write-Host ""

