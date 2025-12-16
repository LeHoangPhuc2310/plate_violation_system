# PowerShell script để push code lên GitHub
# Usage: .\push_to_github.ps1 "Commit message"

param(
    [Parameter(Mandatory=$false)]
    [string]$CommitMessage = "📝 Update: Code changes"
)

Write-Host "🚀 Starting GitHub push process..." -ForegroundColor Cyan

# Kiểm tra Git đã cài đặt
try {
    $gitVersion = git --version
    Write-Host "✅ Git found: $gitVersion" -ForegroundColor Green
} catch {
    Write-Host "❌ Git chưa được cài đặt!" -ForegroundColor Red
    Write-Host "📥 Tải Git từ: https://git-scm.com/downloads" -ForegroundColor Yellow
    exit 1
}

# Kiểm tra đã có .git chưa
if (-not (Test-Path .git)) {
    Write-Host "📦 Khởi tạo Git repository..." -ForegroundColor Yellow
    git init
    Write-Host "✅ Git repository đã được khởi tạo" -ForegroundColor Green
}

# Kiểm tra remote origin
$remoteExists = git remote get-url origin 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "⚠️  Chưa có remote origin!" -ForegroundColor Yellow
    Write-Host "📝 Vui lòng thêm remote:" -ForegroundColor Yellow
    Write-Host "   git remote add origin https://github.com/YOUR_USERNAME/plate_violation_system.git" -ForegroundColor Cyan
    Write-Host ""
    $addRemote = Read-Host "Bạn có muốn thêm remote ngay bây giờ? (y/n)"
    if ($addRemote -eq "y" -or $addRemote -eq "Y") {
        $repoUrl = Read-Host "Nhập GitHub repository URL"
        git remote add origin $repoUrl
        Write-Host "✅ Đã thêm remote origin" -ForegroundColor Green
    } else {
        Write-Host "❌ Không thể tiếp tục mà không có remote origin" -ForegroundColor Red
        exit 1
    }
} else {
    Write-Host "✅ Remote origin: $remoteExists" -ForegroundColor Green
}

# Kiểm tra status
Write-Host ""
Write-Host "📊 Checking git status..." -ForegroundColor Cyan
git status

# Thêm files
Write-Host ""
Write-Host "➕ Adding files to staging area..." -ForegroundColor Cyan
git add .

# Kiểm tra có changes không
$changes = git diff --cached --name-only
if ($changes.Count -eq 0) {
    Write-Host "⚠️  Không có thay đổi nào để commit!" -ForegroundColor Yellow
    exit 0
}

# Commit
Write-Host ""
Write-Host "💾 Committing changes..." -ForegroundColor Cyan
Write-Host "📝 Commit message: $CommitMessage" -ForegroundColor Yellow
git commit -m $CommitMessage

if ($LASTEXITCODE -eq 0) {
    Write-Host "✅ Commit thành công!" -ForegroundColor Green
} else {
    Write-Host "❌ Commit thất bại!" -ForegroundColor Red
    exit 1
}

# Push
Write-Host ""
Write-Host "📤 Pushing to GitHub..." -ForegroundColor Cyan

# Kiểm tra branch hiện tại
$currentBranch = git branch --show-current
Write-Host "🌿 Current branch: $currentBranch" -ForegroundColor Yellow

# Push
if ($currentBranch -eq "main" -or $currentBranch -eq "master") {
    git push -u origin $currentBranch
} else {
    Write-Host "⚠️  Bạn đang ở branch: $currentBranch" -ForegroundColor Yellow
    $pushBranch = Read-Host "Bạn có muốn push branch này? (y/n)"
    if ($pushBranch -eq "y" -or $pushBranch -eq "Y") {
        git push -u origin $currentBranch
    } else {
        Write-Host "⏭️  Bỏ qua push" -ForegroundColor Yellow
    }
}

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "🎉 Push thành công lên GitHub!" -ForegroundColor Green
    Write-Host "🔗 Xem repository tại: $remoteExists" -ForegroundColor Cyan
} else {
    Write-Host ""
    Write-Host "❌ Push thất bại!" -ForegroundColor Red
    Write-Host "💡 Thử pull trước: git pull origin $currentBranch --rebase" -ForegroundColor Yellow
}

