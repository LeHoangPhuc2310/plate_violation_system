#!/bin/bash
# Bash script để push code lên GitHub
# Usage: ./push_to_github.sh "Commit message"

COMMIT_MESSAGE="${1:-📝 Update: Code changes}"

echo "🚀 Starting GitHub push process..."

# Kiểm tra Git đã cài đặt
if ! command -v git &> /dev/null; then
    echo "❌ Git chưa được cài đặt!"
    echo "📥 Cài đặt Git: sudo apt install git (Ubuntu/Debian)"
    exit 1
fi

echo "✅ Git found: $(git --version)"

# Kiểm tra đã có .git chưa
if [ ! -d .git ]; then
    echo "📦 Khởi tạo Git repository..."
    git init
    echo "✅ Git repository đã được khởi tạo"
fi

# Kiểm tra remote origin
if ! git remote get-url origin &> /dev/null; then
    echo "⚠️  Chưa có remote origin!"
    echo "📝 Vui lòng thêm remote:"
    echo "   git remote add origin https://github.com/YOUR_USERNAME/plate_violation_system.git"
    echo ""
    read -p "Bạn có muốn thêm remote ngay bây giờ? (y/n) " add_remote
    if [ "$add_remote" = "y" ] || [ "$add_remote" = "Y" ]; then
        read -p "Nhập GitHub repository URL: " repo_url
        git remote add origin "$repo_url"
        echo "✅ Đã thêm remote origin"
    else
        echo "❌ Không thể tiếp tục mà không có remote origin"
        exit 1
    fi
else
    REMOTE_URL=$(git remote get-url origin)
    echo "✅ Remote origin: $REMOTE_URL"
fi

# Kiểm tra status
echo ""
echo "📊 Checking git status..."
git status

# Thêm files
echo ""
echo "➕ Adding files to staging area..."
git add .

# Kiểm tra có changes không
CHANGES=$(git diff --cached --name-only)
if [ -z "$CHANGES" ]; then
    echo "⚠️  Không có thay đổi nào để commit!"
    exit 0
fi

# Commit
echo ""
echo "💾 Committing changes..."
echo "📝 Commit message: $COMMIT_MESSAGE"
git commit -m "$COMMIT_MESSAGE"

if [ $? -eq 0 ]; then
    echo "✅ Commit thành công!"
else
    echo "❌ Commit thất bại!"
    exit 1
fi

# Push
echo ""
echo "📤 Pushing to GitHub..."

# Kiểm tra branch hiện tại
CURRENT_BRANCH=$(git branch --show-current)
echo "🌿 Current branch: $CURRENT_BRANCH"

# Push
if [ "$CURRENT_BRANCH" = "main" ] || [ "$CURRENT_BRANCH" = "master" ]; then
    git push -u origin "$CURRENT_BRANCH"
else
    echo "⚠️  Bạn đang ở branch: $CURRENT_BRANCH"
    read -p "Bạn có muốn push branch này? (y/n) " push_branch
    if [ "$push_branch" = "y" ] || [ "$push_branch" = "Y" ]; then
        git push -u origin "$CURRENT_BRANCH"
    else
        echo "⏭️  Bỏ qua push"
    fi
fi

if [ $? -eq 0 ]; then
    echo ""
    echo "🎉 Push thành công lên GitHub!"
    REMOTE_URL=$(git remote get-url origin)
    echo "🔗 Xem repository tại: $REMOTE_URL"
else
    echo ""
    echo "❌ Push thất bại!"
    echo "💡 Thử pull trước: git pull origin $CURRENT_BRANCH --rebase"
fi

