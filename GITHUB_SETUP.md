# 🚀 Hướng dẫn đưa code lên GitHub

## 📋 Bước 1: Chuẩn bị

### 1.1. Kiểm tra Git đã cài đặt

```bash
git --version
```

Nếu chưa có, cài đặt từ: https://git-scm.com/downloads

### 1.2. Cấu hình Git (nếu chưa có)

```bash
git config --global user.name "LeHoangPhuc2310"
git config --global user.email "lehoangphuc2310@gmail.com"
```

---

## 📦 Bước 2: Khởi tạo Git Repository

### 2.1. Kiểm tra xem đã có .git chưa

```bash
# Windows PowerShell
if (Test-Path .git) { Write-Host "Git repository đã tồn tại" } else { Write-Host "Chưa có Git repository" }

# Linux/macOS
if [ -d .git ]; then echo "Git repository đã tồn tại"; else echo "Chưa có Git repository"; fi
```

### 2.2. Khởi tạo Git repository (nếu chưa có)

```bash
git init
```

### 2.3. Kiểm tra .gitignore đã có chưa

File `.gitignore` đã được tạo sẵn với các rules:
- `__pycache__/`
- `*.pyc`
- `venv/`
- `.env`
- `uploads/`
- `static/violation_videos/`
- `*.mp4`
- `*.pt` (trừ yolo11n.pt)

---

## 🔗 Bước 3: Tạo Repository trên GitHub

### 3.1. Đăng nhập GitHub

1. Truy cập: https://github.com
2. Đăng nhập với tài khoản của bạn

### 3.2. Tạo Repository mới

1. Click **"New"** hoặc **"+"** → **"New repository"**
2. Điền thông tin:
   - **Repository name:** `plate_violation_system`
   - **Description:** `AI-Powered Traffic Violation Detection System using YOLOv11, OC-SORT and FastALPR`
   - **Visibility:** Public (hoặc Private)
   - **⚠️ KHÔNG check "Initialize with README"** (vì đã có README.md)
3. Click **"Create repository"**

---

## 📤 Bước 4: Push code lên GitHub

### 4.1. Thêm files vào staging area

```bash
# Kiểm tra status
git status

# Thêm tất cả files (trừ những file trong .gitignore)
git add .

# Hoặc thêm từng file cụ thể
git add README.md
git add app.py
git add requirements.txt
# ... etc
```

### 4.2. Commit changes

```bash
git commit -m "🎉 Initial commit: Plate Violation Detection System

✨ Features:
- 6-thread architecture for real-time processing
- YOLOv11 vehicle detection
- OC-SORT/ByteTrack multi-object tracking
- FastALPR license plate recognition
- MySQL database integration
- Telegram notifications
- Docker support
- Professional UI/UX

📝 Documentation:
- Complete README with badges and icons
- API documentation
- Docker deployment guide
- AWS deployment guide"
```

### 4.3. Thêm remote repository

```bash
# Thay YOUR_USERNAME bằng username GitHub của bạn
git remote add origin https://github.com/YOUR_USERNAME/plate_violation_system.git

# Hoặc sử dụng SSH (nếu đã setup SSH key)
git remote add origin git@github.com:YOUR_USERNAME/plate_violation_system.git
```

### 4.4. Push code lên GitHub

```bash
# Push lần đầu (set upstream)
git push -u origin main

# Hoặc nếu branch là master
git push -u origin master
```

**Nếu gặp lỗi:** Có thể branch mặc định là `master` thay vì `main`. Kiểm tra:

```bash
git branch
```

Nếu là `master`, đổi tên:

```bash
git branch -M main
git push -u origin main
```

---

## 🔄 Bước 5: Cập nhật code sau này

### 5.1. Workflow thông thường

```bash
# 1. Kiểm tra status
git status

# 2. Thêm files đã thay đổi
git add .

# 3. Commit với message mô tả
git commit -m "✨ Add new feature: video creation with FFmpeg/OpenCV fallback"

# 4. Push lên GitHub
git push
```

### 5.2. Commit message format (khuyến nghị)

```bash
# Format: [Emoji] Action: Description

git commit -m "✨ Add: Video creation with organized folder structure"
git commit -m "🐛 Fix: Video not created when FFmpeg unavailable"
git commit -m "📝 Update: README with professional badges and icons"
git commit -m "🔧 Refactor: Improve code structure"
git commit -m "🚀 Deploy: Add Docker Compose support"
```

**Emoji thường dùng:**
- ✨ `:sparkles:` - New feature
- 🐛 `:bug:` - Bug fix
- 📝 `:memo:` - Documentation
- 🔧 `:wrench:` - Refactoring
- 🚀 `:rocket:` - Deployment
- ⚡ `:zap:` - Performance
- 🎨 `:art:` - UI/UX
- 🔒 `:lock:` - Security

---

## 🌿 Bước 6: Tạo Branch cho Feature mới

### 6.1. Tạo và chuyển sang branch mới

```bash
# Tạo branch mới
git checkout -b feature/new-feature

# Hoặc (Git 2.23+)
git switch -c feature/new-feature
```

### 6.2. Làm việc trên branch

```bash
# Make changes...
git add .
git commit -m "✨ Add new feature"

# Push branch lên GitHub
git push -u origin feature/new-feature
```

### 6.3. Tạo Pull Request

1. Truy cập GitHub repository
2. Click **"Compare & pull request"**
3. Điền mô tả và tạo PR
4. Sau khi review, merge vào `main`

---

## 📋 Checklist trước khi push

- [ ] ✅ Đã kiểm tra `.gitignore` (không commit file nhạy cảm)
- [ ] ✅ Đã test code chạy được
- [ ] ✅ Đã cập nhật README.md
- [ ] ✅ Đã xóa file test/temp không cần thiết
- [ ] ✅ Đã commit với message rõ ràng
- [ ] ✅ Đã kiểm tra `git status` trước khi push

---

## 🚨 Troubleshooting

### Lỗi: "remote origin already exists"

```bash
# Xóa remote cũ
git remote remove origin

# Thêm lại
git remote add origin https://github.com/YOUR_USERNAME/plate_violation_system.git
```

### Lỗi: "failed to push some refs"

```bash
# Pull code từ GitHub trước
git pull origin main --rebase

# Sau đó push lại
git push
```

### Lỗi: "authentication failed"

```bash
# Sử dụng Personal Access Token thay vì password
# Tạo token tại: https://github.com/settings/tokens

# Hoặc setup SSH key
# Xem: https://docs.github.com/en/authentication/connecting-to-github-with-ssh
```

### Xóa file đã commit nhầm

```bash
# Xóa file khỏi Git (nhưng giữ file local)
git rm --cached filename

# Xóa file khỏi Git và local
git rm filename

# Commit
git commit -m "🗑️ Remove: unnecessary file"
git push
```

---

## 📚 Tài liệu tham khảo

- [Git Documentation](https://git-scm.com/doc)
- [GitHub Guides](https://guides.github.com/)
- [Git Commit Message Convention](https://www.conventionalcommits.org/)

---

## ✅ Sau khi push thành công

1. ✅ Truy cập: `https://github.com/YOUR_USERNAME/plate_violation_system`
2. ✅ Kiểm tra README hiển thị đúng
3. ✅ Kiểm tra badges hoạt động
4. ✅ Thêm description và topics cho repository:
   - Topics: `yolo`, `flask`, `opencv`, `license-plate-recognition`, `traffic-violation`, `python`, `ai`, `machine-learning`
5. ✅ Thêm screenshots vào README (nếu có)

---

**🎉 Chúc mừng! Code đã được đưa lên GitHub thành công!**

