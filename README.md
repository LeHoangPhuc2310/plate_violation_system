<div align="center">

# 🚗🚦 Hệ Thống Nhận Diện Biển Số & Tính Toán Tốc Độ Vi Phạm

[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/)
[![Flask](https://img.shields.io/badge/Flask-2.3.3-green.svg)](https://flask.palletsprojects.com/)
[![YOLO](https://img.shields.io/badge/YOLO-v11-orange.svg)](https://github.com/ultralytics/ultralytics)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![GPU](https://img.shields.io/badge/GPU-CUDA%2011.8%2B-red.svg)](https://developer.nvidia.com/cuda-downloads)

> **Hệ thống AI thông minh phát hiện và theo dõi vi phạm tốc độ giao thông sử dụng Deep Learning**

[📖 Tài liệu](#-tài-liệu) • [🚀 Cài đặt](#-cài-đặt-nhanh) • [⚙️ Cấu hình](#-cấu-hình) • [📊 Tính năng](#-tính-năng) • [🏗️ Kiến trúc](#️-kiến-trúc)

---

</div>

## 📋 Mục Lục

- [✨ Tính năng](#-tính-năng)
- [🏗️ Kiến trúc](#️-kiến-trúc)
- [🚀 Cài đặt nhanh](#-cài-đặt-nhanh)
- [⚙️ Cấu hình](#-cấu-hình)
- [📊 Demo](#-demo)
- [🔧 Sử dụng](#-sử-dụng)
- [🌐 Deploy](#-deploy)
- [📖 Tài liệu](#-tài-liệu)
- [🤝 Đóng góp](#-đóng-góp)
- [📄 License](#-license)

---

## ✨ Tính năng

<div align="center">

### 🎯 Core Features

| Tính năng | Mô tả | Status |
|-----------|-------|--------|
| 🚗 **Phát hiện xe tự động** | YOLOv11n detect 4 loại xe (ô tô, xe máy, xe tải, xe bus) | ✅ |
| 📍 **Tracking chính xác** | OC-SORT/ByteTrack với Kalman Filter | ✅ |
| 🏷️ **Đọc biển số** | Fast-ALPR đọc biển số xe Việt Nam | ✅ |
| 🚦 **Tính toán tốc độ** | Theo dõi vị trí và tính tốc độ real-time | ✅ |
| 📱 **Thông báo Telegram** | Tự động gửi ảnh/video vi phạm | ✅ |
| 📊 **Dashboard Web** | Giao diện quản lý và xem vi phạm | ✅ |
| 🎥 **Hỗ trợ video** | Camera trực tiếp hoặc upload video | ✅ |
| ⚡ **Tối ưu GPU** | Tăng tốc với CUDA, FP16, multi-threading | ✅ |

</div>

### 🎨 Tính năng nổi bật

- 🚀 **Real-time Processing**: Xử lý video real-time với 5 thread độc lập
- 🎯 **High Accuracy**: Độ chính xác cao với YOLOv11n và Fast-ALPR
- ⚡ **GPU Acceleration**: Hỗ trợ CUDA và Apple Silicon (MPS)
- 🔄 **Multi-threading**: 5 thread độc lập, không block video stream
- 📱 **Telegram Integration**: Tự động gửi thông báo vi phạm
- 🌐 **Web Dashboard**: Giao diện web đầy đủ tính năng
- 🎥 **Video Support**: Camera trực tiếp hoặc upload video file

---

## 🏗️ Kiến trúc

<div align="center">

### 📊 System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     VIDEO SOURCE                            │
│              (Camera / Video File / Upload)                 │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│  THREAD 1: VIDEO THREAD                                     │
│  • Đọc video với tốc độ gốc                                │
│  • Push frame vào detection_queue                          │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│  THREAD 2: DETECTION WORKER                                 │
│  • YOLOv11n: Detect xe                                      │
│  • OC-SORT: Tracking với Kalman Filter                     │
│  • SpeedTracker: Tính tốc độ                               │
│  • Fast-ALPR: Đọc biển số                                  │
│  • Vẽ bbox + tốc độ lên frame                              │
└──────────────────────┬──────────────────────────────────────┘
                       │
        ┌──────────────┴──────────────┐
        │                             │
        ▼                             ▼
┌───────────────┐         ┌──────────────────────┐
│  STREAM       │         │  VIOLATION QUEUE     │
│  (Web Admin)  │         │  (Vi phạm tốc độ)    │
└───────────────┘         └──────────┬───────────┘
                                     │
                                     ▼
                    ┌────────────────────────────────┐
                    │  THREAD 3: VIOLATION WORKER   │
                    │  • Tạo DB record              │
                    │  • Crop ảnh xe/biển số        │
                    │  • Tạo video vi phạm          │
                    │  • Push vào ALPR queue        │
                    └──────────┬─────────────────────┘
                               │
                               ▼
                    ┌────────────────────────────────┐
                    │  THREAD 5: ALPR WORKER        │
                    │  • Đọc biển số từ ảnh         │
                    │  • Validate & normalize        │
                    │  • Enhance ảnh biển số        │
                    │  • Update database            │
                    │  • Push vào Telegram queue    │
                    └──────────┬─────────────────────┘
                               │
                               ▼
                    ┌────────────────────────────────┐
                    │  THREAD 4: TELEGRAM WORKER    │
                    │  • Gửi ảnh/video qua Bot      │
                    │  • Tuần tự (tránh spam)       │
                    └────────────────────────────────┘
```

</div>

### 🔄 Data Flow

1. **Video Thread** đọc frame từ camera/video → `detection_queue`
2. **Detection Worker** detect xe, tracking, tính tốc độ, đọc biển số
3. **Admin Frame** (có bbox) → `stream_queue` → Web Dashboard
4. **Violation detected** → `violation_queue` → Violation Worker
5. **Violation Worker** tạo record DB, crop ảnh → `alpr_queue`
6. **ALPR Worker** đọc biển số, update DB → `telegram_queue`
7. **Telegram Worker** gửi thông báo qua Telegram Bot

### 💾 Queues & Buffers

| Queue/Buffer | Mục đích | Size | Type |
|--------------|----------|------|------|
| `detection_queue` | Frame từ video → detection | 15-20 | deque |
| `stream_queue` | Frame có bbox → web stream | 30 | Queue |
| `violation_queue` | Vi phạm → violation worker | 20 | Queue |
| `alpr_queue` | Vi phạm → ALPR worker | 50 | Queue |
| `telegram_queue` | Vi phạm → Telegram worker | 50 | Queue |
| `admin_frame_buffer` | Backup frame có bbox | 90/60 | deque |
| `violation_frame_buffer` | Frame gốc cho video vi phạm | 90 | dict[deque] |

---

## 🚀 Cài đặt nhanh

### 📋 Yêu cầu hệ thống

- **Python**: 3.10+ 
- **GPU**: NVIDIA GPU với CUDA 11.8+ (khuyến nghị) hoặc Apple Silicon
- **RAM**: Tối thiểu 8GB (16GB khuyến nghị)
- **Storage**: Tối thiểu 10GB (cho models và dependencies)
- **Database**: MySQL 8.0+
- **OS**: Windows 10+, Linux, macOS

### 1️⃣ Clone Repository

```bash
git clone https://github.com/LeHoangPhuc2310/plate_violation_system.git
cd plate_violation_system
```

### 2️⃣ Tạo Virtual Environment

**Windows:**
```bash
python -m venv venv
venv\Scripts\activate
```

**Linux/macOS:**
```bash
python3 -m venv venv
source venv/bin/activate
```

### 3️⃣ Cài đặt Dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 4️⃣ Cài đặt GPU Support (NVIDIA)

**Cài CUDA Toolkit:**
- Download: https://developer.nvidia.com/cuda-downloads
- Cài đặt CUDA 11.8 hoặc mới hơn

**Cài PyTorch với CUDA:**
```bash
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu118
```

### 5️⃣ Cấu hình Database

**Tạo database:**
```sql
CREATE DATABASE plate_violation CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

**Tạo bảng:**
```sql
CREATE TABLE violations (
    id INT PRIMARY KEY AUTO_INCREMENT,
    plate VARCHAR(20),
    speed FLOAT,
    speed_limit INT,
    time DATETIME,
    image VARCHAR(255),
    plate_image VARCHAR(255),
    video_path VARCHAR(255),
    vehicle_class VARCHAR(50)
);

CREATE TABLE vehicle_owner (
    id INT PRIMARY KEY AUTO_INCREMENT,
    plate VARCHAR(20) UNIQUE,
    owner_name VARCHAR(255),
    address VARCHAR(255),
    phone VARCHAR(20)
);
```

### 6️⃣ Cấu hình Environment

Tạo file `.env` từ template:
```bash
cp env.template .env
```

Chỉnh sửa `.env`:
```env
# Database
MYSQL_HOST=localhost
MYSQL_USER=root
MYSQL_PASSWORD=your_password
MYSQL_DB=plate_violation

# Telegram Bot
TELEGRAM_TOKEN=your_telegram_bot_token
TELEGRAM_CHAT_ID=your_chat_id

# Flask
SECRET_KEY=your-secret-key-here
FLASK_ENV=production
PORT=5000
```

### 7️⃣ Chạy ứng dụng

```bash
python app.py
```

Truy cập: **http://localhost:5000**

---

## ⚙️ Cấu hình

### 🎛️ Cấu hình Detector

File: `app.py`

```python
# GPU/CPU detection
DEVICE = 'cuda'  # 'cuda', 'mps', hoặc 'cpu'

# Detection settings
DETECTION_FREQUENCY = 1      # Detect mỗi frame
DETECTION_SCALE = 1.0        # Scale frame (1.0 = full resolution)

# Speed limit
speed_limit = 40  # km/h

# Violation cooldown
VIOLATION_COOLDOWN = 3  # giây
```

### 🎨 Cấu hình Tracking

File: `combined_detector.py`

**OC-SORT:**
```python
OCSort(
    det_thresh=0.25,      # Detection threshold
    max_age=20,           # Max frames lost
    min_hits=2,           # Min hits to confirm
    iou_threshold=0.25    # IoU threshold
)
```

### 📊 Cấu hình Speed Tracker

File: `speed_tracker.py`

```python
SpeedTracker(
    pixel_to_meter=0.13  # Camera: 0.13, Video: 0.2
)
```

**Calibration:**
- Đo khoảng cách thực tế giữa 2 điểm trong video (mét)
- Đo khoảng cách pixel giữa 2 điểm đó
- `pixel_to_meter = khoảng_cách_thực_tế / khoảng_cách_pixel`

---

## 📊 Demo

### 🎥 Video Stream

- **Admin Stream**: `/video_feed` - Video có bbox và tốc độ
- **Clean Stream**: `/video_feed_clean` - Video gốc (không bbox)

### 📱 Telegram Notifications

Khi phát hiện vi phạm, hệ thống tự động gửi:
- 📷 Ảnh xe vi phạm (clean, không bbox)
- 🏷️ Ảnh biển số
- 🎥 Video vi phạm (nếu có)
- 📊 Thông tin: Biển số, tốc độ, chủ xe, địa chỉ

### 📈 Web Dashboard

- **Dashboard**: Xem vi phạm real-time
- **History**: Lịch sử vi phạm
- **Admin**: Quản lý xe, chỉnh sửa thông tin

---

## 🔧 Sử dụng

### 🎥 Chạy với Camera

1. Kết nối camera USB hoặc IP camera
2. Chỉnh sửa `app.py`:
   ```python
   cap = cv2.VideoCapture(0)  # USB camera
   # hoặc
   cap = cv2.VideoCapture("rtsp://ip:port/stream")  # IP camera
   ```
3. Chạy: `python app.py`

### 📁 Chạy với Video File

1. Upload video qua web interface: `/`
2. Hoặc đặt video vào thư mục `uploads/`
3. Hệ thống tự động xử lý

### 📱 Cấu hình Telegram Bot

1. Tạo bot với [@BotFather](https://t.me/BotFather)
2. Lấy token
3. Lấy Chat ID:
   - Gửi tin nhắn cho bot
   - Truy cập: `https://api.telegram.org/bot<TOKEN>/getUpdates`
   - Tìm `chat.id`
4. Thêm vào `.env`

---

## 🌐 Deploy

### 🚀 Deploy lên AWS EC2

Xem hướng dẫn chi tiết: [AWS_DEPLOY_GUIDE.md](AWS_DEPLOY_GUIDE.md)

**Quick Start:**
```bash
# 1. Launch EC2 instance (g4dn.xlarge hoặc lớn hơn)
# 2. SSH vào instance
ssh -i your-key.pem ubuntu@your-ec2-ip

# 3. Clone và setup
git clone https://github.com/LeHoangPhuc2310/plate_violation_system.git
cd plate_violation_system
chmod +x ec2-setup.sh
./ec2-setup.sh

# 4. Chạy ứng dụng
python app.py
```

### 🐳 Deploy với Docker

Xem hướng dẫn: [DOCKER_GUIDE.md](DOCKER_GUIDE.md)

**Quick Start:**
```bash
# Build image
docker build -f Dockerfile -t plate-violation:latest .

# Run container
docker run -d \
  -p 5000:5000 \
  -e MYSQL_HOST=your-db-host \
  -e MYSQL_USER=your-user \
  -e MYSQL_PASSWORD=your-password \
  -e MYSQL_DB=plate_violation \
  plate-violation:latest
```

### ☁️ Deploy lên AWS ECS

Xem hướng dẫn: [README_AWS.md](README_AWS.md)

---

## 📖 Tài liệu

### 📚 Tài liệu chi tiết

- **[QUY_TRINH_XU_LY_CHI_TIET.md](QUY_TRINH_XU_LY_CHI_TIET.md)** - Quy trình xử lý từ A-Z
- **[HUONG_DAN_CAU_HINH.md](HUONG_DAN_CAU_HINH.md)** - Hướng dẫn cấu hình chi tiết
- **[AWS_DEPLOY_GUIDE.md](AWS_DEPLOY_GUIDE.md)** - Hướng dẫn deploy AWS
- **[DOCKER_GUIDE.md](DOCKER_GUIDE.md)** - Hướng dẫn Docker
- **[TROUBLESHOOTING.md](TROUBLESHOOTING.md)** - Xử lý lỗi thường gặp

### 🔍 API Endpoints

| Endpoint | Method | Mô tả |
|----------|--------|-------|
| `/` | GET | Dashboard chính |
| `/video_feed` | GET | Video stream (có bbox) |
| `/video_feed_clean` | GET | Video stream (clean) |
| `/violations` | GET | Danh sách vi phạm |
| `/api/violations` | GET | API lấy vi phạm (JSON) |
| `/upload` | POST | Upload video |

### 📊 Database Schema

**violations:**
- `id`: ID vi phạm
- `plate`: Biển số
- `speed`: Tốc độ (km/h)
- `speed_limit`: Giới hạn tốc độ
- `time`: Thời gian vi phạm
- `image`: Ảnh vi phạm
- `plate_image`: Ảnh biển số
- `video_path`: Video vi phạm
- `vehicle_class`: Loại xe

**vehicle_owner:**
- `id`: ID
- `plate`: Biển số (unique)
- `owner_name`: Tên chủ xe
- `address`: Địa chỉ
- `phone`: Số điện thoại

---

## 🛠️ Công nghệ sử dụng

<div align="center">

| Category | Technology | Version |
|----------|-----------|---------|
| **Web Framework** | Flask | 2.3.3 |
| **Computer Vision** | OpenCV | 4.8.1 |
| **Deep Learning** | PyTorch | 2.1.0 |
| **Object Detection** | YOLOv11 (Ultralytics) | 8.1.0 |
| **License Plate OCR** | Fast-ALPR | 0.3.0 |
| **Tracking** | OC-SORT / ByteTrack | - |
| **Database** | MySQL | 8.0+ |
| **Tracking Filter** | FilterPy | 1.4.5 |

</div>

---

## 🐛 Xử lý lỗi

### ❌ Lỗi thường gặp

**1. ModuleNotFoundError: No module named 'flask_mysqldb'**
```bash
pip install flask-mysqldb==1.0.1
pip install Flask==2.3.3 Werkzeug==2.3.7
```

**2. CUDA out of memory**
- Giảm `DETECTION_SCALE` xuống 0.7
- Giảm batch size
- Sử dụng model nhỏ hơn

**3. Database connection error**
- Kiểm tra MySQL đang chạy
- Kiểm tra credentials trong `.env`
- Kiểm tra firewall

Xem thêm: [TROUBLESHOOTING.md](TROUBLESHOOTING.md)

---

## 🤝 Đóng góp

Chúng tôi rất hoan nghênh mọi đóng góp! 

1. Fork repository
2. Tạo feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to branch (`git push origin feature/AmazingFeature`)
5. Mở Pull Request

### 📝 Code Style

- Tuân thủ PEP 8
- Sử dụng type hints
- Viết docstring cho functions
- Comment code phức tạp

---

## 📄 License

Distributed under the MIT License. See `LICENSE` for more information.

---

## 👨‍💻 Tác giả

**LeHoangPhuc2310**

- GitHub: [@LeHoangPhuc2310](https://github.com/LeHoangPhuc2310)

---

## 🙏 Lời cảm ơn

- [Ultralytics](https://github.com/ultralytics/ultralytics) - YOLOv11
- [Fast-ALPR](https://github.com/onurkavafoglu/fast-alpr) - License Plate Recognition
- [OC-SORT](https://github.com/noahcao/OC_SORT) - Tracking algorithm

---

<div align="center">

### ⭐ Nếu project này hữu ích, hãy cho một star! ⭐

Made with ❤️ by LeHoangPhuc2310

</div>
