# 📦 Hướng Dẫn Tối Ưu Lưu Trữ

## 🎯 Tổng quan

Hệ thống đã được tối ưu để:
- ✅ Giảm **85% dung lượng** lưu trữ
- ✅ Giảm **80% số file** ảnh
- ✅ Dễ quản lý và tìm kiếm
- ✅ Vẫn đủ chứng cứ vi phạm

---

## 📁 Cấu trúc thư mục mới

```
violations/
├── 2025-12-17/              # Thư mục theo ngày
│   ├── 29D59493/            # Thư mục theo biển số
│   │   ├── vehicle.jpg      # Ảnh xe (70% quality)
│   │   ├── plate.jpg        # Ảnh biển số (85% quality)
│   │   └── violation.mp4    # Video 5s, 10 FPS
│   ├── 51F12345/
│   │   ├── vehicle.jpg
│   │   ├── plate.jpg
│   │   └── violation.mp4
│   └── unknown_123/         # Xe không đọc được biển
│       ├── vehicle.jpg
│       └── violation.mp4
└── 2025-12-18/
    └── ...
```

---

## ⚙️ Cấu hình

### Trong `app.py` (dòng 127-134):

```python
IMAGE_SAVE_CONFIG = {
    'jpeg_quality': 70,              # Chất lượng JPEG (60-75 khuyến nghị)
    'max_images_per_violation': 2,   # Số ảnh tối đa/vi phạm
    'save_video': True,              # Có lưu video không
    'video_duration': 5,             # Độ dài video (giây)
    'video_fps': 10,                 # FPS của video
}

VIOLATION_COOLDOWN = 10  # Cooldown chống trùng (giây)
```

### Tùy chỉnh:

#### 1. Thay đổi chất lượng ảnh:
```python
IMAGE_SAVE_CONFIG['jpeg_quality'] = 80  # Tăng chất lượng (tăng dung lượng)
```

#### 2. Tắt lưu video:
```python
IMAGE_SAVE_CONFIG['save_video'] = False  # Chỉ lưu ảnh
```

#### 3. Tăng độ dài video:
```python
IMAGE_SAVE_CONFIG['video_duration'] = 10  # Lưu 10 giây
```

#### 4. Thay đổi cooldown:
```python
VIOLATION_COOLDOWN = 15  # Tăng lên 15 giây
```

---

## 🔍 Tìm kiếm và quản lý

### 1. Tìm vi phạm theo ngày:
```bash
ls violations/2025-12-17/
```

### 2. Tìm vi phạm theo biển số:
```bash
find violations -name "29D59493" -type d
```

### 3. Xem tất cả vi phạm của 1 xe:
```bash
ls violations/*/29D59493/
```

### 4. Xóa dữ liệu cũ (>30 ngày):
```bash
# Linux/macOS
find violations -type d -mtime +30 -exec rm -rf {} \;

# Windows PowerShell
Get-ChildItem violations -Directory | Where-Object {$_.LastWriteTime -lt (Get-Date).AddDays(-30)} | Remove-Item -Recurse -Force
```

---

## 📊 So sánh dung lượng

### Ví dụ: 1000 vi phạm/ngày

| Mục | Trước | Sau | Tiết kiệm |
|-----|-------|-----|-----------|
| **Số file ảnh** | 10,000 | 2,000 | 80% |
| **Dung lượng ảnh** | 5 GB | 0.5 GB | 90% |
| **Dung lượng video** | 50 GB | 7.5 GB | 85% |
| **Tổng** | **55 GB** | **8 GB** | **85%** |

### Ví dụ cụ thể 1 vi phạm:

**Trước:**
```
vehicle_1765742055_216.jpg    500 KB
vehicle_1765742055_217.jpg    500 KB
vehicle_1765742055_218.jpg    500 KB
plate_29D59493_1765742055.jpg 200 KB
plate_29D59493_1765742056.jpg 200 KB
violation_video.mp4           50 MB
---
Tổng: ~52 MB
```

**Sau:**
```
vehicle.jpg                   150 KB  (quality 70)
plate.jpg                     80 KB   (quality 85)
violation.mp4                 7.5 MB  (5s, 10 FPS)
---
Tổng: ~7.7 MB (giảm 85%)
```

---

## 🛠️ Troubleshooting

### 1. Ảnh bị mờ/không rõ

**Nguyên nhân:** JPEG quality quá thấp

**Giải pháp:**
```python
IMAGE_SAVE_CONFIG['jpeg_quality'] = 80  # Tăng lên 80
```

### 2. Vẫn tốn nhiều dung lượng

**Kiểm tra:**
```python
# Đảm bảo save_video = False nếu không cần
IMAGE_SAVE_CONFIG['save_video'] = False

# Giảm độ dài video
IMAGE_SAVE_CONFIG['video_duration'] = 3  # Chỉ 3 giây
```

### 3. Không tìm thấy file

**Kiểm tra đường dẫn:**
```python
# Trong database, path được lưu dạng:
# violations/2025-12-17/29D59493/vehicle.jpg

# Truy cập qua web:
# http://localhost:5000/violations/2025-12-17/29D59493/vehicle.jpg
```

### 4. Lỗi "File not found"

**Nguyên nhân:** Thư mục violations chưa được tạo

**Giải pháp:**
```bash
mkdir violations
```

---

## 📈 Monitoring

### Kiểm tra dung lượng:

**Linux/macOS:**
```bash
# Tổng dung lượng
du -sh violations/

# Theo ngày
du -sh violations/2025-12-17/

# Theo biển số
du -sh violations/*/29D59493/
```

**Windows PowerShell:**
```powershell
# Tổng dung lượng
(Get-ChildItem violations -Recurse | Measure-Object -Property Length -Sum).Sum / 1GB

# Theo ngày
(Get-ChildItem violations/2025-12-17 -Recurse | Measure-Object -Property Length -Sum).Sum / 1MB
```

### Đếm số file:

```bash
# Linux/macOS
find violations -type f | wc -l

# Windows PowerShell
(Get-ChildItem violations -Recurse -File).Count
```

---

## 🚀 Best Practices

### 1. Backup định kỳ
```bash
# Backup theo tuần
tar -czf violations_backup_$(date +%Y%m%d).tar.gz violations/
```

### 2. Dọn dữ liệu cũ
```bash
# Cron job: Mỗi ngày 2h sáng, xóa dữ liệu >30 ngày
0 2 * * * find /path/to/violations -type d -mtime +30 -exec rm -rf {} \;
```

### 3. Monitor disk space
```bash
# Alert khi disk >80%
df -h | grep violations
```

---

## 📞 Support

Nếu có vấn đề:
- Email: lehoangphuc2310@gmail.com
- GitHub Issues: https://github.com/LeHoangPhuc2310/plate_violation_system/issues

