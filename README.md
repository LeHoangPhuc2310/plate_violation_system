# 🚗 Hệ Thống Nhận Diện Biển Số & Phát Hiện Vi Phạm Tốc Độ

<div align="center">

![Python](https://img.shields.io/badge/Python-3.10-blue.svg)
![Flask](https://img.shields.io/badge/Flask-3.0.0-green.svg)
![YOLOv11](https://img.shields.io/badge/YOLOv11-Latest-orange.svg)
![Docker](https://img.shields.io/badge/Docker-Ready-blue.svg)
![License](https://img.shields.io/badge/License-MIT-yellow.svg)

**Hệ thống AI tự động nhận diện biển số xe và phát hiện vi phạm tốc độ sử dụng YOLOv11, OC-SORT Tracking và FastALPR**

[Tính năng](#-tính-năng) • [Kiến trúc](#-kiến-trúc-hệ-thống) • [Cài đặt](#-cài-đặt) • [Sử dụng](#-hướng-dẫn-sử-dụng) • [Docker](#-docker-deployment) • [AWS](#-aws-cloud-deployment)

</div>

---

## 📋 Mục lục

- [Giới thiệu](#-giới-thiệu)
- [Tính năng](#-tính-năng)
- [Kiến trúc hệ thống](#-kiến-trúc-hệ-thống)
- [Công nghệ sử dụng](#-công-nghệ-sử-dụng)
- [Yêu cầu hệ thống](#-yêu-cầu-hệ-thống)
- [Cài đặt](#-cài-đặt)
- [Hướng dẫn sử dụng](#-hướng-dẫn-sử-dụng)
- [Docker Deployment](#-docker-deployment)
- [AWS Cloud Deployment](#-aws-cloud-deployment)
- [API Documentation](#-api-documentation)
- [Screenshots](#-screenshots)
- [Tác giả](#-tác-giả)
- [License](#-license)

---

## 🎯 Giới thiệu

Hệ thống **Plate Violation Detection System** là một ứng dụng AI tiên tiến được phát triển để tự động hóa việc phát hiện và xử lý vi phạm giao thông, đặc biệt là vi phạm tốc độ. Hệ thống sử dụng các công nghệ AI/ML tiên tiến nhất hiện nay để đảm bảo độ chính xác cao và hiệu suất xử lý real-time.

### 🎓 Thông tin dự án

- **Sinh viên thực hiện:** Lê Hoàng Phúc
- **MSSV:** 190501014
- **Trường:** Đại học Bình Dương - Phân hiệu Cà Mau
- **Năm:** 2024-2025

---

## ✨ Tính năng

### 🚀 Tính năng chính

- ✅ **Nhận diện biển số xe tự động** với độ chính xác cao (>90%)
- ✅ **Phát hiện vi phạm tốc độ** real-time
- ✅ **Tracking đa đối tượng** (OC-SORT/ByteTrack)
- ✅ **Tính toán tốc độ chính xác** dựa trên pixel movement
- ✅ **Lưu trữ bằng chứng** (ảnh xe, ảnh biển số, video vi phạm)
- ✅ **Gửi thông báo Telegram** tự động
- ✅ **Quản lý database** MySQL với full CRUD
- ✅ **Web interface** chuyên nghiệp và responsive
- ✅ **Hệ thống chống trùng lặp** vi phạm (cooldown 10s)
- ✅ **Multi-threading** tối ưu (6 threads)

### 🎨 Tính năng giao diện

- 📊 **Dashboard** real-time với live video stream
- 📋 **Quản lý vi phạm** với bộ lọc tìm kiếm
- 👥 **Quản lý chủ xe** (Admin only)
- 🔐 **Hệ thống đăng nhập** với phân quyền (Admin/Viewer)
- 📱 **Responsive design** - tương thích mọi thiết bị
- 🎭 **Dark mode navigation** với hiệu ứng gradient

---

## 🏗️ Kiến trúc hệ thống

### 6-Thread Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    VIDEO UPLOAD (Flask)                      │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│  THREAD 1: Video Thread                                      │
│  - Đọc frame từ video                                        │
│  - Push vào detection_queue                                  │
└────────────────────────┬────────────────────────────────────┘
                         │ detection_queue
                         ▼
┌─────────────────────────────────────────────────────────────┐
│  THREAD 2: Detection Worker                                  │
│  - YOLOv11n: Detect vehicles                                 │
│  - OC-SORT: Track objects                                    │
│  - SpeedTracker: Calculate speed                             │
└────────────────────────┬────────────────────────────────────┘
                         │ alpr_realtime_queue
                         ▼
┌─────────────────────────────────────────────────────────────┐
│  THREAD 3: ALPR Worker (Real-time)                           │
│  - FastALPR: Detect license plates                           │
│  - Validate plate format                                     │
└────────────────────────┬────────────────────────────────────┘
                         │ best_frame_queue
                         ▼
┌─────────────────────────────────────────────────────────────┐
│  THREAD 4: Best Frame Selector                               │
│  - Select best quality frame                                 │
│  - Aggregate plate detections                                │
└────────────────────────┬────────────────────────────────────┘
                         │ violation_queue
                         ▼
┌─────────────────────────────────────────────────────────────┐
│  THREAD 5: Violation Worker                                  │
│  - Save to MySQL database                                    │
│  - Create violation videos                                   │
│  - Anti-duplicate check (10s cooldown)                       │
└────────────────────────┬────────────────────────────────────┘
                         │ telegram_queue
                         ▼
┌─────────────────────────────────────────────────────────────┐
│  THREAD 6: Telegram Worker                                   │
│  - Send notifications to Telegram                            │
│  - Update violation status                                   │
└─────────────────────────────────────────────────────────────┘
```

---

## 🛠️ Công nghệ sử dụng

### Backend
- **Python 3.10** - Ngôn ngữ lập trình chính
- **Flask 3.0.0** - Web framework
- **MySQL 8.0** - Database
- **PyTorch** - Deep learning framework

### AI/ML Models
- **YOLOv11n** - Object detection (vehicles)
- **OC-SORT/ByteTrack** - Multi-object tracking
- **FastALPR** - License plate recognition

### Frontend
- **Bootstrap 4.6.2** - UI framework
- **Font Awesome 6.5.1** - Icons
- **Inter Font** - Typography
- **JavaScript/jQuery** - Interactivity


## 💻 Yêu cầu hệ thống

### Minimum Requirements
- **OS:** Windows 10/11, Ubuntu 20.04+, macOS 11+
- **CPU:** Intel Core i5 hoặc tương đương
- **RAM:** 8GB (khuyến nghị 16GB)
- **Storage:** 10GB free space
- **Python:** 3.10+

### Recommended (for GPU acceleration)
- **GPU:** NVIDIA GPU với CUDA 11.8+
- **VRAM:** 4GB+
- **CUDA:** 11.8
- **cuDNN:** 8.x

---

## 📦 Cài đặt

### 1. Clone repository

```bash
git clone https://github.com/LeHoangPhuc2310/plate_violation_system.git
cd plate_violation_system
```

### 2. Tạo virtual environment

```bash
# Windows
python -m venv venv
venv\Scripts\activate

# Linux/macOS
python3 -m venv venv
source venv/bin/activate
```

### 3. Cài đặt dependencies

```bash
# CPU version
pip install -r requirements.txt

# GPU version (NVIDIA CUDA 11.8)
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu118
pip install -r requirements.txt
```

### 4. Cấu hình MySQL Database

```sql
CREATE DATABASE plate_violation CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE plate_violation;

-- Import init.sql
SOURCE init.sql;
```

### 5. Cấu hình Telegram Bot (Optional)

1. Tạo bot mới với [@BotFather](https://t.me/botfather)
2. Lấy Bot Token
3. Lấy Chat ID của bạn
4. Cập nhật trong `app.py`:

```python
TELEGRAM_BOT_TOKEN = "your_bot_token_here"
TELEGRAM_CHAT_ID = "your_chat_id_here"
```

### 6. Chạy ứng dụng

```bash
python app.py
```

Truy cập: **http://localhost:5000**

**Tài khoản mặc định:**
- Username: `admin` / Password: `admin123` (Admin)
- Username: `viewer` / Password: `viewer123` (Viewer)

---

## 🎮 Hướng dẫn sử dụng

### 1. Đăng nhập
- Truy cập http://localhost:5000
- Đăng nhập với tài khoản admin hoặc viewer

### 2. Upload video
- Click **"Upload Video"** trên Dashboard
- Chọn file video (MP4, AVI, MOV)
- Click **"Upload"** để bắt đầu xử lý

### 3. Xem live stream
- Video sẽ hiển thị real-time với bounding boxes
- Thông tin tracking và tốc độ hiển thị trên mỗi xe

### 4. Xem vi phạm
- Click **"Xem vi phạm"** trên navbar
- Sử dụng bộ lọc để tìm kiếm:
  - Biển số xe
  - Khoảng thời gian
  - Mức vượt tốc độ

### 5. Quản lý chủ xe (Admin only)
- Click **"Quản trị"** trên navbar
- Thêm/Sửa/Xóa thông tin chủ xe
- Tìm kiếm theo biển số, tên, địa chỉ, SĐT

---

## 🐳 Docker Deployment

### Quick Start

```bash
# Build and run with Docker Compose
docker-compose up -d

# View logs
docker-compose logs -f app

# Stop services
docker-compose down
```

### Manual Docker Build

```bash
# Build CPU version
docker build -f Dockerfile.cpu -t plate-violation:cpu .

# Build GPU version (requires NVIDIA Docker)
docker build -f Dockerfile -t plate-violation:gpu .

# Run container
docker run -d -p 5000:5000 \
  -v $(pwd)/static/uploads:/app/static/uploads \
  -v $(pwd)/static/plate_images:/app/static/plate_images \
  -v $(pwd)/static/violation_videos:/app/static/violation_videos \
  --name plate-violation \
  plate-violation:cpu
```

### Docker Compose Services

- **mysql** - MySQL 8.0 database (port 3306)
- **app** - Flask application (port 5000)

---

## ☁️ AWS Cloud Deployment

### Prerequisites
- AWS Account
- AWS CLI configured
- Docker installed

### Deploy to AWS EC2

1. **Launch EC2 Instance**
   - AMI: Ubuntu 22.04 LTS
   - Instance Type: t3.medium (minimum)
   - Security Group: Allow ports 22, 80, 443, 5000

2. **Connect to EC2**
   ```bash
   ssh -i your-key.pem ubuntu@your-ec2-ip
   ```

3. **Install Docker**
   ```bash
   sudo apt update
   sudo apt install -y docker.io docker-compose
   sudo usermod -aG docker $USER
   ```

4. **Clone and Deploy**
   ```bash
   git clone https://github.com/LeHoangPhuc2310/plate_violation_system.git
   cd plate_violation_system
   docker-compose up -d
   ```

5. **Access Application**
   - http://your-ec2-ip:5000

### Deploy to AWS ECS (Elastic Container Service)

Coming soon...

---

## 📡 API Documentation

### Authentication Endpoints

#### POST /login
Login to system
```json
{
  "username": "admin",
  "password": "admin123"
}
```

#### GET /logout
Logout from system

### Video Processing Endpoints

#### POST /upload
Upload video for processing
- **Content-Type:** multipart/form-data
- **Body:** video file

#### GET /video_feed
Get MJPEG video stream

#### POST /stop_camera
Stop video processing

### Violation Management Endpoints

#### GET /history
Get violation list with filters
- **Query params:** plate, from_date, to_date, speed_over

#### GET /autocomplete
Autocomplete license plate search
- **Query params:** q (search term)

### Admin Endpoints (Admin only)

#### GET /admin/vehicles
Get vehicle owner list

#### POST /edit_owner/<plate>
Update vehicle owner information

#### GET /delete/<plate>
Delete vehicle owner

---

## 📸 Screenshots

### Dashboard - Live Video Stream
![Dashboard](docs/screenshots/dashboard.png)

### Violation List
![Violations](docs/screenshots/violations.png)

### Vehicle Management (Admin)
![Admin](docs/screenshots/admin.png)

### Login Page
![Login](docs/screenshots/login.png)

---

## 🔧 Troubleshooting

### Video không hiển thị
- Kiểm tra browser console (F12) để xem lỗi
- Đảm bảo `/video_feed` endpoint đang hoạt động
- Thử refresh trang (Ctrl+F5)

### Detection chậm
- Sử dụng GPU nếu có thể
- Giảm resolution video input
- Tăng `DETECTION_SKIP_FRAMES` trong app.py

### Database connection error
- Kiểm tra MySQL service đang chạy
- Verify database credentials trong app.py
- Đảm bảo database `plate_violation` đã được tạo

### Telegram không gửi được
- Kiểm tra Bot Token và Chat ID
- Verify bot đã được start (@BotFather)
- Kiểm tra internet connection

---

## 🚀 Performance Optimization

### CPU Optimization
- Sử dụng YOLOv11n (nano) thay vì YOLOv11s/m/l
- Tăng `DETECTION_SKIP_FRAMES` để giảm số frame xử lý
- Giảm resolution video input

### GPU Optimization
- Cài đặt CUDA 11.8 và cuDNN 8.x
- Sử dụng PyTorch với CUDA support
- Tăng batch size nếu VRAM đủ lớn

### Database Optimization
- Tạo index cho các cột thường query (plate, time)
- Sử dụng connection pooling
- Định kỳ optimize tables

---

## 📊 System Metrics

### Detection Performance
- **YOLOv11n:** ~50-100 FPS (GPU), ~5-15 FPS (CPU)
- **OC-SORT Tracking:** ~200 FPS
- **FastALPR:** ~30-50 FPS
- **Overall System:** ~10-30 FPS (depends on hardware)

### Accuracy
- **Vehicle Detection:** >95%
- **License Plate Detection:** >90%
- **Plate Recognition:** >85% (Vietnamese plates)
- **Speed Calculation:** ±5 km/h

---

## 🤝 Contributing

Contributions are welcome! Please follow these steps:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

---

## 📝 Changelog

### Version 2.0.0 (2024-12-15)
- ✅ Implemented 6-thread architecture for better performance
- ✅ Added anti-duplicate violation system (10s cooldown)
- ✅ Improved UI/UX with professional design
- ✅ Added Docker and Docker Compose support
- ✅ Enhanced database schema with proper indexes
- ✅ Fixed video stream display issues
- ✅ Optimized ALPR processing pipeline

### Version 1.0.0 (2024-11-01)
- 🎉 Initial release
- ✅ Basic vehicle detection and tracking
- ✅ License plate recognition
- ✅ Speed violation detection
- ✅ MySQL database integration
- ✅ Telegram notifications

---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## 👨‍💻 Tác giả

**Lê Hoàng Phúc**
- MSSV: 190501014
- Trường: Đại học Bình Dương - Phân hiệu Cà Mau
- Email: lehoangphuc2310@gmail.com
- GitHub: [@LeHoangPhuc2310](https://github.com/LeHoangPhuc2310)

---

## 🙏 Acknowledgments

- [Ultralytics YOLOv11](https://github.com/ultralytics/ultralytics) - Object detection
- [OC-SORT](https://github.com/noahcao/OC_SORT) - Multi-object tracking
- [FastALPR](https://github.com/ankandrew/fast-alpr) - License plate recognition
- [Flask](https://flask.palletsprojects.com/) - Web framework
- [Bootstrap](https://getbootstrap.com/) - UI framework

---

## 📞 Support

Nếu bạn gặp vấn đề hoặc có câu hỏi, vui lòng:
- Mở [Issue](https://github.com/LeHoangPhuc2310/plate_violation_system/issues) trên GitHub
- Email: lehoangphuc2310@gmail.com

---

<div align="center">

**⭐ Nếu project này hữu ích, hãy cho một star nhé! ⭐**

Made with ❤️ by Lê Hoàng Phúc

</div>




