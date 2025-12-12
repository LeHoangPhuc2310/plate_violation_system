# Script PowerShell để chạy ứng dụng trong Docker
# Usage: .\docker-run.ps1

Write-Host "🐳 Chạy Plate Violation System với Docker..." -ForegroundColor Cyan

# Kiểm tra file .env
if (-not (Test-Path .env)) {
    Write-Host "❌ File .env không tồn tại!" -ForegroundColor Red
    Write-Host "Tạo file .env từ .env.example và điền thông tin:" -ForegroundColor Yellow
    Write-Host "Copy-Item .env.example .env" -ForegroundColor Yellow
    exit 1
}

# Kiểm tra Docker đang chạy
try {
    docker ps | Out-Null
} catch {
    Write-Host "❌ Docker không đang chạy! Vui lòng khởi động Docker Desktop." -ForegroundColor Red
    exit 1
}

# Kiểm tra image đã build chưa
$imageExists = docker images plate-violation:latest -q
if (-not $imageExists) {
    Write-Host "📦 Image chưa được build. Đang build image..." -ForegroundColor Yellow
    Write-Host "Chọn loại build:" -ForegroundColor Cyan
    Write-Host "1. CPU-only (không cần GPU) - Khuyến nghị" -ForegroundColor Green
    Write-Host "2. GPU (cần NVIDIA GPU và Docker với GPU support)" -ForegroundColor Green
    $choice = Read-Host "Nhập lựa chọn (1 hoặc 2)"
    
    if ($choice -eq "1") {
        docker build -f Dockerfile.cpu -t plate-violation:latest .
    } else {
        docker build -t plate-violation:latest .
    }
    
    if ($LASTEXITCODE -ne 0) {
        Write-Host "❌ Build image thất bại!" -ForegroundColor Red
        exit 1
    }
}

# Dừng và xóa container cũ (nếu có)
$existingContainer = docker ps -a -q -f name=plate-violation-app
if ($existingContainer) {
    Write-Host "🛑 Dừng container cũ..." -ForegroundColor Yellow
    docker stop plate-violation-app 2>$null
    docker rm plate-violation-app 2>$null
}

# Tạo thư mục nếu chưa có
New-Item -ItemType Directory -Force -Path uploads, static/uploads, static/plate_images, static/violation_videos | Out-Null

# Chạy container
Write-Host "🚀 Đang khởi động container..." -ForegroundColor Green
docker run -d `
    --name plate-violation-app `
    -p 5000:5000 `
    --env-file .env `
    --add-host=host.docker.internal:host-gateway `
    -v "${PWD}/uploads:/app/uploads" `
    -v "${PWD}/static:/app/static" `
    plate-violation:latest

if ($LASTEXITCODE -eq 0) {
    Write-Host "✅ Container đã khởi động thành công!" -ForegroundColor Green
    Write-Host "📊 Xem logs: docker logs -f plate-violation-app" -ForegroundColor Cyan
    Write-Host "🌐 Truy cập: http://localhost:5000" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Đang hiển thị logs (Ctrl+C để dừng)..." -ForegroundColor Yellow
    docker logs -f plate-violation-app
} else {
    Write-Host "❌ Khởi động container thất bại!" -ForegroundColor Red
    Write-Host "Kiểm tra logs: docker logs plate-violation-app" -ForegroundColor Yellow
}

