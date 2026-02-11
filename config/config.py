"""
Cấu hình ứng dụng.
Chứa tất cả cài đặt cho hệ thống phát hiện vi phạm biển số.
"""

import os
import warnings
from pathlib import Path
from dotenv import load_dotenv

# Luôn tải .env từ thư mục gốc project (tránh lỗi khi PyCharm/IDE chạy với Working directory khác)
_ROOT_DIR = Path(__file__).resolve().parent.parent
_ENV_PATH = _ROOT_DIR / ".env"
load_dotenv(_ENV_PATH)


class Config:
    """Lớp cấu hình ứng dụng."""
    
    # Flask secret key
    SECRET_KEY = os.getenv('SECRET_KEY', 'your-secret-key-here')

    # Cấu hình MySQL Database
    MYSQL_HOST = os.getenv('MYSQL_HOST', 'localhost')
    MYSQL_USER = os.getenv('MYSQL_USER', 'root')
    MYSQL_PASSWORD = os.getenv('MYSQL_PASSWORD', '')
    MYSQL_DB = os.getenv('MYSQL_DB', 'plate_violation')

    # Cấu hình Telegram Bot
    # Mặc định development (chỉ dùng khi không có .env)
    # Production: BẮT BUỘC phải set trong .env file
    TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '8306836477:AAEJSaTQg2Pu7tZQMEHjoDPUSIC3Mz0QtGY')
    TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', '6680799636')
    
    # Bảo mật: Cảnh báo nếu dùng giá trị mặc định trong production
    FLASK_ENV = os.getenv('FLASK_ENV', 'development')
    if FLASK_ENV == 'production':
        if TELEGRAM_BOT_TOKEN == '8306836477:AAEJSaTQg2Pu7tZQMEHjoDPUSIC3Mz0QtGY':
            warnings.warn(
                "SECURITY WARNING: Using default TELEGRAM_BOT_TOKEN in production! "
                "Please set TELEGRAM_BOT_TOKEN in .env file for security.",
                UserWarning
            )
        if TELEGRAM_CHAT_ID == '6680799636':
            warnings.warn(
                "SECURITY WARNING: Using default TELEGRAM_CHAT_ID in production! "
                "Please set TELEGRAM_CHAT_ID in .env file for security.",
                UserWarning
            )
        if SECRET_KEY == 'your-secret-key-here':
            warnings.warn(
                "SECURITY WARNING: Using default SECRET_KEY in production! "
                "Please set SECRET_KEY in .env file for security.",
                UserWarning
            )

    # Cấu hình YOLO Model
    YOLO_MODEL = 'yolo11m.pt'
    DEVICE = 'cuda'
    CONF_THRESH = 0.5

    # Cấu hình phát hiện tốc độ
    SPEED_LIMIT = 30  # Tốc độ tối đa cho phép: 30 km/h
    LINE1_Y = 1000  # LINE1 gần đáy frame để xe vào zone ngay khi xuất hiện
    LINE2_Y = 450
    REAL_DISTANCE = 30  # Khoảng cách thực tế giữa LINE1 và LINE2 (mét)

    # Cấu hình upload file
    UPLOAD_FOLDER = 'uploads'
    VIOLATION_FOLDER = 'uploads/violations'
    
    # Cài đặt phát hiện vi phạm
    VIOLATION_COOLDOWN_SECONDS = float(os.getenv('VIOLATION_COOLDOWN_SECONDS', '5.0'))
    VIOLATION_VIDEO_DURATION_SECONDS = float(os.getenv('VIOLATION_VIDEO_DURATION_SECONDS', '4.0'))
    VIOLATION_VIDEO_BEFORE_SECONDS = float(os.getenv('VIOLATION_VIDEO_BEFORE_SECONDS', '1.5'))
    VIOLATION_VIDEO_AFTER_SECONDS = float(os.getenv('VIOLATION_VIDEO_AFTER_SECONDS', '2.5'))

