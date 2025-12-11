# 🚗 Hệ thống nhận diện biển số & tính toán tốc độ

Hệ thống AI nhận diện biển số xe và tính toán tốc độ vi phạm giao thông sử dụng YOLO, Fast-ALPR, và Telegram notifications.

## ✨ Tính năng

- 🎯 **Nhận diện xe tự động**: YOLOv11n phát hiện các loại xe (ô tô, xe máy, xe tải, xe bus)
- 🔢 **Tính toán tốc độ**: Theo dõi và tính tốc độ xe trong thời gian thực
- 🏷️ **Nhận diện biển số**: Fast-ALPR đọc biển số xe Việt Nam
- 📱 **Thông báo Telegram**: Tự động gửi thông tin vi phạm qua Telegram
- 📊 **Dashboard Web**: Giao diện web quản lý và xem vi phạm
- 🎥 **Xử lý video**: Hỗ trợ camera trực tiếp và upload video
- ⚡ **Tối ưu hiệu suất**: 4 thread độc lập, không block video stream

## 🏗️ Kiến trúc

### 4 Thread độc lập:
1. **Video Thread**: Đọc video với tốc độ gốc, không chờ detection
2. **Detection Thread**: YOLO + OC-SORT tracking + tính tốc độ + Fast-ALPR
3. **Violation Thread**: Crop xe/biển số, lưu DB, queue Telegram
4. **Telegram Thread**: Gửi thông báo tuần tự, tránh spam API

### 2 Luồng Stream:
1. **Admin Stream**: Video có bounding box và thông tin tốc độ
2. **User Stream**: Video/ảnh sạch (không bbox) cho vi phạm

## 📋 Yêu cầu

- Python 3.10+
- CUDA 11.8+ (khuyến nghị cho GPU)
- MySQL 8.0+
- Telegram Bot Token

## 🚀 Cài đặt

### 1. Clone repository

```bash
git clone https://github.com/LeHoangPhuc2310/plate_violation_system.git
cd plate_violation_system
```

### 2. Cài đặt dependencies

```bash
pip install -r requirements.txt
```

### 3. Cấu hình

Tạo file `.env` từ `.env.example`:

```bash
cp .env.example .env
```

Điền thông tin vào `.env`:
```env
MYSQL_HOST=localhost
MYSQL_USER=root
MYSQL_PASSWORD=your-password
MYSQL_DB=plate_violation
SECRET_KEY=your-secret-key
TELEGRAM_TOKEN=your-telegram-bot-token
TELEGRAM_CHAT_ID=your-chat-id
```

### 4. Tạo database

```sql
CREATE DATABASE plate_violation;
```

Tạo các bảng (xem schema trong code hoặc migrations).

### 5. Chạy ứng dụng

```bash
python app.py
```

Truy cập: `http://localhost:5000`

## 🌐 Deploy lên AWS

Xem hướng dẫn chi tiết trong [README_AWS.md](README_AWS.md)

### Quick Start với EC2:

1. Launch EC2 instance (g4dn.xlarge hoặc lớn hơn, có GPU)
2. SSH vào instance
3. Clone repo và chạy:
```bash
git clone https://github.com/LeHoangPhuc2310/plate_violation_system.git
cd plate_violation_system
chmod +x ec2-setup.sh
./ec2-setup.sh
```

## 📁 Cấu trúc Project

```
plate_violation_system/
├── app.py                      # Flask application chính
├── combined_detector.py        # YOLO + Tracking detector
├── detector.py                 # Fast-ALPR plate detector
├── speed_tracker.py            # Tính toán tốc độ
├── enhanced_plate_detector.py  # Enhanced plate detection (optional)
├── oc_sort.py                  # OC-SORT tracking
├── byte_tracker.py             # ByteTrack tracking (fallback)
├── requirements.txt            # Python dependencies
├── Dockerfile                  # Docker image cho AWS
├── deploy.sh                   # Script deploy tự động
├── ec2-setup.sh                # Script setup EC2
├── README_AWS.md               # Hướng dẫn deploy AWS
├── templates/                  # HTML templates
│   ├── base.html
│   ├── index.html
│   ├── login.html
│   └── ...
└── static/                     # Static files
    ├── img/
    ├── uploads/
    └── plate_images/
```

## 🔧 Cấu hình

### Environment Variables

- `MYSQL_HOST`: MySQL host
- `MYSQL_USER`: MySQL username
- `MYSQL_PASSWORD`: MySQL password
- `MYSQL_DB`: Database name
- `SECRET_KEY`: Flask secret key
- `TELEGRAM_TOKEN`: Telegram bot token
- `TELEGRAM_CHAT_ID`: Telegram chat ID
- `HOST`: Flask host (default: 0.0.0.0)
- `PORT`: Flask port (default: 5000)
- `FLASK_DEBUG`: Debug mode (default: False)

## 📝 License

MIT License

## 👤 Author

**Lê Hoàng Phúc** - MSSV: 190501014

Trường Đại Học Bình Dương - Phân Hiệu Cà Mau

## 🙏 Acknowledgments

- YOLO: [Ultralytics](https://github.com/ultralytics/ultralytics)
- Fast-ALPR: License plate recognition
- Flask: Web framework
- OpenCV: Computer vision

## 📞 Support

Nếu có vấn đề, vui lòng tạo [Issue](https://github.com/LeHoangPhuc2310/plate_violation_system/issues) trên GitHub.

