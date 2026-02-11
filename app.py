"""
Điểm khởi tạo ứng dụng Flask chính.
Khởi tạo Flask app, cấu hình, đăng ký routes và các module phát hiện.
"""

import os
from flask import Flask

# Thiết lập logging trước
from utils.logger import get_logger, setup_logging
from config.config import Config
from utils.helpers import format_plate, format_time_vietnam

# Thiết lập hệ thống logging
setup_logging()
logger = get_logger(__name__)

# Khởi tạo Flask app
app = Flask(__name__)
app.config.from_object(Config)
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024

# Đăng ký template filters
app.jinja_env.filters['format_plate'] = format_plate
app.jinja_env.filters['format_time_vietnam'] = format_time_vietnam

# Tạo các thư mục cần thiết
os.makedirs(Config.UPLOAD_FOLDER, exist_ok=True)
os.makedirs(Config.VIOLATION_FOLDER, exist_ok=True)

# Khởi tạo database
from database import DatabaseHandler
db = DatabaseHandler()
db.init_app(app)

# Khởi tạo Telegram notifier
from telegram import TelegramNotifier
telegram = TelegramNotifier(
    Config.TELEGRAM_BOT_TOKEN,
    Config.TELEGRAM_CHAT_ID
)

# Module phát hiện toàn cục (khởi tạo lazy)
detector = None
tracker = None
speed_calc = None
alpr = None
violation_handler = None
processor = None


def init_detection_modules():
    """Khởi tạo các module phát hiện (YOLO, tracker, speed calculator, ALPR, ...)."""
    global detector, tracker, speed_calc, alpr, violation_handler, processor

    if processor is not None:
        return

    logger.info("Loading detection modules...")

    from detector import YOLODetector
    from tracker import ByteTracker
    from speed import SpeedCalculator
    from alpr import PlateReader
    from violation import ViolationHandler
    from video_processor import VideoProcessor

    detector = YOLODetector(
        model_path=Config.YOLO_MODEL,
        device=Config.DEVICE,
        conf_thresh=Config.CONF_THRESH
    )

    tracker = ByteTracker(
        max_age=30,
        min_hits=3,
        iou_threshold=0.6
    )

    speed_calc = SpeedCalculator(
        line1_y=Config.LINE1_Y,
        line2_y=Config.LINE2_Y,
        real_distance_meters=Config.REAL_DISTANCE
    )

    cuda_lock = detector.cuda_lock if hasattr(detector, 'cuda_lock') else None
    alpr = PlateReader(cuda_lock=cuda_lock)

    violation_handler = ViolationHandler(
        speed_limit=Config.SPEED_LIMIT,
        save_dir=Config.VIOLATION_FOLDER,
        cooldown_seconds=Config.VIOLATION_COOLDOWN_SECONDS,
        video_duration_seconds=Config.VIOLATION_VIDEO_DURATION_SECONDS,
        video_before_seconds=Config.VIOLATION_VIDEO_BEFORE_SECONDS,
        video_after_seconds=Config.VIOLATION_VIDEO_AFTER_SECONDS
    )

    processor = VideoProcessor(
        detector=detector,
        tracker=tracker,
        speed_calc=speed_calc,
        alpr=alpr,
        violation_handler=violation_handler,
        db_handler=db,
        telegram=telegram
    )

    logger.info("Detection modules loaded successfully")


# Khởi tạo routes
from routes.auth import init_auth_routes
from routes.main import init_main_routes
from routes.violations import init_violations_routes
from routes.admin import init_admin_routes
from routes.api import init_api_routes

# Hàm helper để lấy processor (cho routes)
def get_processor():
    return processor

init_auth_routes(app, db)
init_main_routes(app, db, get_processor, init_detection_modules)
init_violations_routes(app, db)
init_admin_routes(app, db)
init_api_routes(app, db, get_processor)

# Routes manual review được xử lý trong routes/api.py


if __name__ == '__main__':
    logger.info("=" * 60)
    logger.info("VEHICLE SPEED VIOLATION DETECTION SYSTEM")
    logger.info("=" * 60)
    logger.info(f"YOLO Model: {Config.YOLO_MODEL}")
    logger.info(f"Device: {Config.DEVICE}")
    logger.info(f"Speed Limit: {Config.SPEED_LIMIT} km/h")
    logger.info(f"Virtual Lines: Y={Config.LINE1_Y}, Y={Config.LINE2_Y}")
    logger.info(f"Real Distance: {Config.REAL_DISTANCE}m")
    logger.info("=" * 60)

    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)

