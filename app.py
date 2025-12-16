from flask import Flask, Response, render_template, request, jsonify, redirect, session, url_for, send_from_directory, make_response
from flask_mysqldb import MySQL  # pyright: ignore[reportMissingImports]
import cv2
import numpy as np
import time
import json
import os
import re
import requests
import threading
from collections import deque, Counter
import queue
from datetime import datetime, timezone, timedelta

from combined_detector import CombinedDetector
from speed_tracker import SpeedTracker
from detector import PlateDetector
from video_reader import OfflineVideoReader
from violation_saver import save_violation_evidence

# Thử import Enhanced Plate Detector (có fallback)
try:
    from enhanced_plate_detector import EnhancedPlateDetector
    ENHANCED_DETECTOR_AVAILABLE = True
except ImportError:
    ENHANCED_DETECTOR_AVAILABLE = False
    print(">>> ⚠️ Enhanced Plate Detector not available - using standard PlateDetector")

VIETNAM_TZ = timezone(timedelta(hours=7))

def get_vietnam_time():
    """Trả về thời gian hiện tại theo múi giờ Vietnam (UTC+7)"""
    return datetime.now(VIETNAM_TZ)

def format_vietnam_time(dt=None):
    """Format thời gian theo định dạng Vietnam"""
    if dt is None:
        dt = get_vietnam_time()
    elif isinstance(dt, str):
        # Nếu là string từ database, parse và convert
        try:
            dt = datetime.strptime(dt, '%Y-%m-%d %H:%M:%S')
            dt = dt.replace(tzinfo=timezone.utc).astimezone(VIETNAM_TZ)
        except:
            return dt
    elif isinstance(dt, datetime):
        if dt.tzinfo is None:
            # Nếu không có timezone, giả sử là UTC
            dt = dt.replace(tzinfo=timezone.utc).astimezone(VIETNAM_TZ)
        else:
            dt = dt.astimezone(VIETNAM_TZ)
    return dt.strftime('%d/%m/%Y %H:%M:%S')

app = Flask(__name__)
app.secret_key = "your-secret-key-123"

# Tắt Werkzeug logging để giảm terminal noise
import logging
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)  # Chỉ hiện ERROR, không hiện 404/200 requests

app.config['MYSQL_HOST'] = os.getenv('MYSQL_HOST', 'localhost')
app.config['MYSQL_USER'] = os.getenv('MYSQL_USER', 'root')
app.config['MYSQL_PASSWORD'] = os.getenv('MYSQL_PASSWORD', '')
app.config['MYSQL_DB'] = os.getenv('MYSQL_DB', 'plate_violation')
app.config['MYSQL_CURSORCLASS'] = 'DictCursor'
app.config['MYSQL_CONNECT_TIMEOUT'] = 5
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024

mysql = MySQL(app)

def test_db_connection_async():
    """Test database connection trong thread riêng để không block startup"""
    time.sleep(1)  # Đợi 1 giây để app khởi động xong
    try:
        with app.app_context():
            conn = mysql.connection
            if conn:
                cursor = conn.cursor()
                cursor.execute("SELECT 1")
                cursor.close()
                print(f"✅ Database connected: {app.config['MYSQL_HOST']}/{app.config['MYSQL_DB']}")
            else:
                print(f"⚠️  Database connection failed: No connection object")
    except Exception as e:
        print(f"⚠️  Database connection warning: {e}")
        print(f"   Host: {app.config['MYSQL_HOST']}")
        print(f"   User: {app.config['MYSQL_USER']}")
        print(f"   Database: {app.config['MYSQL_DB']}")
        print("   App will continue but database features may not work")

db_test_thread = threading.Thread(target=test_db_connection_async, daemon=True)
db_test_thread.start()
UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs("static/uploads", exist_ok=True)
os.makedirs("static/plate_images", exist_ok=True)
os.makedirs("static/violation_videos", exist_ok=True)

cap = None
current_video_path = None
camera_running = False
last_id = 0
video_fps = 30
is_video_upload_mode = False
cap_lock = threading.Lock()

last_violation_time = {}
VIOLATION_COOLDOWN = 5  # Tăng lên 15 giây để tránh trùng vi phạm

# Track active vehicles to buffer frames
active_tracks = {}  # track_id -> last_seen_time
active_tracks_lock = threading.Lock()
TRACK_TIMEOUT = 10.0  # Remove tracks không thấy sau 10s

def can_save_violation(track_id, plate=None):
    """
    Kiểm tra có thể lưu vi phạm cho track_id này không
    Sử dụng plate làm key chính để tránh trùng vi phạm cho cùng một biển số
    """
    current_time = time.time()

    # Ưu tiên dùng plate làm key (cùng biển số = cùng xe)
    if plate:
        plate_normalized = normalize_plate(plate) if plate else None
        if plate_normalized:
            cooldown_key = f"plate_{plate_normalized}"
        else:
            cooldown_key = f"track_{track_id}"
    else:
        cooldown_key = f"track_{track_id}"

    if cooldown_key not in last_violation_time:
        last_violation_time[cooldown_key] = current_time
        return True

    time_since_last = current_time - last_violation_time[cooldown_key]
    if time_since_last >= VIOLATION_COOLDOWN:
        last_violation_time[cooldown_key] = current_time
        return True
    else:
        print(f"[ANTI-DUPLICATE] ⏳ {'Biển số ' + plate if plate else 'Track ' + str(track_id)} đã vi phạm {time_since_last:.1f}s trước, bỏ qua (cooldown: {VIOLATION_COOLDOWN}s)")
        return False
def calculate_blur_score(image):
    """Tính blur score bằng Laplacian variance"""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return cv2.Laplacian(gray, cv2.CV_64F).var()

def apply_clahe(image):
    """Apply CLAHE"""
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    l = clahe.apply(l)
    enhanced = cv2.merge([l, a, b])
    return cv2.cvtColor(enhanced, cv2.COLOR_LAB2BGR)

def sharpen_image(image):
    """Sharpen image"""
    gaussian = cv2.GaussianBlur(image, (0, 0), 2.0)
    return cv2.addWeighted(image, 1.5, gaussian, -0.5, 0)

def denoise_image(image):
    """Denoise image"""
    return cv2.fastNlMeansDenoisingColored(image, None, 10, 10, 7, 21)

def is_valid_vietnamese_plate(plate_text):
    """Validate Vietnamese plate format"""
    normalized = normalize_plate(plate_text)
    if len(normalized) < 7 or len(normalized) > 10:
        return False
    patterns = [
        r'^[0-9]{2}[A-Z]{1}[0-9]{4,5}$',
        r'^[0-9]{2}[A-Z]{2}[0-9]{4,5}$',
    ]
    for pattern in patterns:
        if re.match(pattern, normalized):
            return True
    return False

def select_best_frame(frames, bbox, weights={'blur': 0.4, 'size': 0.3, 'position': 0.3}):
    """Chọn frame tốt nhất dựa trên blur, size, position"""
    if not frames:
        return None

    x1, y1, x2, y2 = bbox
    scores = []

    for frame in frames:
        try:
            crop = frame[int(y1):int(y2), int(x1):int(x2)]
            if crop.size == 0:
                continue

            blur_score = calculate_blur_score(crop)
            size_score = (x2 - x1) * (y2 - y1)

            center_x = (x1 + x2) / 2
            center_y = (y1 + y2) / 2
            frame_center_x = frame.shape[1] / 2
            frame_center_y = frame.shape[0] / 2
            dist = ((center_x - frame_center_x)**2 + (center_y - frame_center_y)**2)**0.5
            position_score = 1.0 / (1.0 + dist / 100)

            total = (
                blur_score * weights['blur'] +
                size_score * weights['size'] +
                position_score * weights['position']
            )
            scores.append((total, frame))
        except Exception as e:
            continue

    if not scores:
        return frames[0] if frames else None

    return max(scores, key=lambda x: x[0])[1]

def ensemble_plate_results(results, min_confidence=0.7, min_votes=2):
    """Voting mechanism cho ALPR results"""
    if not results:
        return None

    votes = Counter()
    confidence_map = {}

    for r in results:
        if not r or 'text' not in r:
            continue

        normalized = normalize_plate(r['text'])
        if not normalized:
            continue

        votes[normalized] += 1

        if normalized not in confidence_map:
            confidence_map[normalized] = []
        confidence_map[normalized].append(r.get('confidence', 0))

    if not votes:
        return None

    best_plate, vote_count = votes.most_common(1)[0]

    if vote_count < min_votes:
        return None

    avg_confidence = sum(confidence_map[best_plate]) / len(confidence_map[best_plate])
    if avg_confidence < min_confidence:
        return None

    return {
        'text': best_plate,
        'confidence': avg_confidence,
        'votes': vote_count
    }

# GPU Detection and Device Configuration
try:
    import torch
    if torch.cuda.is_available():
        DEVICE = 'cuda'
        gpu_name = torch.cuda.get_device_name(0)
        gpu_memory = torch.cuda.get_device_properties(0).total_memory / 1024**3
        print(f"🚀 GPU CUDA detected: {gpu_name} ({gpu_memory:.1f} GB)")
        print(f"🚀 CUDA Version: {torch.version.cuda}")
        try:
            if hasattr(torch.backends, 'cudnn') and hasattr(torch.backends.cudnn, 'version'):
                print(f"🚀 cuDNN Version: {torch.backends.cudnn.version()}")
            else:
                print(f"🚀 cuDNN: Available (version check not supported)")
        except Exception as e:
            print(f"🚀 cuDNN: Available (version: {e})")
        DETECTION_FREQUENCY = 1
        DETECTION_SCALE = 1.0
    elif hasattr(torch.backends, 'mps') and torch.backends.mps.is_available():
        DEVICE = 'mps'
        print("🚀 GPU MPS (Apple Silicon) detected")
        DETECTION_FREQUENCY = 1
        DETECTION_SCALE = 0.8
    else:
        DEVICE = 'cpu'
        print("⚠️  WARNING: No GPU detected! System will run on CPU (SLOW performance)")
        DETECTION_FREQUENCY = 1
        DETECTION_SCALE = 0.7
except ImportError as e:
    print(f"⚠️  WARNING: PyTorch is not installed! Please install: pip install torch torchvision")
    print(f"    Error: {e}")
    print("⚠️  System will attempt to run without PyTorch (may cause errors)")
    DEVICE = 'cpu'
    DETECTION_FREQUENCY = 1
    DETECTION_SCALE = 0.7
except Exception as e:
    print(f"⚠️  WARNING: Error detecting GPU: {e}")
    print("⚠️  System will run on CPU (SLOW performance)")
    DEVICE = 'cpu'
    DETECTION_FREQUENCY = 1
    DETECTION_SCALE = 0.7

detector = None
tracker = None
plate_detector_post = None
speed_limit = 40

# ============================================================================
# FFMPEG VIDEO HELPER FUNCTIONS
# ============================================================================

def check_ffmpeg_available():
    """Check if FFmpeg is installed"""
    try:
        import subprocess
        result = subprocess.run(
            ['ffmpeg', '-version'],
            capture_output=True,
            timeout=5
        )
        if result.returncode == 0:
            version = result.stdout.decode().split('\n')[0]
            print(f"✅ FFmpeg available: {version}")
            return True
        return False
    except:
        print("⚠️  FFmpeg not found - will use OpenCV fallback")
        print("   Install: choco install ffmpeg (Windows) or apt install ffmpeg (Linux)")
        return False

def create_video_with_ffmpeg(
    source_video_path,
    output_path,
    start_time,
    duration=5.0
):
    """
    Tạo video vi phạm bằng FFmpeg (direct copy stream - FAST & PERFECT)

    Args:
        source_video_path: Đường dẫn video gốc
        output_path: Đường dẫn video output
        start_time: Thời điểm bắt đầu (seconds)
        duration: Độ dài video (seconds, default=5.0)

    Returns:
        (success: bool, message: str)
    """
    import subprocess

    # Validate inputs
    if not os.path.exists(source_video_path):
        return False, f"Source video not found: {source_video_path}"

    # Ensure output directory exists
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # Build FFmpeg command
    cmd = [
        'ffmpeg',
        '-ss', str(start_time),              # Seek to start time (BEFORE -i for speed)
        '-i', source_video_path,             # Input file
        '-t', str(duration),                 # Duration
        '-c', 'copy',                        # Copy codec (no re-encoding, fast!)
        '-avoid_negative_ts', 'make_zero',   # Fix timestamp issues
        '-y',                                 # Overwrite output
        output_path
    ]

    try:
        print(f"[FFMPEG] 🎬 Creating video:")
        print(f"   - Source: {os.path.basename(source_video_path)}")
        print(f"   - Start: {start_time:.2f}s")
        print(f"   - Duration: {duration}s")
        print(f"   - Output: {os.path.basename(output_path)}")

        # Run FFmpeg (timeout 30s)
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30
        )

        if result.returncode == 0:
            # Verify output file
            if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                file_size = os.path.getsize(output_path) / 1024  # KB
                print(f"[FFMPEG] ✅ Video created: {file_size:.1f} KB")
                return True, f"Success: {file_size:.1f} KB"
            else:
                return False, "Output file empty or not created"
        else:
            error_msg = result.stderr.strip().split('\n')[-1] if result.stderr else "Unknown error"
            print(f"[FFMPEG] ❌ FFmpeg failed: {error_msg}")
            return False, f"FFmpeg error: {error_msg}"

    except subprocess.TimeoutExpired:
        return False, "FFmpeg timeout (>30s)"
    except FileNotFoundError:
        return False, "FFmpeg not found - please install: choco install ffmpeg"
    except Exception as e:
        return False, f"Exception: {str(e)}"

# Check FFmpeg availability on startup
FFMPEG_AVAILABLE = check_ffmpeg_available()

# ============================================================================

def init_detector():
    """Khởi tạo detector - lazy load"""
    global detector, tracker, plate_detector_post
    if detector is None:
        print(">>> Loading CombinedDetector (YOLOv11n)...")
        try:
            detector = CombinedDetector(yolo_model='yolo11n.pt', device=DEVICE)
            print(">>> ✅ CombinedDetector loaded!")
        except Exception as e:
            print(f">>> ❌ CombinedDetector failed: {e}")
            detector = None

    if tracker is None:
        tracker = SpeedTracker(pixel_to_meter=0.13)
        print(">>> ✅ SpeedTracker initialized!")

    if plate_detector_post is None:
        if ENHANCED_DETECTOR_AVAILABLE:
            print(">>> Loading Enhanced Plate Detector for post-processing...")
            try:
                plate_detector_post = EnhancedPlateDetector()
                print(">>> ✅ Enhanced Plate Detector loaded! (Fast-ALPR + EasyOCR fallback)")
            except Exception as e:
                print(f">>> ⚠️ Enhanced Plate Detector failed: {e}, using standard PlateDetector")
                try:
                    plate_detector_post = PlateDetector(device=DEVICE)
                    print(">>> ✅ Standard Fast-ALPR PlateDetector loaded!")
                except Exception as e2:
                    print(f">>> ⚠️ Standard PlateDetector also failed: {e2}")
                    plate_detector_post = None
                    print(">>> ⚠️ Plate detection will be disabled for post-processing")
        else:
            print(">>> Loading Fast-ALPR PlateDetector for post-processing...")
            try:
                plate_detector_post = PlateDetector(device=DEVICE)
                print(">>> ✅ Fast-ALPR PlateDetector loaded!")
            except Exception as e:
                print(f">>> ⚠️ PlateDetector failed: {e}")
                plate_detector_post = None
                print(">>> ⚠️ Plate detection will be disabled for post-processing")

TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN', '8306836477:AAEJSaTQg2Pu7tZQMEHjoDPUSIC3Mz0QtGY')
TELEGRAM_CHAT_ID = int(os.getenv('TELEGRAM_CHAT_ID', '6680799636'))

telegram_queue = queue.Queue()
telegram_worker_running = False
telegram_worker_thread = None
def telegram_worker():
    """THREAD 6: Telegram Worker Thread - Gửi thông báo tuần tự"""
    global telegram_worker_running, speed_limit
    telegram_worker_running = True
    print("[TELEGRAM THREAD] ✅ Worker thread đã khởi động - sẵn sàng xử lý hàng đợi")

    while telegram_worker_running:
        try:
            # Lấy vi phạm từ queue (blocking, đợi đến khi có)
            violation_data = telegram_queue.get(timeout=1)

            if violation_data is None:  # Signal để dừng
                break

            full_img_path = violation_data.get('vehicle_image_path') or violation_data.get('full_img_path')
            plate_img_path = violation_data.get('plate_image_path') or violation_data.get('plate_img_path')
            video_path = violation_data.get('video_path')
            print(f"[TELEGRAM THREAD] 📤 Đang gửi vi phạm: {violation_data.get('plate', 'N/A')} (Còn {telegram_queue.qsize()} trong hàng đợi)")
            send_telegram_alert(
                plate=violation_data.get('plate'),
                speed=violation_data.get('speed', 0),
                limit=violation_data.get('limit', speed_limit),
                full_img_path=full_img_path,
                plate_img_path=plate_img_path,
                video_path=video_path,  # Video clean, không có bbox
                owner_name=violation_data.get('owner_name'),
                address=violation_data.get('address'),
                phone=violation_data.get('phone'),
                vehicle_class=violation_data.get('vehicle_type') or violation_data.get('vehicle_class', 'N/A'),
                violation_id=violation_data.get('violation_id')
            )
            print(f"[TELEGRAM THREAD] ✅ Đã gửi xong vi phạm: {violation_data.get('plate', 'N/A')}")

            telegram_queue.task_done()
            time.sleep(0.5)

        except queue.Empty:
            # Timeout - tiếp tục vòng lặp
            continue
        except Exception as e:
            print(f"[TELEGRAM THREAD ERROR] {e}")
            import traceback
            traceback.print_exc()
            # Đánh dấu task đã hoàn thành ngay cả khi lỗi
            try:
                telegram_queue.task_done()
            except:
                pass

    print("[TELEGRAM THREAD] ⏹️ Worker thread đã dừng")

def start_telegram_worker():
    """Khởi động Telegram worker thread"""
    global telegram_worker_thread, telegram_worker_running

    if telegram_worker_thread is None or not telegram_worker_thread.is_alive():
        telegram_worker_thread = threading.Thread(target=telegram_worker, daemon=True)
        telegram_worker_thread.start()
        print("[TELEGRAM QUEUE] 🚀 Đã khởi động Telegram worker thread")

def queue_telegram_alert(plate, speed, limit, full_img_path, plate_img_path, video_path, owner_name, address, phone, vehicle_class="N/A", violation_id=None):
    """Thêm vi phạm vào hàng đợi Telegram"""
    start_telegram_worker()
    violation_data = {
        'plate': plate,
        'speed': speed,
        'limit': limit,
        'full_img_path': full_img_path,
        'plate_img_path': plate_img_path,
        'video_path': video_path,
        'owner_name': owner_name,
        'address': address,
        'phone': phone,
        'vehicle_class': vehicle_class,
        'violation_id': violation_id
    }

    telegram_queue.put(violation_data)
    print(f"[TELEGRAM QUEUE] ➕ Đã thêm vi phạm vào hàng đợi: {plate} (Tổng: {telegram_queue.qsize()} vi phạm đang chờ)")

def admin_required(f):
    def wrapper(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("login"))

        if session.get("role") != "admin":
            session["alert_message"] = "Bạn không có quyền truy cập!"
            return redirect(url_for("history"))

        return f(*args, **kwargs)

    wrapper.__name__ = f.__name__
    return wrapper


def require_role(role):
    def decorator(f):
        def wrapper(*args, **kwargs):
            if "user" not in session:
                return jsonify({"error": "not_login"}), 401

            if session.get("role") != role:
                return jsonify({"error": "no_permission"}), 403

            return f(*args, **kwargs)

        wrapper.__name__ = f.__name__
        return wrapper

    return decorator


# ======================
# AUTH DECORATORS
# ======================

def login_required(f):
    def wrapper(*args, **kwargs):
        # chưa đăng nhập thì trả về trang login + thông báo nhẹ ở UI
        if "user" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    wrapper.__name__ = f.__name__
    return wrapper







# FUNCTIONS
# ======================
def update_telegram_status(violation_id, status):
    """
    Cập nhật trạng thái gửi Telegram cho violation
    status: 'pending', 'sent', 'failed'
    """
    try:
        with app.app_context():
            conn = mysql.connection
            cursor = conn.cursor()
            cursor.execute("UPDATE violations SET status=%s WHERE id=%s", (status, violation_id))
            conn.commit()
            print(f"[DB] ✅ Đã cập nhật status violation ID {violation_id} thành '{status}'")
    except Exception as e:
        print(f"[ERROR] Update status failed: {e}")

def send_telegram_alert(plate, speed, limit, full_img_path, plate_img_path, video_path, owner_name, address, phone, vehicle_class="N/A", violation_id=None):
    """Gửi cảnh báo vi phạm qua Telegram"""
    try:
        if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
            print("[TELEGRAM] Token hoặc Chat ID chưa được cấu hình")
            if violation_id:
                update_telegram_status(violation_id, 'failed')
            return

        if not plate:
            print("[TELEGRAM] ❌ Biển số không được để trống!")
            if full_img_path and os.path.exists(full_img_path):
                try:
                    os.remove(full_img_path)
                    print(f"[TELEGRAM] 🗑️ Đã xóa ảnh xe vì không có biển số: {full_img_path}")
                except Exception as e:
                    print(f"[TELEGRAM] Lỗi xóa ảnh xe: {e}")
            if plate_img_path and os.path.exists(plate_img_path):
                try:
                    os.remove(plate_img_path)
                    print(f"[TELEGRAM] 🗑️ Đã xóa ảnh biển số vì không có biển số: {plate_img_path}")
                except Exception as e:
                    print(f"[TELEGRAM] Lỗi xóa ảnh biển số: {e}")
            if violation_id:
                update_telegram_status(violation_id, 'failed')
            return

        normalized_plate = normalize_plate(plate)
        if not is_valid_plate(normalized_plate):
            print(f"[TELEGRAM] ❌ Biển số không hợp lệ '{plate}' (normalized: {normalized_plate})")
            if full_img_path and os.path.exists(full_img_path):
                try:
                    os.remove(full_img_path)
                    print(f"[TELEGRAM] 🗑️ Đã xóa ảnh xe vì biển số không hợp lệ: {full_img_path}")
                except Exception as e:
                    print(f"[TELEGRAM] Lỗi xóa ảnh xe: {e}")
            if plate_img_path and os.path.exists(plate_img_path):
                try:
                    os.remove(plate_img_path)
                    print(f"[TELEGRAM] 🗑️ Đã xóa ảnh biển số vì biển số không hợp lệ: {plate_img_path}")
                except Exception as e:
                    print(f"[TELEGRAM] Lỗi xóa ảnh biển số: {e}")
            if violation_id:
                update_telegram_status(violation_id, 'failed')
            return

        plate = normalized_plate

        if not full_img_path or not os.path.exists(full_img_path):
            print(f"[TELEGRAM] ❌ Ảnh vi phạm xe không tồn tại: {full_img_path}")
            if plate_img_path and os.path.exists(plate_img_path):
                try:
                    os.remove(plate_img_path)
                    print(f"[TELEGRAM] 🗑️ Đã xóa ảnh biển số vì không có ảnh xe: {plate_img_path}")
                except Exception as e:
                    print(f"[TELEGRAM] Lỗi xóa ảnh biển số: {e}")
            if violation_id:
                update_telegram_status(violation_id, 'failed')
            return

        if not owner_name:
            owner_name = "Chưa có thông tin"
        if not address:
            address = "Chưa có thông tin"
        if not phone:
            phone = "Chưa có thông tin"

        send_success = True

        if not full_img_path or not os.path.exists(full_img_path):
            full_img_path = None
        else:
            full_img_path = os.path.abspath(full_img_path)

        if not plate_img_path or not os.path.exists(plate_img_path):
            plate_img_path = None
        else:
            plate_img_path = os.path.abspath(plate_img_path)

        if not video_path or not os.path.exists(video_path):
            video_path = None
        else:
            video_path = os.path.abspath(video_path)

        vehicle_type_map = {
            'car': 'Ô TÔ',
            'motorcycle': 'XE GẮN MÁY',
            'bus': 'XE BUS',
            'truck': 'XE TẢI'
        }
        vehicle_type_display = vehicle_type_map.get(vehicle_class.lower(), vehicle_class.upper())
        exceeded = round(speed - limit, 2)

        message = (
            f"🚨 *CẢNH BÁO VI PHẠM TỐC ĐỘ!*\n\n"
            f"🔰 *Biển số:* `{plate}`\n"
            f"🚗 *Loại xe:* {vehicle_type_display}\n\n"
            f"👤 *Chủ xe:* {owner_name}\n"
            f"🏠 *Địa chỉ:* {address}\n"
            f"📞 *SĐT:* {phone}\n\n"
            f"⚡ *Tốc độ ghi nhận:* `{round(speed, 2)} km/h`\n"
            f"🔻 *Giới hạn:* `{limit} km/h`\n"
            f"📊 *Vượt quá:* `{exceeded} km/h`\n\n"
            f"⏰ *Thời gian:* {format_vietnam_time()}"
        )

        try:
            response = requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                data={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"},
                timeout=10
            )
            if response.status_code != 200:
                print(f"[TELEGRAM] Message send failed: {response.text}")
                send_success = False
        except Exception as e:
            print(f"[TELEGRAM] Message send error: {e}")
            send_success = False

        try:
            with open(full_img_path, "rb") as imgf:
                caption = (
                    f"🚗 Ảnh phương tiện vi phạm\n"
                    f"Biển số: {plate}\n"
                    f"Loại xe: {vehicle_type_display}\n"
                    f"Tốc độ: {round(speed, 2)} km/h (Giới hạn: {limit} km/h)"
                )
                response = requests.post(
                    f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto",
                    files={"photo": imgf},
                    data={"chat_id": TELEGRAM_CHAT_ID, "caption": caption},
                    timeout=20
                )
                if response.status_code != 200:
                    print(f"[TELEGRAM] ❌ Ảnh vi phạm xe gửi thất bại: {response.text}")
                    send_success = False
                else:
                    print(f"[TELEGRAM] ✅ Đã gửi ảnh phương tiện vi phạm (BẮT BUỘC)")
        except Exception as e:
            print(f"[TELEGRAM] ❌ Lỗi gửi ảnh vi phạm xe: {e}")
            send_success = False

        if plate_img_path:
            try:
                with open(plate_img_path, "rb") as imgf:
                    caption = (
                        f"🔰 Ảnh biển số đã crop\n"
                        f"Biển số: {plate}"
                    )
                    response = requests.post(
                        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto",
                        files={"photo": imgf},
                        data={"chat_id": TELEGRAM_CHAT_ID, "caption": caption},
                        timeout=20
                    )
                    if response.status_code != 200:
                        print(f"[TELEGRAM] Plate image send failed: {response.text}")
                        send_success = False
                    else:
                        print(f"[TELEGRAM] ✓ Đã gửi ảnh biển số đã crop")
            except Exception as e:
                print(f"[TELEGRAM] Plate image send error: {e}")
                send_success = False

        if video_path:
            try:
                file_size = os.path.getsize(video_path)
                if file_size > 50 * 1024 * 1024:  # 50MB
                    print(f"[TELEGRAM] Video quá lớn ({file_size / 1024 / 1024:.2f}MB), bỏ qua")
                else:
                    with open(video_path, "rb") as vf:
                        caption = (
                            f"🎥 Video vi phạm 5s (từ camera gốc)\n"
                            f"Biển số: {plate}\n"
                            f"Loại xe: {vehicle_type_display}\n"
                            f"Tốc độ: {round(speed, 2)} km/h (Vượt quá: {exceeded} km/h)\n"
                            f"⏱️ Nội dung: 2s trước + 3s sau vi phạm"
                        )
                        response = requests.post(
                            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendVideo",
                            files={"video": vf},
                            data={"chat_id": TELEGRAM_CHAT_ID, "caption": caption},
                            timeout=60  # Tăng timeout cho video lớn
                        )
                        if response.status_code != 200:
                            print(f"[TELEGRAM] Video send failed: {response.text}")
                            send_success = False
                        else:
                            print(f"[TELEGRAM] ✓ Đã gửi video vi phạm 5s (từ camera gốc)")
            except Exception as e:
                print(f"[TELEGRAM] Video send error: {e}")
                send_success = False

        if violation_id:
            if send_success:
                update_telegram_status(violation_id, 'sent')
                print(f"[TELEGRAM] ✅ Đã gửi đầy đủ cảnh báo cho {plate} (Status: sent)")
            else:
                update_telegram_status(violation_id, 'failed')
                print(f"[TELEGRAM] ⚠️ Gửi cảnh báo cho {plate} có lỗi (Status: failed)")
        else:
            print(f"[TELEGRAM] ✅ Đã gửi đầy đủ cảnh báo cho {plate}")

    except Exception as e:
        print(f"[TELEGRAM ERROR] {e}")
        import traceback
        traceback.print_exc()
        # Cập nhật status thành 'failed' nếu có lỗi
        if violation_id:
            update_telegram_status(violation_id, 'failed')

# ======================






def is_valid_plate(plate):
    """Validate biển số Việt Nam hợp lệ"""
    if not plate:
        return False
    plate = plate.replace(" ", "").replace(".", "").replace("-", "").replace("_", "").upper()
    if len(plate) < 7 or len(plate) > 9:
        return False
    patterns = [
        r"^[0-9]{2}[A-Z][0-9]{5}$",
        r"^[0-9]{2}[A-Z]{2}[0-9]{4}$",
        r"^[0-9]{2}NG[0-9]{4}$",
        r"^[0-9]{2}[A-Z][0-9]{4}$"
    ]
    for pattern in patterns:
        if re.match(pattern, plate):
            return True
    return False

def normalize_plate(plate):
    """Normalize biển số"""
    if not plate:
        return ""
    return plate.replace(" ", "").replace(".", "").replace("-", "").replace("_", "").upper()


def save_violation_data(detection, speed, frame):
    """Lưu dữ liệu vi phạm vào database và gửi cho ALPR worker async - Using ViolationSaver"""
    try:
        plate = detection.get('plate')
        vehicle_class = detection['vehicle_class']
        track_id = detection['track_id']
        vehicle_bbox = detection['vehicle_bbox']
        plate_bbox = detection.get('plate_bbox', vehicle_bbox)  # Fallback to vehicle_bbox if no plate_bbox

        if not can_save_violation(track_id, plate):
            return

        timestamp = time.time()
        temp_plate = normalize_plate(plate) if plate else f"UNKNOWN_{track_id}"

        # Get clean frames from buffer
        clean_frames = []
        if track_id in violation_frame_buffer:
            buffer_data = violation_frame_buffer[track_id]
            if isinstance(buffer_data, dict):
                # New dict format
                clean_frames = list(buffer_data.get('frames', []))
            else:
                # Old deque format (backward compatibility)
                clean_frames = list(buffer_data)

        # Check if we have enough frames
        if len(clean_frames) < 30:
            print(f"[VIOLATION SAVER] ⚠️ Không đủ frames ({len(clean_frames)} < 30), bỏ qua vi phạm")
            return

        print(f"[VIOLATION SAVER] 📹 Bắt đầu lưu vi phạm với {len(clean_frames)} frames")

        # Use ViolationSaver to save evidence
        try:
            target_fps = 10  # Optimal for file size and quality
            best_frame_idx = len(clean_frames) // 2  # Use middle frame as best frame

            result = save_violation_evidence(
                frames=clean_frames,
                fps=target_fps,
                full_frame=clean_frames[best_frame_idx],
                vehicle_bbox=tuple(vehicle_bbox),
                plate_bbox=tuple(plate_bbox),
                plate_number=temp_plate,
                timestamp=timestamp,
                base_dir="violations"
            )

            # Extract paths from result
            vehicle_img_path = result['vehicle_image']
            video_path = result['video']
            violation_img_path = vehicle_img_path

            # Extract just the filename for database (relative path from violations/)
            vehicle_img_name = os.path.relpath(vehicle_img_path, "violations")
            video_name_for_db = os.path.relpath(video_path, "violations")

            print(f"[VIOLATION SAVER] ✅ Đã lưu evidence:")
            print(f"  - Vehicle: {vehicle_img_path}")
            print(f"  - Video: {video_path}")

            # Mark track as sent
            global sent_violation_tracks
            sent_violation_tracks.add(track_id)

        except Exception as e:
            print(f"[VIOLATION SAVER ERROR] {e}")
            import traceback
            traceback.print_exc()
            # Fallback to old paths if ViolationSaver fails
            vehicle_img_path = None
            violation_img_path = None
            video_path = None
            vehicle_img_name = None
            video_name_for_db = None

        violation_id = None
        try:
            with app.app_context():
                conn = mysql.connection
                cursor = conn.cursor()
                cursor.execute("SET time_zone = '+07:00'")

                db_plate = temp_plate if (temp_plate and is_valid_plate(temp_plate)) else None

                if db_plate:
                    cursor.execute("INSERT IGNORE INTO vehicle_owner (plate, owner_name, address, phone) VALUES (%s, NULL, NULL, NULL)", (db_plate,))
                    conn.commit()

                cursor.execute("""
                    INSERT INTO violations (plate, speed, speed_limit, image, plate_image, video, status, vehicle_class, time)
                    VALUES (%s, %s, %s, %s, %s, %s, 'pending', %s, CONVERT_TZ(NOW(), @@session.time_zone, '+07:00'))
                """, (
                    db_plate,
                    speed,
                    speed_limit,
                    vehicle_img_name if vehicle_img_path else None,
                    None,
                    video_name_for_db if video_name_for_db else None,
                    vehicle_class
                ))
                conn.commit()
                violation_id = cursor.lastrowid
                cursor.close()
                print(f"[DB] ✅ Đã lưu violation vào database (ID: {violation_id}, Plate tạm: {db_plate or 'NULL'})")
        except Exception as e:
            print(f"[ERROR] Database error: {e}")
            import traceback
            traceback.print_exc()
            return

        if violation_id and violation_img_path and os.path.exists(violation_img_path):
            print(f"[ALPR QUEUE] 📤 Gửi ảnh đã lưu vào ALPR queue (async): {os.path.basename(violation_img_path)}")
            start_alpr_worker()
            try:
                alpr_queue.put({
                    'violation_id': violation_id,
                    'violation_img_path': violation_img_path,
                    'vehicle_img_path': vehicle_img_path,
                    'video_path': video_path,
                    'speed': speed,
                    'speed_limit': speed_limit,
                    'vehicle_class': vehicle_class,
                    'track_id': track_id
                }, block=False)
                print(f"[ALPR QUEUE] ✅ Đã thêm vào ALPR queue (Tổng: {alpr_queue.qsize()} ảnh đang chờ)")
            except queue.Full:
                print(f"[ALPR QUEUE] ⚠️ Queue đầy, bỏ qua ảnh này (có thể xử lý sau)")
        else:
            print(f"[WARNING] Không thể gửi ảnh cho ALPR: violation_id={violation_id}, img_exists={violation_img_path and os.path.exists(violation_img_path) if violation_img_path else False}")

        print(f"[SAVED] ✅ Đã lưu vi phạm: {vehicle_class} - Track ID: {track_id} - {speed:.1f} km/h (Fast-ALPR đang xử lý...)")

    except Exception as e:
        print(f"[ERROR] save_violation_data failed: {e}")
        import traceback
        traceback.print_exc()


def process_plate_from_saved_image(violation_id, violation_img_path, vehicle_img_path, video_path, speed, speed_limit, vehicle_class, track_id):
    """Đọc biển số từ ảnh vi phạm đã lưu bằng Fast-ALPR và cập nhật database"""
    try:
        print(f"[FAST-ALPR] 🔍 Bắt đầu đọc biển số từ ảnh đã lưu: {os.path.basename(violation_img_path)}")

        # Kiểm tra ảnh tồn tại
        if not os.path.exists(violation_img_path):
            print(f"[FAST-ALPR] ❌ Ảnh không tồn tại: {violation_img_path}")
            return

        violation_frame = cv2.imread(violation_img_path)
        if violation_frame is None:
            print(f"[FAST-ALPR] ❌ Không thể đọc ảnh: {violation_img_path}")
            return

        print(f"[FAST-ALPR] ✅ Đã đọc ảnh từ disk: {violation_frame.shape[1]}x{violation_frame.shape[0]}")

        h_orig, w_orig = violation_frame.shape[:2]
        max_width = 800
        max_height = 600

        scale_factor = 1.0
        if w_orig > max_width or h_orig > max_height:
            scale_w = max_width / w_orig if w_orig > max_width else 1.0
            scale_h = max_height / h_orig if h_orig > max_height else 1.0
            scale_factor = min(scale_w, scale_h)
            new_w = int(w_orig * scale_factor)
            new_h = int(h_orig * scale_factor)
            detection_frame = cv2.resize(violation_frame, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
            print(f"[FAST-ALPR] ⚡ Resize ảnh: {w_orig}x{h_orig} → {new_w}x{new_h}")
        else:
            detection_frame = violation_frame

        plate_img_path = None
        plate_img_name = None
        detected_plate_text = None
        detected_plate_bbox = None

        try:
            if plate_detector_post is None:
                print(f"[FAST-ALPR] ⚠️ Plate detector not available, skipping plate detection")
                plate_results_raw = []
            else:
                plate_results_raw = plate_detector_post.detect(detection_frame)

            if not plate_results_raw:
                print(f"[FAST-ALPR] ⚠️ Fast-ALPR không phát hiện biển số")
                plate_results = []
                if violation_img_path and os.path.exists(violation_img_path):
                    try:
                        os.remove(violation_img_path)
                        print(f"[CLEANUP] 🗑️ Đã xóa ảnh vi phạm vì FastALPR không đọc được biển số: {os.path.basename(violation_img_path)}")
                    except Exception as e:
                        print(f"[ERROR] Không thể xóa ảnh: {e}")
                # Xóa ảnh xe nếu có
                if vehicle_img_path and os.path.exists(vehicle_img_path):
                    try:
                        os.remove(vehicle_img_path)
                        print(f"[CLEANUP] 🗑️ Đã xóa ảnh xe: {os.path.basename(vehicle_img_path)}")
                    except Exception as e:
                        print(f"[ERROR] Không thể xóa ảnh xe: {e}")
                # Xóa record trong database
                try:
                    with app.app_context():
                        conn = mysql.connection
                        cursor = conn.cursor()
                        cursor.execute("DELETE FROM violations WHERE id=%s", (violation_id,))
                        conn.commit()
                        print(f"[CLEANUP] 🗑️ Đã xóa violation ID {violation_id} vì FastALPR không đọc được biển số")
                except Exception as e:
                    print(f"[ERROR] Không thể xóa record trong database: {e}")
                return  # Dừng xử lý vì không có biển số
            else:
                print(f"[FAST-ALPR] ⚡ Phát hiện {len(plate_results_raw)} biển số")

                plate_results = []
                seen_plates = set()

                for result in plate_results_raw:
                    plate_text = result.get('plate', '').strip()
                    if not plate_text:
                        continue

                    if scale_factor != 1.0:
                        px1, py1, px2, py2 = result['bbox']
                        px1 = int(px1 / scale_factor)
                        py1 = int(py1 / scale_factor)
                        px2 = int(px2 / scale_factor)
                        py2 = int(py2 / scale_factor)
                        result['bbox'] = (px1, py1, px2, py2)

                    normalized = normalize_plate(plate_text)
                    if normalized and normalized not in seen_plates:
                        seen_plates.add(normalized)
                        result['plate'] = normalized
                        result['plate_original'] = plate_text
                        plate_results.append(result)

            if plate_results and len(plate_results) > 0:
                print(f"[FAST-ALPR] ✅ Tổng cộng phát hiện {len(plate_results)} biển số unique trong ảnh vi phạm")

                best_plate = None
                best_score = 0

                for plate_result in plate_results:
                    plate_text = plate_result['plate']
                    plate_bbox_crop = plate_result['bbox']
                    plate_conf = plate_result.get('confidence', 0.5)
                    detection_conf = plate_result.get('detection_conf', 0.5)
                    ocr_conf = plate_result.get('ocr_conf', 0.5)

                    plate_text = normalize_plate(plate_text)
                    if not plate_text:
                        continue

                    if not is_valid_plate(plate_text):
                        print(f"[FAST-ALPR] ⚠️ Bỏ qua biển số không hợp lệ: {plate_text} (original: {plate_result.get('plate_original', '')})")
                        continue

                    score = plate_conf * 50
                    score += detection_conf * 20
                    score += ocr_conf * 15
                    
                    if len(plate_text) >= 8:
                        score += 30
                    elif len(plate_text) >= 6:
                        score += 20
                    else:
                        continue

                    px1, py1, px2, py2 = plate_bbox_crop
                    if px2 <= px1 or py2 <= py1:
                        continue

                    bbox_w = px2 - px1
                    bbox_h = py2 - py1
                    bbox_area = bbox_w * bbox_h

                    if 50 <= bbox_w <= 500 and 20 <= bbox_h <= 150:
                        score += 10
                    if bbox_area >= 2000:
                        score += 5

                    aspect_ratio = bbox_w / bbox_h if bbox_h > 0 else 0
                    if 2.0 <= aspect_ratio <= 5.0:
                        score += 10

                    if score > best_score:
                        best_plate = {
                            'plate': plate_text,
                            'bbox': plate_bbox_crop,
                            'confidence': plate_conf,
                            'detection_conf': detection_conf,
                            'ocr_conf': ocr_conf
                        }
                        best_score = score

                if best_plate:
                    detected_plate_text = normalize_plate(best_plate['plate'])
                    detected_plate_bbox = best_plate['bbox']
                    print(f"[FAST-ALPR] ✅ Fast-ALPR đã đọc được biển số: {detected_plate_text} "
                          f"(conf={best_plate['confidence']:.2f}, det={best_plate['detection_conf']:.2f}, ocr={best_plate['ocr_conf']:.2f}, score={best_score:.1f})")
                    print(f"[FAST-ALPR] 📦 Bounding box biển số: ({detected_plate_bbox[0]}, {detected_plate_bbox[1]}, {detected_plate_bbox[2]}, {detected_plate_bbox[3]})")
                else:
                    print(f"[FAST-ALPR] ⚠️ Không có biển số hợp lệ trong kết quả")
                    # Log tất cả biển số đã detect để debug
                    for r in plate_results:
                        print(f"  - Detected: '{r.get('plate_original', r.get('plate', ''))}' -> normalized: '{normalize_plate(r.get('plate', ''))}' -> valid: {is_valid_plate(normalize_plate(r.get('plate', '')))}")
                    # Xóa ảnh vi phạm vì không có biển số hợp lệ
                    if violation_img_path and os.path.exists(violation_img_path):
                        try:
                            os.remove(violation_img_path)
                            print(f"[CLEANUP] 🗑️ Đã xóa ảnh vi phạm vì không có biển số hợp lệ: {os.path.basename(violation_img_path)}")
                        except Exception as e:
                            print(f"[ERROR] Không thể xóa ảnh: {e}")
                    # Xóa ảnh xe nếu có
                    if vehicle_img_path and os.path.exists(vehicle_img_path):
                        try:
                            os.remove(vehicle_img_path)
                            print(f"[CLEANUP] 🗑️ Đã xóa ảnh xe: {os.path.basename(vehicle_img_path)}")
                        except Exception as e:
                            print(f"[ERROR] Không thể xóa ảnh xe: {e}")
                    # Xóa record trong database
                    try:
                        with app.app_context():
                            conn = mysql.connection
                            cursor = conn.cursor()
                            cursor.execute("DELETE FROM violations WHERE id=%s", (violation_id,))
                            conn.commit()
                            print(f"[CLEANUP] 🗑️ Đã xóa violation ID {violation_id} vì không có biển số hợp lệ")
                    except Exception as e:
                        print(f"[ERROR] Không thể xóa record trong database: {e}")
                    return  # Dừng xử lý vì không có biển số hợp lệ
            else:
                print(f"[FAST-ALPR] ⚠️ Fast-ALPR không tìm thấy biển số hợp lệ sau khi xử lý")
                # Xóa ảnh vi phạm vì FastALPR không tìm thấy biển số hợp lệ
                if violation_img_path and os.path.exists(violation_img_path):
                    try:
                        os.remove(violation_img_path)
                        print(f"[CLEANUP] 🗑️ Đã xóa ảnh vi phạm vì FastALPR không phát hiện biển số: {os.path.basename(violation_img_path)}")
                    except Exception as e:
                        print(f"[ERROR] Không thể xóa ảnh: {e}")
                # Xóa ảnh xe nếu có
                if vehicle_img_path and os.path.exists(vehicle_img_path):
                    try:
                        os.remove(vehicle_img_path)
                        print(f"[CLEANUP] 🗑️ Đã xóa ảnh xe: {os.path.basename(vehicle_img_path)}")
                    except Exception as e:
                        print(f"[ERROR] Không thể xóa ảnh xe: {e}")
                # Xóa record trong database
                try:
                    with app.app_context():
                        conn = mysql.connection
                        cursor = conn.cursor()
                        cursor.execute("DELETE FROM violations WHERE id=%s", (violation_id,))
                        conn.commit()
                        print(f"[CLEANUP] 🗑️ Đã xóa violation ID {violation_id} vì FastALPR không tìm thấy biển số hợp lệ")
                except Exception as e:
                    print(f"[ERROR] Không thể xóa record trong database: {e}")
                return  # Dừng xử lý vì không phát hiện biển số
        except Exception as e:
            print(f"[ERROR] ❌ Lỗi khi dùng Fast-ALPR đọc biển số: {e}")
            import traceback
            traceback.print_exc()

        if detected_plate_bbox:
            print(f"[PLATE CROP] ✂️ Đang crop ảnh biển số từ bounding box của Fast-ALPR...")
            try:
                px1, py1, px2, py2 = detected_plate_bbox
                h, w = violation_frame.shape[:2]
                print(f"[PLATE CROP] Fast-ALPR bbox: ({px1}, {py1}, {px2}, {py2}), Violation frame size: {w}x{h}")

                px1 = max(0, min(px1, w - 1))
                py1 = max(0, min(py1, h - 1))
                px2 = max(px1 + 1, min(px2, w))
                py2 = max(py1 + 1, min(py2, h))

                if px2 <= px1 or py2 <= py1:
                    print(f"[ERROR] Plate bbox không hợp lệ sau validate: ({px1}, {py1}, {px2}, {py2})")
                else:
                    bbox_w_orig = px2 - px1
                    bbox_h_orig = py2 - py1

                    padding_x = max(5, int(bbox_w_orig * 0.05))
                    padding_y = max(3, int(bbox_h_orig * 0.05))
                    padding_x = min(padding_x, 10)
                    padding_y = min(padding_y, 8)

                    px1 = max(0, px1 - padding_x)
                    py1 = max(0, py1 - padding_y)
                    px2 = min(w, px2 + padding_x)
                    py2 = min(h, py2 + padding_y)

                    bbox_w = px2 - px1
                    bbox_h = py2 - py1

                    print(f"[PLATE CROP] After padding: ({px1}, {py1}, {px2}, {py2}), Size: {bbox_w}x{bbox_h} (padding: {padding_x}x{padding_y})")

                    if bbox_w >= 30 and bbox_h >= 15:
                        plate_img = violation_frame[py1:py2, px1:px2].copy()

                        if plate_img.size == 0:
                            print(f"[ERROR] ❌ Plate crop rỗng: ({px1}, {py1}, {px2}, {py2})")
                        else:
                            print(f"[PLATE CROP] ✅ Crop thành công ảnh biển số: {plate_img.shape[1]}x{plate_img.shape[0]}")

                            try:
                                if len(plate_img.shape) == 2:
                                    plate_img = cv2.cvtColor(plate_img, cv2.COLOR_GRAY2BGR)
                                elif len(plate_img.shape) == 3 and plate_img.shape[2] == 3:
                                    pass
                                else:
                                    plate_img = cv2.cvtColor(plate_img, cv2.COLOR_GRAY2BGR)

                                if len(plate_img.shape) != 3 or plate_img.shape[2] != 3:
                                    raise ValueError(f"Ảnh không phải BGR: shape={plate_img.shape}")

                                lab = cv2.cvtColor(plate_img, cv2.COLOR_BGR2LAB)
                                l, a, b = cv2.split(lab)
                                clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(4,4))
                                l_enhanced = clahe.apply(l)
                                lab_enhanced = cv2.merge([l_enhanced, a, b])
                                enhanced = cv2.cvtColor(lab_enhanced, cv2.COLOR_LAB2BGR)

                                if len(enhanced.shape) != 3 or enhanced.shape[2] != 3:
                                    raise ValueError(f"Ảnh enhanced không phải BGR: shape={enhanced.shape}")

                                gaussian = cv2.GaussianBlur(enhanced, (0, 0), 1.5)
                                sharpened = cv2.addWeighted(enhanced, 1.5, gaussian, -0.5, 0)

                                hsv = cv2.cvtColor(sharpened, cv2.COLOR_BGR2HSV)
                                h, s, v = cv2.split(hsv)
                                s = cv2.multiply(s, 1.2)
                                s = cv2.min(s, 255)
                                hsv_enhanced = cv2.merge([h, s, v])
                                sharpened = cv2.cvtColor(hsv_enhanced, cv2.COLOR_HSV2BGR)

                                if len(sharpened.shape) != 3 or sharpened.shape[2] != 3:
                                    raise ValueError(f"Ảnh sharpened không phải BGR: shape={sharpened.shape}")

                                h_img, w_img = sharpened.shape[:2]
                                target_width = 200
                                max_width = 400

                                if w_img < target_width:
                                    scale = target_width / w_img
                                    new_w = int(w_img * scale)
                                    new_h = int(h_img * scale)
                                    if new_w > max_width:
                                        scale = max_width / w_img
                                        new_w = int(w_img * scale)
                                        new_h = int(h_img * scale)
                                    sharpened = cv2.resize(sharpened, (new_w, new_h), interpolation=cv2.INTER_CUBIC)
                                elif w_img > max_width:
                                    scale = max_width / w_img
                                    new_w = int(w_img * scale)
                                    new_h = int(h_img * scale)
                                    sharpened = cv2.resize(sharpened, (new_w, new_h), interpolation=cv2.INTER_CUBIC)

                                if len(sharpened.shape) != 3 or sharpened.shape[2] != 3:
                                    raise ValueError(f"Ảnh cuối cùng không phải BGR: shape={sharpened.shape}")

                                plate_img_final = sharpened

                                if not detected_plate_text or not is_valid_plate(detected_plate_text):
                                    print(f"[SKIP] ⚠️ Biển số không hợp lệ, không lưu ảnh: {detected_plate_text}")
                                    plate_img_path = None
                                    plate_img_name = None
                                else:
                                    timestamp_plate = int(time.time())
                                    plate_img_name = f"{detected_plate_text}_{timestamp_plate}_plate.jpg"
                                    plate_img_path = os.path.join("static/plate_images", plate_img_name)
                                    cv2.imwrite(plate_img_path, plate_img_final, [cv2.IMWRITE_JPEG_QUALITY, 95])
                                    print(f"[SAVED] ✅ Đã lưu ảnh biển số: {plate_img_name}")
                            except Exception as e:
                                print(f"[WARNING] Plate enhance failed: {e}, saving original")
                                if len(plate_img.shape) == 2:
                                    plate_img = cv2.cvtColor(plate_img, cv2.COLOR_GRAY2BGR)

                                if not detected_plate_text or not is_valid_plate(detected_plate_text):
                                    print(f"[SKIP] ⚠️ Biển số không hợp lệ, không lưu ảnh: {detected_plate_text}")
                                    plate_img_path = None
                                    plate_img_name = None
                                else:
                                    timestamp_plate = int(time.time())
                                    plate_img_name = f"{detected_plate_text}_{timestamp_plate}_plate.jpg"
                                    plate_img_path = os.path.join("static/plate_images", plate_img_name)
                                    cv2.imwrite(plate_img_path, plate_img, [cv2.IMWRITE_JPEG_QUALITY, 95])
                                    print(f"[SAVED] ✅ Đã lưu ảnh biển số (original): {plate_img_name}")
                    else:
                        print(f"[WARNING] ⚠️ Plate bbox quá nhỏ hoặc không hợp lệ: ({px1}, {py1}, {px2}, {py2}), Size: {bbox_w}x{bbox_h}")
            except Exception as e:
                print(f"[ERROR] ❌ Lỗi khi xử lý plate_bbox từ Fast-ALPR: {e}")
                import traceback
                traceback.print_exc()

        if detected_plate_text and is_valid_plate(detected_plate_text) and plate_img_path and os.path.exists(plate_img_path):
            try:
                with app.app_context():
                    conn = mysql.connection
                    cursor = conn.cursor()
                    cursor.execute("SET time_zone = '+07:00'")

                    cursor.execute("SELECT * FROM vehicle_owner WHERE plate=%s", (detected_plate_text,))
                    owner = cursor.fetchone()
                    if not owner:
                        cursor.execute("INSERT INTO vehicle_owner (plate, owner_name, address, phone) VALUES (%s, NULL, NULL, NULL)", (detected_plate_text,))
                        conn.commit()

                    cursor.execute("""
                        UPDATE violations
                        SET plate=%s, plate_image=%s, vehicle_class=%s
                        WHERE id=%s
                    """, (
                        detected_plate_text,
                        plate_img_name,
                        vehicle_class,
                        violation_id
                    ))
                    conn.commit()

                    cursor.execute("SELECT owner_name, address, phone FROM vehicle_owner WHERE plate=%s", (detected_plate_text,))
                    owner = cursor.fetchone()
                    owner_name = owner["owner_name"] or "Không rõ" if owner else "Không rõ"
                    address = owner["address"] or "Không rõ" if owner else "Không rõ"
                    phone = owner["phone"] or "Không rõ" if owner else "Không rõ"

                    print(f"[DB] ✅ Đã cập nhật violation ID {violation_id} với biển số: {detected_plate_text} và ảnh biển số: {plate_img_name}")

                    full_img_path = violation_img_path
                    queue_telegram_alert(
                        plate=detected_plate_text,
                        speed=speed,
                        limit=speed_limit,
                        full_img_path=full_img_path,
                        plate_img_path=plate_img_path,
                        video_path=video_path,
                        owner_name=owner_name,
                        address=address,
                        phone=phone,
                        vehicle_class=vehicle_class,
                        violation_id=violation_id
                    )
            except Exception as e:
                print(f"[ERROR] Database update error: {e}")
                import traceback
                traceback.print_exc()
        else:
            try:
                with app.app_context():
                    conn = mysql.connection
                    cursor = conn.cursor()
                    cursor.execute("DELETE FROM violations WHERE id=%s", (violation_id,))
                    conn.commit()

                    if violation_img_path and os.path.exists(violation_img_path):
                        try:
                            os.remove(violation_img_path)
                            print(f"[CLEANUP] Đã xóa ảnh vi phạm: {os.path.basename(violation_img_path)}")
                        except:
                            pass

                    if vehicle_img_path and os.path.exists(vehicle_img_path):
                        try:
                            os.remove(vehicle_img_path)
                            print(f"[CLEANUP] Đã xóa ảnh xe: {os.path.basename(vehicle_img_path)}")
                        except:
                            pass

                    if video_path and os.path.exists(video_path):
                        try:
                            os.remove(video_path)
                            print(f"[CLEANUP] Đã xóa video: {os.path.basename(video_path)}")
                        except:
                            pass

                    reason = []
                    if not detected_plate_text or not is_valid_plate(detected_plate_text):
                        reason.append("không có biển số hợp lệ")
                    if not plate_img_path or not os.path.exists(plate_img_path):
                        reason.append("không có ảnh biển số")

                    print(f"[SKIP] ⚠️ Đã xóa violation ID {violation_id} vì: {', '.join(reason)}")
            except Exception as e:
                print(f"[ERROR] Cleanup error: {e}")
                import traceback
                traceback.print_exc()

        print(f"[FAST-ALPR] ✅ Hoàn thành xử lý ảnh vi phạm ID {violation_id}")

    except Exception as e:
        print(f"[ERROR] process_plate_from_saved_image failed: {e}")
        import traceback
        traceback.print_exc()

def get_detection_queue_size():
    """Tính queue size dựa trên device và mode"""
    base_size = 15 if DEVICE == 'cuda' else 10
    if is_video_upload_mode:
        return base_size + 5
    return base_size

detection_queue = deque(maxlen=get_detection_queue_size())
stream_queue_clean = queue.Queue(maxsize=60)
stream_queue = queue.Queue(maxsize=30)
alpr_proactive_queue = queue.Queue(maxsize=50)
alpr_realtime_queue = queue.Queue(maxsize=30)
best_frame_queue = queue.Queue(maxsize=30)
violation_queue = queue.Queue(maxsize=30)
telegram_queue = queue.Queue(maxsize=100)

alpr_proactive_cache = {}
alpr_cache_lock = threading.Lock()

original_frame_buffer = {}
admin_frame_buffer = {}
violation_frame_buffer = {}
current_detections = {}
sent_violation_tracks = set()
recording_tracks = {}

def cleanup_old_buffers():
    """Xóa buffer không được update trong 5 giây"""
    now = time.time()
    to_delete = []

    for track_id, data in violation_frame_buffer.items():
        if isinstance(data, dict) and 'last_update' in data:
            if now - data['last_update'] > 5.0:
                to_delete.append(track_id)

    for track_id in to_delete:
        if track_id in violation_frame_buffer:
            del violation_frame_buffer[track_id]
        if track_id in recording_tracks:
            del recording_tracks[track_id]
        print(f"🗑️ Cleaned up buffer for track {track_id}")
    
    # NEW: Cleanup expired active tracks (không thấy sau TRACK_TIMEOUT)
    with active_tracks_lock:
        expired = [tid for tid, t in active_tracks.items() if now - t > TRACK_TIMEOUT]
        for tid in expired:
            del active_tracks[tid]
            if tid in original_frame_buffer:
                del original_frame_buffer[tid]
            print(f"🗑️ Cleaned up expired active track {tid}")

def start_recording_violation(track_id):
    """Bắt đầu recording frames cho vi phạm"""
    if track_id not in recording_tracks:
        recording_tracks[track_id] = {
            'start_time': time.time(),
            'frame_count': 0
        }
        if track_id not in violation_frame_buffer:
            violation_frame_buffer[track_id] = {
                'frames': deque(maxlen=150),  # 150 frames @ 30fps = 5s (dư để chọn)
                'last_update': time.time()
            }

def update_recording(track_id, frame):
    """Cập nhật frame vào buffer"""
    if track_id in violation_frame_buffer:
        if isinstance(violation_frame_buffer[track_id], dict):
            violation_frame_buffer[track_id]['frames'].append(frame.copy())
            violation_frame_buffer[track_id]['last_update'] = time.time()
        else:
            # Backward compatibility
            violation_frame_buffer[track_id].append(frame.copy())

        if track_id in recording_tracks:
            recording_tracks[track_id]['frame_count'] += 1

alpr_queue = queue.Queue(maxsize=50)
alpr_worker_running = False

def detection_worker():
    """THREAD 2: Detection Worker - YOLO + Tracking + Speed"""
    global current_detections, is_video_upload_mode, stream_queue, admin_frame_buffer, violation_frame_buffer, original_frame_buffer, violation_queue, detector, tracker, active_tracks, active_tracks_lock, video_fps

    # Khởi tạo detector nếu chưa có
    init_detector()

    # Kiểm tra detector đã được khởi tạo thành công chưa
    if detector is None:
        print("[ERROR] Detection worker: Detector initialization failed. Retrying in loop...")

    # Buffer cleanup timer
    last_cleanup = time.time()

    while camera_running:
        # Nếu detector chưa được khởi tạo, thử lại mỗi giây
        if detector is None:
            print("[ERROR] Detection worker: Detector is None, retrying initialization...")
            init_detector()
            if detector is None:
                time.sleep(1)
                continue

        if time.time() - last_cleanup > 2.0:
            cleanup_old_buffers()
            last_cleanup = time.time()

        if len(detection_queue) == 0:
            if is_video_upload_mode:
                sleep_time = 0.0001 if DEVICE == 'cuda' else 0.0005
            else:
                sleep_time = 0.0005 if DEVICE == 'cuda' else 0.001
            time.sleep(sleep_time)
            continue

        try:
            frame_data = detection_queue.popleft()
            detect_frame = frame_data['frame']
            original_frame = frame_data['original']
            # USE frame_number (actual frame in source video) NOT frame_id (counter)
            frame_id = frame_data.get('frame_number', frame_data.get('frame_id', frame_data.get('id', 0)))

            # Kiểm tra detector trước khi sử dụng
            if detector is None:
                init_detector()
                if detector is None:
                    print("[ERROR] Detection worker: Detector is None, skipping frame")
                    continue

            detections = detector.detect(detect_frame, enable_plate_detection=True)
            admin_frame = original_frame.copy()

            if DETECTION_SCALE < 1.0:
                original_h, original_w = original_frame.shape[:2]
                detect_h, detect_w = detect_frame.shape[:2]
                scale_x = original_w / detect_w
                scale_y = original_h / detect_h

                for det in detections:
                    x1, y1, x2, y2 = det['vehicle_bbox']
                    new_x1 = max(0, min(int(x1 * scale_x + 0.5), original_w - 1))
                    new_y1 = max(0, min(int(y1 * scale_y + 0.5), original_h - 1))
                    new_x2 = max(new_x1 + 1, min(int(x2 * scale_x + 0.5), original_w))
                    new_y2 = max(new_y1 + 1, min(int(y2 * scale_y + 0.5), original_h))
                    det['vehicle_bbox'] = (new_x1, new_y1, new_x2, new_y2)

            new_detections = {}
            for detection in detections:
                track_id = detection['track_id']
                vehicle_bbox = detection['vehicle_bbox']
                vehicle_class = detection['vehicle_class']
                plate = detection.get('plate')
                plate_bbox = detection.get('plate_bbox')

                speed = tracker.update(track_id, vehicle_bbox)

                if track_id in current_detections:
                    old_det = current_detections[track_id]
                    if old_det.get('speed') is not None:
                        if speed is not None:
                            speed = 0.75 * speed + 0.25 * old_det['speed']
                        else:
                            speed = old_det['speed']

                detection['speed'] = speed
                new_detections[track_id] = detection

                # NEW: Update active_tracks (video_reader sẽ tự động buffer frames)
                with active_tracks_lock:
                    active_tracks[track_id] = time.time()

                # REMOVED: Không còn cần populate original_frame_buffer ở đây
                # video_reader đã handle việc buffer MỌI frame cho active tracks rồi

                try:
                    detector.draw_detections(admin_frame, detection, speed, speed_limit)
                except Exception as e:
                    print(f"[DETECT THREAD] Error drawing detection: {e}")

                if speed and speed > speed_limit:
                    start_recording_violation(track_id)
                    update_recording(track_id, original_frame)

                    # NEW: Track violation frame number for video extraction
                    if track_id not in violation_frame_buffer:
                        violation_frame_buffer[track_id] = {
                            'frames': deque(maxlen=150),
                            'last_update': time.time()
                        }

                    # Save violation frame number
                    violation_frame_buffer[track_id]['violation_frame'] = frame_id
                    violation_frame_buffer[track_id]['violation_timestamp'] = frame_id / video_fps if video_fps > 0 else 0

                    print(f"[DETECTION] 📍 Violation frame: {frame_id}, timestamp: {frame_id / video_fps:.2f}s")
                    print(f"[DETECTION] 🎯 This is ACTUAL frame {frame_id} in source video (not counter)")

                    # FIX: Sử dụng can_save_violation để kiểm tra cooldown (đồng bộ logic)
                    # DEBUG: Log để kiểm tra
                    print(f"[DETECTION] 🔍 Checking violation: track_id={track_id}, plate={plate}, speed={speed:.1f} km/h")
                    can_save = can_save_violation(track_id, plate)
                    print(f"[DETECTION] 🔍 can_save_violation(track_id={track_id}, plate={plate}) = {can_save}")
                    if not can_save:
                        print(f"[DETECTION] ⏳ Bỏ qua vi phạm trùng lặp: track_id={track_id}, plate={plate}")
                        continue
                    print(f"[DETECTION] ✅ Cho phép lưu vi phạm: track_id={track_id}, plate={plate}")

                    # PRE-BUFFERING: Copy TẤT CẢ frames từ original_frame_buffer vào violation_frame_buffer
                    # Bao gồm CẢ frames TRƯỚC + SAU vi phạm
                    if track_id in original_frame_buffer and len(original_frame_buffer[track_id]) > 0:
                        all_frames = list(original_frame_buffer[track_id])
                        
                        # Extract chỉ frame data (bỏ dict wrapper)
                        frames_only = []
                        for frame_data in all_frames:
                            if isinstance(frame_data, dict) and 'frame' in frame_data:
                                frames_only.append(frame_data['frame'])
                            else:
                                frames_only.append(frame_data)
                        
                        # Lưu vào violation_frame_buffer
                        if track_id not in violation_frame_buffer:
                            violation_frame_buffer[track_id] = {
                                'frames': deque(maxlen=150),
                                'last_update': time.time()
                            }
                        
                        # Thêm tất cả frames vào buffer
                        for f in frames_only:
                            violation_frame_buffer[track_id]['frames'].append(f.copy())
                        
                        print(f"[DETECTION] 📹 Copied {len(frames_only)} frames to violation buffer for track {track_id} (includes frames BEFORE violation)")

                    plate_from_cache = None
                    with alpr_cache_lock:
                        x1, y1, x2, y2 = vehicle_bbox
                        vehicle_center_x = (x1 + x2) / 2
                        vehicle_center_y = (y1 + y2) / 2

                        min_distance = float('inf')
                        best_cache_key = None
                        for cache_key in alpr_proactive_cache:
                            cx, cy = map(int, cache_key.split('_'))
                            distance = ((vehicle_center_x - cx)**2 + (vehicle_center_y - cy)**2)**0.5
                            if distance < min_distance and distance < 200:
                                min_distance = distance
                                best_cache_key = cache_key

                        if best_cache_key:
                            plate_from_cache = alpr_proactive_cache[best_cache_key]
                            print(f"[DETECTION] ✅ Using cached plate: {plate_from_cache['plate']} (confidence: {plate_from_cache['confidence']:.2f})")

                        alpr_data = {
                            'track_id': track_id,
                            'detection': detection,
                            'speed': speed,
                            'full_frame': original_frame.copy(),
                            'vehicle_bbox': vehicle_bbox,
                            'vehicle_class': vehicle_class,
                        'timestamp': time.time(),
                        'cached_plate': plate_from_cache
                        }

                    try:
                        alpr_realtime_queue.put(alpr_data, block=False)
                        print(f"[DETECT THREAD] ✅ Đẩy vào ALPR queue: track_id={track_id}, speed={speed:.1f}")
                    except queue.Full:
                        print(f"[DETECT THREAD] ⚠️ ALPR queue đầy, bỏ qua track_id={track_id}")

            current_detections = new_detections

            if 'global' not in admin_frame_buffer:
                admin_frame_buffer['global'] = deque(maxlen=90)
            admin_frame_buffer['global'].append({
                'frame': admin_frame,
                'frame_id': frame_id,
                'timestamp': time.time()
            })

            try:
                stream_queue.put(admin_frame, block=False)
            except queue.Full:
                pass
            
            active_track_ids = set(det['track_id'] for det in detections)
            tracker.cleanup_old_tracks(active_track_ids)

        except Exception as e:
            print(f"[ERROR] Detection worker error: {e}")

def alpr_proactive_worker():
    """THREAD MỚI: ALPR Proactive Worker - Detect plate TRƯỚC khi vi phạm"""
    global alpr_proactive_queue, alpr_proactive_cache, alpr_cache_lock, detector, camera_running, plate_detector_post

    print("[ALPR PROACTIVE] ✅ Worker started")

    if detector is None:
        init_detector()

    while camera_running:
        try:
            frame_data = alpr_proactive_queue.get(timeout=1.0)
            frame = frame_data['frame']
            frame_id = frame_data['frame_id']
            timestamp = frame_data['timestamp']

            if plate_detector_post is not None:
                plates_detected = plate_detector_post.detect(frame)

                if plates_detected:
                    with alpr_cache_lock:
                        for plate_data in plates_detected:
                            plate_text = plate_data.get('plate', '')
                            bbox = plate_data.get('bbox', [])
                            confidence = plate_data.get('confidence', 0.0)

                            if not plate_text or len(bbox) != 4:
                                continue

                            x1, y1, x2, y2 = bbox
                            center_x = (x1 + x2) / 2
                            center_y = (y1 + y2) / 2

                            cache_key = f"{int(center_x//50)*50}_{int(center_y//50)*50}"

                            if cache_key not in alpr_proactive_cache or \
                               confidence > alpr_proactive_cache[cache_key].get('confidence', 0):
                                alpr_proactive_cache[cache_key] = {
                                    'plate': plate_text,
                                    'bbox': bbox,
                                    'confidence': confidence,
                                    'timestamp': timestamp,
                                    'frame_id': frame_id
                                }

                    with alpr_cache_lock:
                        current_time = timestamp
                        keys_to_remove = []
                        for key, value in alpr_proactive_cache.items():
                            if current_time - value['timestamp'] > 5.0:
                                keys_to_remove.append(key)
                        for key in keys_to_remove:
                            del alpr_proactive_cache[key]

        except queue.Empty:
            continue
        except Exception as e:
            print(f"[ALPR PROACTIVE] ❌ Error: {e}")
            continue

    print("[ALPR PROACTIVE] 🛑 Worker stopped")

def alpr_realtime_worker():
    """THREAD 3: ALPR Realtime Worker - FastALPR detect biển số"""
    global alpr_realtime_queue, best_frame_queue, camera_running, plate_detector_post, alpr_proactive_cache, alpr_cache_lock

    print("[ALPR WORKER] ✅ Thread 3 - ALPR Realtime Worker đã khởi động")

    while camera_running:
        try:
            alpr_data = alpr_realtime_queue.get(timeout=1.0)

            track_id = alpr_data['track_id']
            detection = alpr_data['detection']
            speed = alpr_data['speed']
            full_frame = alpr_data['full_frame']
            vehicle_bbox = alpr_data['vehicle_bbox']
            vehicle_class = alpr_data['vehicle_class']
            timestamp = alpr_data['timestamp']
            cached_plate = alpr_data.get('cached_plate')

            refined_plate = None
            refined_plate_bbox = None
            plate_crop = None

            if cached_plate and cached_plate.get('confidence', 0) > 0.7:
                print(f"[ALPR REALTIME] 📋 Using cached plate: {cached_plate['plate']}")
                refined_plate = cached_plate['plate']
                refined_plate_bbox = cached_plate['bbox']
            else:
                try:
                    x1, y1, x2, y2 = vehicle_bbox
                    padding = 100
                    crop_x1 = max(0, x1 - padding)
                    crop_y1 = max(0, y1 - padding)
                    crop_x2 = min(full_frame.shape[1], x2 + padding)
                    crop_y2 = min(full_frame.shape[0], y2 + padding)

                    vehicle_region = full_frame[crop_y1:crop_y2, crop_x1:crop_x2].copy()

                    if plate_detector_post is not None:
                        plate_results = plate_detector_post.detect(vehicle_region)

                        if plate_results and len(plate_results) > 0:
                            best_plate = max(plate_results, key=lambda p: p.get('confidence', 0))
                            detected_plate = best_plate.get('plate', '')
                            normalized_detected = normalize_plate(detected_plate)

                            if normalized_detected and is_valid_plate(normalized_detected):
                                refined_plate = normalized_detected
                                print(f"[ALPR WORKER] ✅ FastALPR detect: {refined_plate}")

                                plate_bbox_local = best_plate.get('bbox')
                                if plate_bbox_local:
                                    px1_local, py1_local, px2_local, py2_local = plate_bbox_local
                                    refined_plate_bbox = (
                                        crop_x1 + px1_local,
                                        crop_y1 + py1_local,
                                        crop_x1 + px2_local,
                                        crop_y1 + py2_local
                                    )

                                    px1, py1, px2, py2 = refined_plate_bbox
                                    padding_x = max(10, int((px2 - px1) * 0.2))
                                    padding_y = max(5, int((py2 - py1) * 0.2))

                                    px1_padded = max(0, px1 - padding_x)
                                    py1_padded = max(0, py1 - padding_y)
                                    px2_padded = min(full_frame.shape[1], px2 + padding_x)
                                    py2_padded = min(full_frame.shape[0], py2 + padding_y)

                                    if px2_padded > px1_padded and py2_padded > py1_padded:
                                        plate_crop = full_frame[py1_padded:py2_padded, px1_padded:px2_padded].copy()
                except Exception as e:
                    print(f"[ALPR WORKER] Lỗi FastALPR: {e}")

            best_frame_data = {
                'track_id': track_id,
                'detection': detection,
                'speed': speed,
                'full_frame': full_frame,
                'plate': refined_plate,
                'plate_bbox': refined_plate_bbox,
                'plate_crop': plate_crop,
                'vehicle_bbox': vehicle_bbox,
                'vehicle_class': vehicle_class,
                'timestamp': timestamp
            }

            try:
                best_frame_queue.put(best_frame_data, block=False)
                print(f"[ALPR WORKER] ✅ Đẩy vào Best Frame queue: track_id={track_id}, plate={refined_plate}")
            except queue.Full:
                print(f"[ALPR WORKER] ⚠️ Best Frame queue đầy")

        except queue.Empty:
            continue
        except Exception as e:
            print(f"[ALPR WORKER] Lỗi: {e}")
            time.sleep(0.1)

def best_frame_selector_worker():
    """THREAD 4: Best Frame Selector - Chọn frame tốt nhất"""
    global best_frame_queue, violation_queue, violation_frame_buffer, camera_running

    print("[BEST FRAME] ✅ Thread 4 - Best Frame Selector đã khởi động")

    while camera_running:
        try:
            # Lấy dữ liệu từ best_frame_queue
            data = best_frame_queue.get(timeout=1.0)

            track_id = data['track_id']
            full_frame = data['full_frame']
            vehicle_bbox = data['vehicle_bbox']
            plate = data.get('plate')

            # Chọn best frame từ buffer (nếu có)
            best_frame = full_frame
            if track_id in violation_frame_buffer:
                buffer_data = violation_frame_buffer[track_id]
                if isinstance(buffer_data, dict) and 'frames' in buffer_data:
                    frames_list = list(buffer_data['frames'])
                    if frames_list:
                        selected = select_best_frame(frames_list, vehicle_bbox)
                        if selected is not None:
                            best_frame = selected
                            print(f"[BEST FRAME] ✅ Chọn best frame từ {len(frames_list)} frames")

            # Cập nhật full_frame với best_frame
            data['full_frame'] = best_frame

            # FIX: Thêm violation_timestamp và violation_frame vào data
            # Lấy từ violation_frame_buffer (đã được set trong detection_worker)
            print(f"[BEST FRAME DEBUG] track_id={track_id} in violation_frame_buffer? {track_id in violation_frame_buffer}")

            if track_id in violation_frame_buffer:
                buffer_data = violation_frame_buffer[track_id]
                print(f"[BEST FRAME DEBUG] buffer_data type: {type(buffer_data)}")
                print(f"[BEST FRAME DEBUG] buffer_data keys: {list(buffer_data.keys()) if isinstance(buffer_data, dict) else 'not dict'}")

                if isinstance(buffer_data, dict):
                    vts = buffer_data.get('violation_timestamp')
                    vfr = buffer_data.get('violation_frame')
                    print(f"[BEST FRAME DEBUG] violation_timestamp from buffer: {vts}")
                    print(f"[BEST FRAME DEBUG] violation_frame from buffer: {vfr}")

                    data['violation_timestamp'] = vts
                    data['violation_frame'] = vfr
                    print(f"[BEST FRAME] 📍 Added violation info: frame={data.get('violation_frame')}, timestamp={data.get('violation_timestamp')}")
                else:
                    print(f"[BEST FRAME DEBUG] ❌ buffer_data is not dict!")
            else:
                print(f"[BEST FRAME DEBUG] ❌ track_id {track_id} NOT in violation_frame_buffer!")
                print(f"[BEST FRAME DEBUG] Available track_ids in buffer: {list(violation_frame_buffer.keys())}")

            # Đẩy vào violation_queue
            try:
                violation_queue.put(data, block=False)
                print(f"[BEST FRAME] ✅ Đẩy vào Violation queue: track_id={track_id}, plate={plate}")
            except queue.Full:
                print(f"[BEST FRAME] ⚠️ Violation queue đầy")

        except queue.Empty:
            continue
        except Exception as e:
            print(f"[BEST FRAME] Lỗi: {e}")
            time.sleep(0.1)

def violation_worker():
    """THREAD 5: Violation Worker - Lưu ảnh/video và database"""
    global violation_queue, telegram_queue, original_frame_buffer, violation_frame_buffer, camera_running, video_fps, mysql, app, speed_limit, current_video_path

    print("[VIOLATION THREAD] ✅ Đã khởi động")

    while camera_running:
        try:
            # Lấy dữ liệu vi phạm từ violation_queue
            violation_data = violation_queue.get(timeout=1.0)

            track_id = violation_data['track_id']
            detection = violation_data['detection']
            speed = violation_data['speed']
            full_frame = violation_data.get('full_frame')  # ORIGINAL FRAME từ Detection Thread
            plate = violation_data.get('plate')  # Biển số từ FastALPR (có thể None)
            plate_bbox = violation_data.get('plate_bbox')  # Bbox biển số (có thể None)
            plate_crop = violation_data.get('plate_crop')  # Plate đã crop từ Detection Thread (có thể None)
            vehicle_bbox = violation_data['vehicle_bbox']
            vehicle_class = violation_data['vehicle_class']
            timestamp = violation_data['timestamp']

            print(f"[VIOLATION THREAD] Xử lý vi phạm: track_id={track_id}, plate={plate}, speed={speed:.2f} km/h, có plate_crop={plate_crop is not None}")

            if full_frame is None:
                print(f"[VIOLATION THREAD] ⚠️ Không có full_frame trong violation_data, bỏ qua")
                continue

            # FIX: Luôn dùng full_frame để crop (đảm bảo bbox đúng với frame)
            # best_frame chỉ dùng để chọn frame tốt nhất, nhưng crop vẫn dùng full_frame
            best_frame = full_frame
            if track_id in violation_frame_buffer:
                buffer_data = violation_frame_buffer[track_id]
                if isinstance(buffer_data, dict) and 'frames' in buffer_data:
                    frames_list = list(buffer_data['frames'])
                    if frames_list:
                        selected_best = select_best_frame(frames_list, vehicle_bbox)
                        if selected_best is not None:
                            # Kiểm tra resolution của best_frame và full_frame
                            best_h, best_w = selected_best.shape[:2]
                            full_h, full_w = full_frame.shape[:2]
                            
                            if best_h == full_h and best_w == full_w:
                                # Cùng resolution: dùng best_frame
                                best_frame = selected_best
                                print(f"[VIOLATION THREAD] ✅ Đã chọn best frame từ {len(frames_list)} frames (resolution match)")
                            else:
                                # Khác resolution: resize best_frame về full_frame resolution
                                best_frame = cv2.resize(selected_best, (full_w, full_h), interpolation=cv2.INTER_LINEAR)
                                print(f"[VIOLATION THREAD] ✅ Đã chọn best frame và resize về {full_w}x{full_h}")
                        else:
                            best_frame = full_frame

            # FIX: Đảm bảo vehicle_bbox hợp lệ và crop đúng
            x1, y1, x2, y2 = [int(v) for v in vehicle_bbox]
            
            # Kiểm tra bbox hợp lệ
            if x2 <= x1 or y2 <= y1:
                print(f"[VIOLATION THREAD] ⚠️ Invalid bbox: ({x1}, {y1}, {x2}, {y2}), using full_frame")
                best_frame = full_frame
                x1, y1, x2, y2 = 0, 0, best_frame.shape[1], best_frame.shape[0]
            
            # Đảm bảo bbox nằm trong frame
            x1 = max(0, min(x1, best_frame.shape[1] - 1))
            y1 = max(0, min(y1, best_frame.shape[0] - 1))
            x2 = max(x1 + 1, min(x2, best_frame.shape[1]))
            y2 = max(y1 + 1, min(y2, best_frame.shape[0]))
            
            padding = 50
            crop_x1 = max(0, x1 - padding)
            crop_y1 = max(0, y1 - padding)
            crop_x2 = min(best_frame.shape[1], x2 + padding)
            crop_y2 = min(best_frame.shape[0], y2 + padding)

            # FIX: Đảm bảo crop hợp lệ
            if crop_x2 > crop_x1 and crop_y2 > crop_y1:
                vehicle_crop = best_frame[crop_y1:crop_y2, crop_x1:crop_x2].copy()
                print(f"[VIOLATION THREAD] ✅ Crop vehicle: ({crop_x1}, {crop_y1}, {crop_x2}, {crop_y2}) from frame {best_frame.shape}, vehicle_crop size: {vehicle_crop.shape}")
            else:
                print(f"[VIOLATION THREAD] ⚠️ Invalid crop coordinates, using full frame")
                vehicle_crop = best_frame.copy()
                crop_x1, crop_y1 = 0, 0
            
            # FIX: Detect lại plate TRỰC TIẾP trên vehicle_crop để đảm bảo chính xác 100%
            # Không dùng plate_bbox từ full_frame vì có thể bị sai do resolution mismatch
            plate_crop = None
            
            # Đảm bảo plate_detector_post được khởi tạo
            if plate_detector_post is None:
                init_detector()
            
            if plate_detector_post is not None:
                try:
                    print(f"[VIOLATION THREAD] 🔍 Detecting plate trực tiếp trên vehicle_crop (size: {vehicle_crop.shape})")
                    plate_results = plate_detector_post.detect(vehicle_crop)
                    
                    if plate_results and len(plate_results) > 0:
                        # Chọn plate có confidence cao nhất
                        best_plate = max(plate_results, key=lambda p: p.get('confidence', 0))
                        detected_plate_bbox = best_plate.get('bbox')
                        detected_plate_text = best_plate.get('plate', '')
                        detected_confidence = best_plate.get('confidence', 0)
                        
                        print(f"[VIOLATION THREAD] ✅ Detected plate trên vehicle_crop: {detected_plate_text} (conf: {detected_confidence:.2f})")
                        
                        if detected_plate_bbox and len(detected_plate_bbox) == 4:
                            px1, py1, px2, py2 = [int(v) for v in detected_plate_bbox]
                            
                            # Validate bbox
                            vehicle_h, vehicle_w = vehicle_crop.shape[:2]
                            px1 = max(0, min(px1, vehicle_w - 1))
                            py1 = max(0, min(py1, vehicle_h - 1))
                            px2 = max(px1 + 1, min(px2, vehicle_w))
                            py2 = max(py1 + 1, min(py2, vehicle_h))
                            
                            if px2 > px1 and py2 > py1:
                                # Thêm padding cho plate crop (20% mỗi bên)
                                plate_width = px2 - px1
                                plate_height = py2 - py1
                                padding_x = max(10, int(plate_width * 0.2))
                                padding_y = max(5, int(plate_height * 0.2))
                                
                                px1_padded = max(0, px1 - padding_x)
                                py1_padded = max(0, py1 - padding_y)
                                px2_padded = min(vehicle_w, px2 + padding_x)
                                py2_padded = min(vehicle_h, py2 + padding_y)
                                
                                if px2_padded > px1_padded and py2_padded > py1_padded:
                                    plate_crop = vehicle_crop[py1_padded:py2_padded, px1_padded:px2_padded].copy()
                                    print(f"[VIOLATION THREAD] ✅ Đã crop plate từ vehicle_crop: size={plate_crop.shape}, bbox=({px1_padded}, {py1_padded}, {px2_padded}, {py2_padded})")
                                    
                                    # Cập nhật plate text nếu detect được
                                    if detected_plate_text and is_valid_plate(normalize_plate(detected_plate_text)):
                                        plate = normalize_plate(detected_plate_text)
                                        print(f"[VIOLATION THREAD] ✅ Cập nhật plate từ vehicle_crop detection: {plate}")
                                else:
                                    print(f"[VIOLATION THREAD] ⚠️ Invalid plate crop coordinates after padding")
                            else:
                                print(f"[VIOLATION THREAD] ⚠️ Invalid plate bbox: ({px1}, {py1}, {px2}, {py2})")
                        else:
                            print(f"[VIOLATION THREAD] ⚠️ Plate bbox không hợp lệ từ detection")
                    else:
                        print(f"[VIOLATION THREAD] ⚠️ Không detect được plate trên vehicle_crop")
                except Exception as e:
                    print(f"[VIOLATION THREAD] ⚠️ Lỗi detect plate trên vehicle_crop: {e}")
                    import traceback
                    traceback.print_exc()
            
            # Fallback: Nếu không detect được, sử dụng plate_crop từ alpr_realtime_worker
            if plate_crop is None and violation_data.get('plate_crop') is not None:
                plate_crop = violation_data.get('plate_crop')
                print(f"[VIOLATION THREAD] ⚠️ Fallback: sử dụng plate_crop từ alpr_realtime_worker")
            # ============================================================================
            # CREATE 5-SECOND VIOLATION VIDEO (FFmpeg + OpenCV hybrid)
            # ============================================================================
            video_clean_path = None

            # DEBUG: Check current_video_path
            # print(f"[VIDEO DEBUG] current_video_path = {current_video_path}")
            # print(f"[VIDEO DEBUG] exists = {os.path.exists(current_video_path) if current_video_path else False}")

            if current_video_path and os.path.exists(current_video_path):
                try:
                    # Get violation info - Priority: từ violation_data (đã được thêm bởi best_frame_selector)
                    print(f"[VIDEO DEBUG] ===== START VIDEO CREATION DEBUG =====")
                    print(f"[VIDEO DEBUG] track_id = {track_id}")
                    print(f"[VIDEO DEBUG] violation_data keys = {list(violation_data.keys())}")

                    violation_timestamp = violation_data.get('violation_timestamp')
                    violation_frame_num = violation_data.get('violation_frame')

                    print(f"[VIDEO DEBUG] violation_timestamp from queue data = {violation_timestamp}")
                    print(f"[VIDEO DEBUG] violation_frame_num from queue data = {violation_frame_num}")

                    # Fallback: lấy từ violation_frame_buffer nếu chưa có
                    if violation_timestamp is None and violation_frame_num is None:
                        print(f"[VIDEO DEBUG] ⚠️ Data from queue is None, trying buffer fallback...")
                        violation_info = violation_frame_buffer.get(track_id, {})
                        print(f"[VIDEO DEBUG] violation_info from buffer = {violation_info}")
                        violation_timestamp = violation_info.get('violation_timestamp')
                        violation_frame_num = violation_info.get('violation_frame')
                        print(f"[VIDEO DEBUG] violation_timestamp from buffer = {violation_timestamp}")
                        print(f"[VIDEO DEBUG] violation_frame_num from buffer = {violation_frame_num}")
                        print(f"[VIDEO DEBUG] Using violation info from buffer")
                    else:
                        print(f"[VIDEO DEBUG] ✅ Using violation info from queue data")

                    # DEBUG: Check violation info
                    print(f"[VIDEO DEBUG] FINAL violation_timestamp = {violation_timestamp}")
                    print(f"[VIDEO DEBUG] FINAL violation_frame_num = {violation_frame_num}")
                    print(f"[VIDEO DEBUG] ===== END VIDEO CREATION DEBUG =====")

                    if violation_timestamp is None and violation_frame_num is None:
                        print(f"[VIOLATION THREAD] ⚠️  No violation info for track {track_id}")
                        print(f"[VIOLATION THREAD] ⚠️  Cannot create video without timestamp or frame number")
                    else:
                        # Generate organized folder structure: YYYY/MM/DD/plate/
                        from datetime import datetime
                        now = datetime.now()

                        # Get normalized plate for folder name
                        plate_folder = normalize_plate(plate) if plate else f"UNKNOWN_{track_id}"
                        # Replace invalid characters for folder name
                        plate_folder = plate_folder.replace('/', '_').replace('\\', '_').replace(':', '_')

                        # Create date-based folder structure
                        date_folder = os.path.join(
                            "static/violation_videos",
                            now.strftime("%Y"),
                            now.strftime("%m"),
                            now.strftime("%d"),
                            plate_folder
                        )
                        os.makedirs(date_folder, exist_ok=True)

                        # Generate filename with datetime
                        timestamp_str = now.strftime("%Y%m%d_%H%M%S")
                        video_clean_name = f"violation_{timestamp_str}_{track_id}.mp4"
                        video_clean_path = os.path.join(date_folder, video_clean_name)

                        print(f"[VIDEO] 📁 Organized path: {date_folder}")
                        print(f"[VIDEO] 📝 Filename: {video_clean_name}")

                        # Initialize video_created flag
                        video_created = False

                        # DEBUG: Log conditions for video creation
                        print(f"[VIDEO DEBUG] ===== VIDEO CREATION CONDITIONS =====")
                        print(f"[VIDEO DEBUG] FFMPEG_AVAILABLE = {FFMPEG_AVAILABLE}")
                        print(f"[VIDEO DEBUG] violation_timestamp = {violation_timestamp}")
                        print(f"[VIDEO DEBUG] violation_frame_num = {violation_frame_num}")
                        print(f"[VIDEO DEBUG] video_created (initial) = {video_created}")
                        print(f"[VIDEO DEBUG] =====================================")

                        # ========================================
                        # METHOD 1: Try FFmpeg first (FASTEST + BEST QUALITY)
                        # ========================================
                        if FFMPEG_AVAILABLE and violation_timestamp is not None:
                            print(f"[VIDEO DEBUG] → Entering FFmpeg block")
                            # Calculate extraction window (2s before + 3s after = 5s)
                            pre_duration = 2.0
                            total_duration = 5.0
                            start_time = max(0, violation_timestamp - pre_duration)

                            print(f"[VIOLATION THREAD] 🎬 Creating video with FFmpeg:")
                            print(f"   - Violation at: {violation_timestamp:.2f}s")
                            print(f"   - Extract from: {start_time:.2f}s to {start_time + total_duration:.2f}s")

                            success, message = create_video_with_ffmpeg(
                                source_video_path=current_video_path,
                                output_path=video_clean_path,
                                start_time=start_time,
                                duration=total_duration
                            )

                            if success:
                                print(f"[VIOLATION THREAD] ✅ Video created with FFmpeg: {message}")
                                video_created = True
                            else:
                                print(f"[VIOLATION THREAD] ⚠️  FFmpeg failed: {message}")
                                print(f"[VIOLATION THREAD] 🔄 Falling back to OpenCV...")
                                video_clean_path = None

                        # ========================================
                        # METHOD 2: Fallback to OpenCV (if FFmpeg not available or failed)
                        # ========================================
                        print(f"[VIDEO DEBUG] Checking OpenCV condition: video_created={video_created}, violation_frame_num={violation_frame_num}")
                        if not video_created and violation_frame_num is not None:
                            print(f"[VIDEO DEBUG] → Entering OpenCV block")
                            print(f"[VIOLATION THREAD] 🎬 Creating video with OpenCV:")
                            print(f"   - Source: {current_video_path}")
                            print(f"   - Violation frame: {violation_frame_num}")

                            cap_source = cv2.VideoCapture(current_video_path)

                            if not cap_source.isOpened():
                                print(f"[VIOLATION THREAD] ❌ Cannot open source video")
                            else:
                                # Get video properties
                                source_fps = cap_source.get(cv2.CAP_PROP_FPS)
                                source_width = int(cap_source.get(cv2.CAP_PROP_FRAME_WIDTH))
                                source_height = int(cap_source.get(cv2.CAP_PROP_FRAME_HEIGHT))
                                total_frames = int(cap_source.get(cv2.CAP_PROP_FRAME_COUNT))

                                print(f"   - FPS: {source_fps}, Resolution: {source_width}x{source_height}")

                                # Calculate frame range (2s before + 3s after = 5s)
                                pre_frames = int(source_fps * 2.0)
                                post_frames = int(source_fps * 3.0)

                                start_frame = max(0, violation_frame_num - pre_frames)
                                end_frame = min(total_frames, violation_frame_num + post_frames)

                                total_extract_frames = end_frame - start_frame

                                print(f"   - Extract frames: {start_frame} to {end_frame} ({total_extract_frames} frames)")

                                # Seek to start frame
                                cap_source.set(cv2.CAP_PROP_POS_FRAMES, start_frame)

                                # Initialize VideoWriter
                                fourcc = cv2.VideoWriter_fourcc(*'mp4v')
                                out = cv2.VideoWriter(
                                    video_clean_path,
                                    fourcc,
                                    source_fps,
                                    (source_width, source_height)
                                )

                                if not out.isOpened():
                                    print(f"[VIOLATION THREAD] ❌ Cannot create VideoWriter")
                                    cap_source.release()
                                    video_clean_path = None
                                else:
                                    # Extract and write frames
                                    frames_written = 0
                                    current_frame = start_frame

                                    while current_frame < end_frame:
                                        ret, frame = cap_source.read()
                                        if not ret:
                                            print(f"[VIOLATION THREAD] ⚠️  End of video at frame {current_frame}")
                                            break

                                        out.write(frame)
                                        frames_written += 1
                                        current_frame += 1

                                        # Progress every 30 frames
                                        if frames_written % 30 == 0:
                                            print(f"   - Progress: {frames_written}/{total_extract_frames} frames")

                                    # Release resources
                                    out.release()
                                    cap_source.release()

                                    # Verify output
                                    if os.path.exists(video_clean_path) and os.path.getsize(video_clean_path) > 0:
                                        file_size = os.path.getsize(video_clean_path) / 1024
                                        actual_duration = frames_written / source_fps

                                        print(f"[VIOLATION THREAD] ✅ Video created with OpenCV:")
                                        print(f"   - File: {video_clean_name}")
                                        print(f"   - Frames: {frames_written}")
                                        print(f"   - Duration: {actual_duration:.2f}s")
                                        print(f"   - Size: {file_size:.1f} KB")
                                        video_created = True
                                    else:
                                        print(f"[VIOLATION THREAD] ❌ Output file empty")
                                        video_clean_path = None
                        else:
                            print(f"[VIDEO DEBUG] ❌ Skipped OpenCV block:")
                            print(f"[VIDEO DEBUG]    - video_created = {video_created}")
                            print(f"[VIDEO DEBUG]    - violation_frame_num = {violation_frame_num}")

                except Exception as e:
                    print(f"[VIOLATION THREAD] ❌ Error creating video: {e}")
                    import traceback
                    traceback.print_exc()
                    video_clean_path = None
            else:
                print(f"[VIOLATION THREAD] ⚠️  Source video not available")
                video_clean_path = None

            # ============================================================================
            # Continue with existing code (save images, database, telegram)
            # ============================================================================

            normalized_plate = normalize_plate(plate) if plate else None
            is_plate_valid = normalized_plate and is_valid_plate(normalized_plate)

            # SKIP violations without valid plate number (UNKNOWN vehicles)
            if not is_plate_valid:
                # print(f"[VIOLATION THREAD] ⏭️ Skipping violation without valid plate: track_id={track_id}")
                continue

            # Check cooldown for valid plates
            can_save = can_save_violation(track_id, plate)
            # print(f"[VIOLATION THREAD] can_save_violation(plate={plate}) = {can_save}")
            if not can_save:
                # print(f"[VIOLATION THREAD] ⏳ Skip duplicate: track_id={track_id}, plate={plate}")
                continue

            # Generate organized folder structure for images: YYYY/MM/DD/plate/
            from datetime import datetime
            now = datetime.now()

            # Get normalized plate for folder name
            plate_folder = normalize_plate(plate) if plate else f"UNKNOWN_{track_id}"
            # Replace invalid characters for folder name
            plate_folder = plate_folder.replace('/', '_').replace('\\', '_').replace(':', '_')

            # Create date-based folder structure (same as video)
            images_folder = os.path.join(
                "static/violation_videos",
                now.strftime("%Y"),
                now.strftime("%m"),
                now.strftime("%d"),
                plate_folder
            )
            os.makedirs(images_folder, exist_ok=True)

            # Generate filename with datetime
            timestamp_str = now.strftime("%Y%m%d_%H%M%S")
            vehicle_img_path = None
            plate_img_path = None

            if vehicle_crop.size > 0:
                vehicle_img_name = f"vehicle_{timestamp_str}_{track_id}.jpg"
                vehicle_img_path = os.path.join(images_folder, vehicle_img_name)
                cv2.imwrite(vehicle_img_path, vehicle_crop)
                print(f"[VIOLATION THREAD] ✅ Đã lưu ảnh xe: {images_folder}/{vehicle_img_name}")
            else:
                print(f"[VIOLATION THREAD] ⚠️ Không thể crop ảnh xe, bỏ qua vi phạm")
                continue

            if plate_crop is not None and plate_crop.size > 0:
                plate_img_name = f"plate_{timestamp_str}_{track_id}.jpg"
                plate_img_path = os.path.join(images_folder, plate_img_name)
                cv2.imwrite(plate_img_path, plate_crop)
                print(f"[VIOLATION THREAD] ✅ Đã lưu ảnh biển số: {images_folder}/{plate_img_name}")
            else:
                print(f"[VIOLATION THREAD] ⚠️ Không có ảnh biển số crop, chỉ gửi ảnh xe")

            violation_id = None
            try:
                with app.app_context():
                    conn = mysql.connection
                    if conn:
                        cursor = conn.cursor()

                        normalized_plate = normalize_plate(plate) if plate else None
                        exceeded = speed - speed_limit if speed > speed_limit else 0

                        owner_name = None
                        address = None
                        phone = None

                        if normalized_plate:
                            try:
                                cursor.execute("""
                                    SELECT owner_name, address, phone
                                    FROM vehicle_registry
                                    WHERE plate_number = %s
                                """, (normalized_plate,))
                                result = cursor.fetchone()
                                if result:
                                    owner_name = result.get('owner_name')
                                    address = result.get('address')
                                    phone = result.get('phone')
                            except Exception as e:
                                print(f"[VIOLATION THREAD] ⚠️ Không thể lấy thông tin chủ xe từ vehicle_registry: {e}")
                                owner_name = None
                                address = None
                                phone = None

                        # Save relative paths from static/ folder for database
                        # Format: violation_videos/YYYY/MM/DD/plate/filename.ext
                        # IMPORTANT: Convert backslashes to forward slashes for web compatibility
                        if vehicle_img_path:
                            vehicle_img_name = vehicle_img_path.replace('static/', '').replace('static\\', '').replace('\\', '/')
                        else:
                            vehicle_img_name = None

                        if plate_img_path:
                            plate_img_name = plate_img_path.replace('static/', '').replace('static\\', '').replace('\\', '/')
                        else:
                            plate_img_name = None

                        if video_clean_path:
                            video_name = video_clean_path.replace('static/', '').replace('static\\', '').replace('\\', '/')
                        else:
                            video_name = None

                        print(f"[DATABASE] 💾 Paths to save:")
                        print(f"   - Vehicle: {vehicle_img_name}")
                        print(f"   - Plate: {plate_img_name}")
                        print(f"   - Video: {video_name}")
                        
                        if normalized_plate:
                            try:
                                cursor.execute("SELECT plate FROM vehicle_owner WHERE plate = %s", (normalized_plate,))
                                existing_owner = cursor.fetchone()

                                if existing_owner:
                                    if owner_name or address or phone:
                                        cursor.execute("""
                                            UPDATE vehicle_owner
                                            SET owner_name = COALESCE(%s, owner_name),
                                                address = COALESCE(%s, address),
                                                phone = COALESCE(%s, phone)
                                            WHERE plate = %s
                                        """, (owner_name, address, phone, normalized_plate))
                                else:
                                    cursor.execute("""
                                        INSERT INTO vehicle_owner (plate, owner_name, address, phone)
                                        VALUES (%s, %s, %s, %s)
                                    """, (normalized_plate, owner_name, address, phone))
                                conn.commit()
                                print(f"[VIOLATION THREAD] ✅ Đã lưu/cập nhật thông tin chủ xe: {normalized_plate}")
                            except Exception as e:
                                print(f"[VIOLATION THREAD] ⚠️ Lỗi khi lưu thông tin chủ xe: {e}")
                                conn.rollback()

                        # FIX: Cho phép lưu vi phạm ngay cả khi không có plate (dùng NULL hoặc track_id)
                        db_plate = normalized_plate if normalized_plate else f"UNKNOWN_{track_id}"
                        cursor.execute("""
                            INSERT INTO violations
                            (plate, vehicle_class, speed, speed_limit, image, plate_image, video, status, time)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, 'pending', %s)
                        """, (
                            db_plate, vehicle_class,
                            round(speed, 2), speed_limit,
                            vehicle_img_name, plate_img_name, video_name,
                            get_vietnam_time().strftime('%Y-%m-%d %H:%M:%S')
                        ))

                        conn.commit()
                        violation_id = cursor.lastrowid
                        cursor.close()
                        print(f"[VIOLATION THREAD] ✅ Đã lưu vào database: violation_id={violation_id}")
            except Exception as e:
                print(f"[VIOLATION THREAD] Lỗi lưu database: {e}")
                import traceback
                traceback.print_exc()

            final_plate = normalized_plate if normalized_plate else plate

            # FIX: Cho phép gửi Telegram ngay cả khi không có plate (dùng track_id)
            if not final_plate:
                final_plate = f"UNKNOWN_{track_id}"
                print(f"[VIOLATION THREAD] ⚠️ Không có biển số, dùng track_id: {final_plate}")

            if not vehicle_img_path or not os.path.exists(vehicle_img_path):
                print(f"[VIOLATION THREAD] ❌ Bỏ qua vi phạm: Không có ảnh vi phạm xe (track_id={track_id}, path={vehicle_img_path})")
                continue

            telegram_data = {
                'violation_id': violation_id,
                'plate': final_plate,
                'speed': speed,
                'limit': speed_limit,
                'vehicle_type': vehicle_class,
                'exceeded': exceeded,
                'vehicle_image_path': vehicle_img_path,
                'plate_image_path': plate_img_path,
                'video_path': video_clean_path,
                'owner_name': owner_name,
                'address': address,
                'phone': phone,
                'timestamp': timestamp
            }

            try:
                telegram_queue.put(telegram_data, block=False)
                print(f"[VIOLATION THREAD] ✅ Đã đẩy vào telegram_queue: plate={final_plate}, owner={owner_name}, ảnh={vehicle_img_path}")
            except queue.Full:
                print(f"[VIOLATION THREAD] ⚠️ Telegram queue đầy, bỏ qua")

        except queue.Empty:
            continue
        except Exception as e:
            print(f"[VIOLATION THREAD] Lỗi: {e}")
            import traceback
            traceback.print_exc()
            time.sleep(0.1)

# ======================
# THREAD 1: VIDEO THREAD
# ======================
def video_thread():
    """
    THREAD 1: VideoThread (video_reader) - OPTIMIZED FOR OFFLINE VIDEO
    - Đọc video NHANH NHẤT có thể (KHÔNG delay theo FPS)
    - Push frame vào detection_queue mỗi N frame (DETECTION_FREQUENCY)
    - Lưu frame gốc vào original_frame_buffer
    - Timestamp CHÍNH XÁC từ frame_number / fps

    🎯 TỐI ƯU CHO OFFLINE VIDEO:
    ✅ Đọc >1000 FPS nếu có thể
    ✅ Timestamp = frame_number / fps
    ✅ KHÔNG time.sleep() delay
    ✅ Video mượt, không giật
    """
    global cap, camera_running, original_frame_buffer, detection_queue, video_fps, cap_lock, DETECTION_FREQUENCY, DETECTION_SCALE, current_video_path, stream_queue_clean, alpr_proactive_queue, active_tracks, active_tracks_lock

    # Kiểm tra có video path không
    if current_video_path is None:
        print("[VIDEO THREAD] ⚠️  current_video_path is None, waiting for video upload...")
        # Chờ tối đa 10 giây cho video upload
        wait_time = 0
        max_wait = 10.0
        while camera_running and current_video_path is None and wait_time < max_wait:
            time.sleep(0.5)
            wait_time += 0.5

        if current_video_path is None:
            print("[VIDEO THREAD] ❌ No video path available after waiting, stopping...")
            return

    print(f"[VIDEO THREAD] 🎬 Starting OfflineVideoReader for: {current_video_path}")
    print(f"[VIDEO THREAD] Detection frequency: {DETECTION_FREQUENCY} (every {DETECTION_FREQUENCY} frame(s))")
    print(f"[VIDEO THREAD] Detection scale: {DETECTION_SCALE * 100}%")

    # Tạo OfflineVideoReader instance
    try:
        reader = OfflineVideoReader(
            video_path=current_video_path,
            detection_queue=detection_queue,
            original_frame_buffer=original_frame_buffer,
            detection_frequency=DETECTION_FREQUENCY,
            detection_scale=DETECTION_SCALE,
            cap_lock=cap_lock
        )

        reader.start(
            stream_queue_clean=stream_queue_clean,
            alpr_proactive_queue=alpr_proactive_queue,
            alpr_frequency=3,
            active_tracks=active_tracks,
            active_tracks_lock=active_tracks_lock
        )
        
        time.sleep(0.5)

        if reader.cap and reader.cap.isOpened():
            info = reader.get_info()
            print(f"[VIDEO THREAD] 📹 Video: {info['width']}x{info['height']} @ {info['fps']:.2f} FPS")
            print(f"[VIDEO THREAD] 📹 Duration: {info['duration']:.2f}s ({info['total_frames']} frames)")
            print(f"[VIDEO THREAD] ⚡ Reading at MAXIMUM speed (NO FPS delay)")
        else:
            print(f"[VIDEO THREAD] ⚠️ Reader started but video not opened")

        print(f"[VIDEO THREAD] ⏳ Waiting for video to finish (camera_running={camera_running}, reader.running={reader.running})")
        while camera_running and reader.running:
            if not reader.running:
                print("[VIDEO THREAD] ⚠️ Reader stopped unexpectedly")
                break
            if reader.thread and not reader.thread.is_alive():
                print("[VIDEO THREAD] ⚠️ Reader thread stopped")
                break
            time.sleep(0.1)

        print("[VIDEO THREAD] 🛑 Stopping video reader...")
        reader.stop()

        # FIX: Khi video hết, tự động dừng detection và tất cả worker threads
        print("[VIDEO THREAD] 🛑 Video finished, stopping all detection workers...")
        camera_running = False
        print("[VIDEO THREAD] ✅ Video thread stopped, camera_running = False")

    except Exception as e:
        print(f"[VIDEO THREAD] ❌ Error: {e}")
        import traceback
        traceback.print_exc()


# ======================
# THREAD 2: FRAME CAPTURE THREAD - REMOVED (DUPLICATE)
# ======================
# ĐÃ XÓA: Thread này duplicate với video_thread()
# video_thread() đã đọc frame và push vào detection_queue rồi


# ======================
# THREAD 4: ALPR WORKER THREAD
# ======================
def alpr_worker_thread():
    """
    THREAD 4: ALPR Worker Thread (async, non-realtime)
    - Đọc ảnh vi phạm đã lưu trong database từ alpr_queue
    - Chạy Fast-ALPR để nhận dạng biển số chính xác
    - Cập nhật lại database với biển số chuẩn
    - Không ảnh hưởng đến FPS của video
    """
    global alpr_worker_running, plate_detector_post

    alpr_worker_running = True
    print("[ALPR WORKER THREAD] ✅ Đã khởi động - Xử lý ALPR async, không block video")

    while alpr_worker_running:
        try:
            # Lấy ảnh vi phạm từ queue (blocking, đợi đến khi có)
            violation_data = alpr_queue.get(timeout=1)

            if violation_data is None:  # Signal để dừng
                break

            violation_id = violation_data.get('violation_id')
            violation_img_path = violation_data.get('violation_img_path')
            vehicle_img_path = violation_data.get('vehicle_img_path')
            video_path = violation_data.get('video_path')
            speed = violation_data.get('speed')
            speed_limit = violation_data.get('speed_limit')
            vehicle_class = violation_data.get('vehicle_class')
            track_id = violation_data.get('track_id')

            print(f"[ALPR WORKER] 🔍 Đang xử lý vi phạm ID {violation_id} (Còn {alpr_queue.qsize()} trong hàng đợi)")

            # Gọi hàm xử lý ALPR (đã có sẵn)
            process_plate_from_saved_image(
                violation_id, violation_img_path, vehicle_img_path, video_path,
                speed, speed_limit, vehicle_class, track_id
            )

            print(f"[ALPR WORKER] ✅ Đã xử lý xong vi phạm ID {violation_id}")

            # Đánh dấu task đã hoàn thành
            alpr_queue.task_done()

            # Delay nhỏ giữa các lần xử lý để tránh quá tải
            time.sleep(0.1)

        except queue.Empty:
            # Timeout - tiếp tục vòng lặp
            continue
        except Exception as e:
            print(f"[ALPR WORKER ERROR] {e}")
            import traceback
            traceback.print_exc()
            # Đánh dấu task đã hoàn thành ngay cả khi lỗi
            try:
                alpr_queue.task_done()
            except:
                pass

    print("[ALPR WORKER THREAD] ⏹️ Đã dừng")

def start_alpr_worker():
    """Khởi động ALPR worker thread"""
    global alpr_worker_thread_obj, alpr_worker_running

    if alpr_worker_thread_obj is None or not alpr_worker_thread_obj.is_alive():
        alpr_worker_thread_obj = threading.Thread(target=alpr_worker_thread, daemon=True)
        alpr_worker_thread_obj.start()
        print("[ALPR WORKER] 🚀 Đã khởi động ALPR worker thread")

alpr_worker_thread_obj = None

# ======================
# START ALL THREADS - 6 THREAD ARCHITECTURE
# ======================
def start_video_thread():
    """
    Khởi động 6 thread độc lập (OPTIMIZED ARCHITECTURE):

    Thread 1: VIDEO THREAD
      ↓ (detection_queue)
    Thread 2: DETECTION WORKER (YOLO + OC-SORT + SpeedTracker)
      ↓ (alpr_realtime_queue)
    Thread 3: ALPR WORKER (FastALPR detect biển số)
      ↓ (best_frame_queue)
    Thread 4: BEST FRAME SELECTOR (Chọn frame tốt nhất)
      ↓ (violation_queue)
    Thread 5: VIOLATION WORKER (Lưu DB + ảnh + video)
      ↓ (telegram_queue)
    Thread 6: TELEGRAM WORKER (Gửi thông báo)
    """
    global camera_running
    
    print("=" * 60)
    print("[THREAD MANAGER] 🚀 KHỞI ĐỘNG DUAL-STREAM ARCHITECTURE")
    print("=" * 60)

    try:
        if 'video_stream_thread' in globals() and video_stream_thread.is_alive():
            print("[THREAD 1] ⚠️ Video thread đang chạy, không tạo mới")
        else:
            video_stream_thread = threading.Thread(target=video_thread, daemon=True)
            video_stream_thread.start()
            print("[THREAD 1] ✅ Video Thread → detection_queue + stream_queue_clean + alpr_proactive_queue")
    except Exception as e:
        print(f"[THREAD 1] ❌ Error: {e}")
        import traceback
        traceback.print_exc()

    # THREAD 2: Detection Worker Thread (YOLO + Tracking + Speed)
    try:
        detection_worker_thread = threading.Thread(target=detection_worker, daemon=True)
        detection_worker_thread.start()
        print("[THREAD 2] ✅ Detection Worker → alpr_realtime_queue")
    except Exception as e:
        print(f"[THREAD 2] ❌ Error: {e}")

    try:
        alpr_proactive_thread = threading.Thread(target=alpr_proactive_worker, daemon=True)
        alpr_proactive_thread.start()
        print("[THREAD 3] ✅ ALPR Proactive Worker → alpr_proactive_cache")
    except Exception as e:
        print(f"[THREAD 3] ❌ Error: {e}")

    try:
        alpr_realtime_thread = threading.Thread(target=alpr_realtime_worker, daemon=True)
        alpr_realtime_thread.start()
        print("[THREAD 4] ✅ ALPR Realtime Worker → best_frame_queue")
    except Exception as e:
        print(f"[THREAD 4] ❌ Error: {e}")

    try:
        best_frame_thread = threading.Thread(target=best_frame_selector_worker, daemon=True)
        best_frame_thread.start()
        print("[THREAD 5] ✅ Best Frame Selector → violation_queue")
    except Exception as e:
        print(f"[THREAD 5] ❌ Error: {e}")

    try:
        violation_worker_thread = threading.Thread(target=violation_worker, daemon=True)
        violation_worker_thread.start()
        print("[THREAD 6] ✅ Violation Worker → telegram_queue")
    except Exception as e:
        print(f"[THREAD 6] ❌ Error: {e}")

    try:
        if not telegram_worker_running:
            telegram_worker_thread_obj = threading.Thread(target=telegram_worker, daemon=True)
            telegram_worker_thread_obj.start()
            print("[THREAD 7] ✅ Telegram Worker → Gửi thông báo")
    except Exception as e:
        print(f"[THREAD 7] ❌ Error: {e}")

    print("=" * 60)
    print("[THREAD MANAGER] ✅ TẤT CẢ 7 THREAD ĐÃ KHỞI ĐỘNG!")
    print("=" * 60)

# ======================
# VIDEO GENERATOR (STREAM TO WEB)
# ======================
# Tối ưu streaming: resize frame và giảm JPEG quality để stream mượt hơn
STREAM_WIDTH = 1280
STREAM_JPEG_QUALITY = 80
STREAM_FPS = 30

def video_generator_smooth():
    """Stream mượt (clean) - KHÔNG có bbox, độ trễ thấp, 30-60 FPS"""
    global stream_queue_clean, camera_running

    print("[VIDEO STREAM SMOOTH] 🎬 Starting smooth stream...")

    while True:
        try:
            if not stream_queue_clean.empty():
                frame = stream_queue_clean.get(timeout=0.1)
                encode_params = [int(cv2.IMWRITE_JPEG_QUALITY), 85]
                _, buffer = cv2.imencode('.jpg', frame, encode_params)
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n'
                       b'Content-Length: ' + str(len(buffer)).encode() + b'\r\n\r\n'
                       + buffer.tobytes() + b'\r\n')
            else:
                black_frame = np.zeros((720, 1280, 3), dtype=np.uint8)
                text = "Loading smooth stream..."
                font = cv2.FONT_HERSHEY_SIMPLEX
                cv2.putText(black_frame, text, (400, 360), font, 1.2, (0, 255, 255), 2)
                encode_params = [int(cv2.IMWRITE_JPEG_QUALITY), 85]
                _, buffer = cv2.imencode('.jpg', black_frame, encode_params)
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n'
                       b'Content-Length: ' + str(len(buffer)).encode() + b'\r\n\r\n'
                       + buffer.tobytes() + b'\r\n')
                time.sleep(0.03)

        except Exception as e:
            print(f"[VIDEO STREAM SMOOTH] ❌ Error: {e}")
            time.sleep(0.1)

def video_generator():
    """
    Stream Admin - Detection stream: Có bounding box, text overlay, thông tin tốc độ
    Dùng để hiển thị trên giao diện web (frontend) hoặc trả về cho admin
    TỐI ƯU: Lấy frame trực tiếp từ admin_frame_buffer thay vì stream_queue để mượt hơn
    """
    global cap, camera_running, admin_frame_buffer, video_fps

    print("[VIDEO STREAM] 🎬 Starting video stream generator...")

    # Luôn chạy stream, không phụ thuộc vào camera_running
    # Điều này cho phép stream hiển thị "Waiting..." khi chưa có video
    while True:
        try:
            # Kiểm tra xem có frame trong buffer không
            has_frame = False
            frame = None

            if 'global' in admin_frame_buffer and len(admin_frame_buffer['global']) > 0:
                try:
                    frame_data = admin_frame_buffer['global'][-1]  # Lấy frame mới nhất
                    frame = frame_data['frame'] if isinstance(frame_data, dict) else frame_data
                    if frame is not None:
                        has_frame = True
                except (IndexError, KeyError, TypeError):
                    pass

            if not has_frame or frame is None:
                # Không có frame, hiển thị thông báo chờ
                black_frame = np.zeros((480, 854, 3), dtype=np.uint8)  # 16:9 aspect ratio

                # Vẽ background gradient
                for i in range(480):
                    color = int(20 + i * 0.05)
                    cv2.line(black_frame, (0, i), (854, i), (color, color, color + 10), 1)

                # Vẽ text
                if camera_running:
                    text = "Loading video stream..."
                    color = (0, 255, 255)  # Cyan
                else:
                    text = "Waiting for video upload..."
                    color = (100, 100, 100)  # Gray

                # Tính vị trí text để căn giữa
                font = cv2.FONT_HERSHEY_SIMPLEX
                font_scale = 0.8
                thickness = 2
                text_size = cv2.getTextSize(text, font, font_scale, thickness)[0]
                text_x = (854 - text_size[0]) // 2
                text_y = (480 + text_size[1]) // 2

                cv2.putText(black_frame, text, (text_x, text_y), font, font_scale, color, thickness)

                # Thêm icon loading nếu đang chạy
                if camera_running:
                    # Vẽ vòng tròn loading
                    import math
                    angle = (time.time() * 2) % (2 * math.pi)
                    cx, cy = 427, 200
                    radius = 30
                    for i in range(8):
                        a = angle + i * math.pi / 4
                        x = int(cx + radius * math.cos(a))
                        y = int(cy + radius * math.sin(a))
                        alpha = 1.0 - i * 0.1
                        cv2.circle(black_frame, (x, y), 5, (int(255*alpha), int(255*alpha), 0), -1)

                encode_params = [int(cv2.IMWRITE_JPEG_QUALITY), 70]
                _, jpeg = cv2.imencode(".jpg", black_frame, encode_params)
                yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg.tobytes() + b"\r\n")
                time.sleep(0.1)  # Chờ 100ms trước khi thử lại
                continue

            # Có frame, stream nó
            # TỐI ƯU: Resize frame trước khi encode để stream nhanh hơn
            original_h, original_w = frame.shape[:2]
            if original_w > STREAM_WIDTH:
                scale = STREAM_WIDTH / original_w
                new_w = STREAM_WIDTH
                new_h = int(original_h * scale)
                frame = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_LINEAR)

            # TỐI ƯU: Encode JPEG với quality thấp hơn để nhanh hơn
            encode_params = [int(cv2.IMWRITE_JPEG_QUALITY), STREAM_JPEG_QUALITY]
            _, jpeg = cv2.imencode(".jpg", frame, encode_params)

            yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg.tobytes() + b"\r\n")

            # TỐI ƯU: Sleep nhỏ để không chiếm hết CPU
            time.sleep(0.01)

        except GeneratorExit:
            print("[VIDEO STREAM] 🛑 Stream closed by client")
            break
        except Exception as e:
            print(f"[VIDEO STREAM] ⚠️ Error: {e}")
            time.sleep(0.1)

    print("[VIDEO STREAM] 🏁 Stream ended")

def video_generator_clean():
    """
    Stream User (Vi phạm) - Clean stream: Frame gốc, không có bounding box, không có overlay
    Dùng để test/debug (video clean thực tế được gửi qua Telegram từ violation_frame_buffer)
    """
    global cap, camera_running, original_frame_buffer, video_fps

    # Tính delay dựa trên FPS để video chạy đúng tốc độ
    target_fps = video_fps if video_fps > 0 else STREAM_FPS
    frame_delay = 1.0 / target_fps  # Thời gian delay giữa các frame

    last_frame_time = time.time()

    while camera_running:
        if cap is None:
            time.sleep(0.1)
            continue
        if 'global' not in original_frame_buffer or len(original_frame_buffer['global']) == 0:
            # Nếu không có frame, tạo frame đen để stream không bị lỗi
            black_frame = np.zeros((480, 640, 3), dtype=np.uint8)
            cv2.putText(black_frame, "Waiting for video...", (50, 240),
                       cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
            encode_params = [int(cv2.IMWRITE_JPEG_QUALITY), STREAM_JPEG_QUALITY]
            _, jpeg = cv2.imencode(".jpg", black_frame, encode_params)
            yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg.tobytes() + b"\r\n")
            time.sleep(0.1)
            continue

        # Điều chỉnh tốc độ stream theo FPS của video
        current_time = time.time()
        elapsed = current_time - last_frame_time

        if elapsed < frame_delay:
            time.sleep(frame_delay - elapsed)

        last_frame_time = time.time()

        # Lấy frame từ buffer - an toàn với try-except
        try:
            if 'global' in original_frame_buffer and len(original_frame_buffer['global']) > 0:
                frame_data = original_frame_buffer['global'][-1]  # Frame gốc (KHÔNG CÓ BOUNDING BOX)
                frame = frame_data['frame'] if isinstance(frame_data, dict) else frame_data
            else:
                raise IndexError("No frame in buffer")
        except (IndexError, TypeError, KeyError):
            # Nếu buffer rỗng hoặc lỗi, tạo frame đen
            black_frame = np.zeros((480, 640, 3), dtype=np.uint8)
            cv2.putText(black_frame, "No frame available", (50, 240),
                       cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
            encode_params = [int(cv2.IMWRITE_JPEG_QUALITY), STREAM_JPEG_QUALITY]
            _, jpeg = cv2.imencode(".jpg", black_frame, encode_params)
            yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg.tobytes() + b"\r\n")
            time.sleep(0.1)
            continue

        # TỐI ƯU: Resize frame trước khi encode để stream nhanh hơn
        original_h, original_w = frame.shape[:2]
        if original_w > STREAM_WIDTH:
            scale = STREAM_WIDTH / original_w
            new_w = STREAM_WIDTH
            new_h = int(original_h * scale)
            frame = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_LINEAR)

        # TỐI ƯU: Encode JPEG với quality thấp hơn để nhanh hơn
        encode_params = [int(cv2.IMWRITE_JPEG_QUALITY), STREAM_JPEG_QUALITY]
        _, jpeg = cv2.imencode(".jpg", frame, encode_params)

        yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg.tobytes() + b"\r\n")

    if cap:
        try: cap.release()
        except: pass

# ======================








# ROUTES
# ======================
@app.route("/")
@login_required
def index():
    """Trang chủ - hiển thị camera và dashboard - TỐI ƯU: 1 query thay vì 3"""
    try:
        conn = mysql.connection
        if not conn:
            print("[ERROR] Database connection is None")
            return render_template("index.html", total=0, vehicles=0, avg_speed=0)

        cursor = conn.cursor()
        # TỐI ƯU: Gộp 3 queries thành 1 query duy nhất để tăng tốc
        cursor.execute("""
            SELECT
                COUNT(*) AS total,
                COUNT(DISTINCT plate) AS vehicles,
                COALESCE(AVG(speed), 0) AS avg_speed
            FROM violations
            WHERE plate IS NOT NULL
            AND plate_image IS NOT NULL
            AND DATE(time) = CURDATE()
        """)
        result = cursor.fetchone()
        cursor.close()

        total = result["total"] if result else 0
        vehicles = result["vehicles"] if result else 0
        avg_speed = round(result["avg_speed"] or 0, 2)

        return render_template("index.html", total=total, vehicles=vehicles, avg_speed=avg_speed)
    except Exception as e:
        print(f"[ERROR] index route: {e}")
        import traceback
        traceback.print_exc()
        # Fallback values nếu có lỗi
        return render_template("index.html", total=0, vehicles=0, avg_speed=0)

@app.route("/video_feed_smooth")
def video_feed_smooth():
    """Stream mượt (clean) - KHÔNG có bbox, độ trễ thấp, 30-60 FPS"""
    return Response(video_generator_smooth(), mimetype="multipart/x-mixed-replace; boundary=frame")

@app.route("/video_feed")
def video_feed():
    """Stream Admin - Detection stream: Có bounding box, text overlay"""
    return Response(video_generator(), mimetype="multipart/x-mixed-replace; boundary=frame")

@app.route("/video_feed_clean")
def video_feed_clean():
    """Stream Clean - Frame gốc không có bounding box"""
    return Response(video_generator_clean(), mimetype="multipart/x-mixed-replace; boundary=frame")

@app.route("/detection_stream")
def detection_stream():
    """
    SSE Stream: Detection data (bbox, speed, plate) cho Canvas Overlay
    
    Format:
    {
        "detections": [
            {
                "track_id": 15,
                "bbox": [120, 300, 450, 680],
                "speed": 85.3,
                "class": "car",
                "plate": "30A12345",
                "violation": true
            }
        ],
        "video_resolution": [1920, 1080],
        "speed_limit": 40,
        "timestamp": 1234567890.123
    }
    """
    def generate():
        global current_detections, speed_limit, current_video_path
        
        # Lấy video resolution từ video reader
        video_resolution = [1920, 1080]  # Default
        if current_video_path and os.path.exists(current_video_path):
            try:
                cap = cv2.VideoCapture(current_video_path)
                if cap.isOpened():
                    video_resolution = [
                        int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
                        int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                    ]
                    cap.release()
            except:
                pass
        
        while True:
            try:
                # Format detections từ current_detections dict
                detections_list = []
                for track_id, det in current_detections.items():
                    vehicle_bbox = det.get('vehicle_bbox', [])
                    if len(vehicle_bbox) == 4:
                        x1, y1, x2, y2 = vehicle_bbox
                        speed = det.get('speed')
                        vehicle_class = det.get('vehicle_class', 'vehicle')
                        plate = det.get('plate', '')
                        
                        det_data = {
                            'track_id': track_id,
                            'bbox': [int(x1), int(y1), int(x2), int(y2)],
                            'speed': float(speed) if speed is not None else None,
                            'class': vehicle_class,
                            'plate': plate if plate else '',
                            'violation': speed is not None and speed > speed_limit
                        }
                        detections_list.append(det_data)
                
                # Gửi data qua SSE
                data = {
                    'detections': detections_list,
                    'video_resolution': video_resolution,
                    'speed_limit': speed_limit,
                    'timestamp': time.time()
                }
                
                yield f"data: {json.dumps(data)}\n\n"
                
                # Update 20 FPS (50ms interval)
                time.sleep(0.05)
                
            except Exception as e:
                print(f"[DETECTION STREAM] Error: {e}")
                time.sleep(0.1)
    
    return Response(
        generate(),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
            'Connection': 'keep-alive'
        }
    )

@app.route("/upload_video", methods=["POST"])
@login_required
def upload_video():
    """Tối ưu: Upload video nhanh, async processing, immediate response"""
    global cap, tracker, camera_running, video_fps, current_video_path

    print("[VIDEO UPLOAD] 📥 Received upload request")
    print(f"[VIDEO UPLOAD] Content-Type: {request.content_type}")
    print(f"[VIDEO UPLOAD] Content-Length: {request.content_length}")

    try:
        # Kiểm tra file có tồn tại không
        if "video" not in request.files:
            print("[VIDEO UPLOAD] ❌ No file in request.files")
            print(f"[VIDEO UPLOAD] Available keys: {list(request.files.keys())}")
            return jsonify({"status": "error", "msg": "Không có file được upload. Vui lòng chọn file video."})

        file = request.files["video"]

        if file.filename == '':
            print("[VIDEO UPLOAD] ❌ Empty filename")
            return jsonify({"status": "error", "msg": "Chưa chọn file. Vui lòng chọn file video để upload."})

        allowed_extensions = ('.mp4', '.avi', '.mov', '.mkv', '.flv', '.wmv')
        if not file.filename.lower().endswith(allowed_extensions):
            print(f"[VIDEO UPLOAD] ❌ Invalid file format: {file.filename}")
            return jsonify({
                "status": "error",
                "msg": f"Định dạng file không hợp lệ. Chỉ chấp nhận: {', '.join(allowed_extensions)}"
            })

        # Kiểm tra kích thước file (nếu có thể)
        file_size = 0
        try:
            # Thử đọc Content-Length từ header
            content_length = request.headers.get('Content-Length')
            if content_length:
                file_size = int(content_length)
                max_size = 500 * 1024 * 1024  # 500MB
                if file_size > max_size:
                    print(f"[VIDEO UPLOAD] ❌ File too large: {file_size / 1024 / 1024:.2f} MB")
                    return jsonify({
                        "status": "error",
                        "msg": f"File quá lớn ({file_size / 1024 / 1024:.2f} MB). Giới hạn tối đa là 500MB."
                    })
        except (ValueError, TypeError):
            # Nếu không đọc được size từ header, bỏ qua (sẽ kiểm tra khi lưu file)
            pass

        if file_size > 0:
            print(f"[VIDEO UPLOAD] 📤 Starting upload: {file.filename} ({file_size / 1024 / 1024:.2f} MB)")
        else:
            print(f"[VIDEO UPLOAD] 📤 Starting upload: {file.filename}")

        # TỐI ƯU: Dừng video/camera hiện tại nếu đang chạy (async, không block)
        def stop_current_video():
            global cap, camera_running, cap_lock
            camera_running = False
            # Đợi thread cũ dừng (tối đa 2 giây)
            time.sleep(1.0)
            # Sử dụng lock để release VideoCapture an toàn
            with cap_lock:
                if cap:
                    try:
                        cap.release()
                        print("[VIDEO UPLOAD] ✅ Old video capture released")
                    except Exception as e:
                        print(f"[VIDEO UPLOAD] ⚠️ Error releasing old capture: {e}")
                    cap = None
            time.sleep(0.5)  # Đợi thêm để đảm bảo thread cũ đã dừng hoàn toàn

        # Chạy async để không block upload
        stop_thread = threading.Thread(target=stop_current_video, daemon=True)
        stop_thread.start()

        # Lưu file video (chunked write để nhanh hơn với file lớn)
        save_path = os.path.join(UPLOAD_FOLDER, "uploaded.mp4")
        try:
            # Tối ưu: Chunked write cho file lớn
            chunk_size = 8192  # 8KB chunks
            total_written = 0
            max_size = 500 * 1024 * 1024  # 500MB

            with open(save_path, 'wb') as f:
                while True:
                    chunk = file.stream.read(chunk_size)
                    if not chunk:
                        break
                    total_written += len(chunk)

                    # Kiểm tra kích thước trong khi upload
                    if total_written > max_size:
                        f.close()
                        if os.path.exists(save_path):
                            os.remove(save_path)
                        print(f"[VIDEO UPLOAD] ❌ File too large during upload: {total_written / 1024 / 1024:.2f} MB")
                        return jsonify({
                            "status": "error",
                            "msg": f"File quá lớn ({total_written / 1024 / 1024:.2f} MB). Giới hạn tối đa là 500MB."
                        })

                    f.write(chunk)

            saved_size = os.path.getsize(save_path)
            print(f"[VIDEO UPLOAD] ✅ File saved to: {save_path} ({saved_size / 1024 / 1024:.2f} MB)")
        except Exception as e:
            print(f"[VIDEO UPLOAD] ❌ Error saving file: {e}")
            import traceback
            traceback.print_exc()
            # Xóa file nếu có lỗi
            if os.path.exists(save_path):
                try:
                    os.remove(save_path)
                except:
                    pass
            return jsonify({"status": "error", "msg": f"Lỗi khi lưu file: {str(e)}"})

        # Kiểm tra file có tồn tại không
        if not os.path.exists(save_path):
            return jsonify({"status": "error", "msg": "File was not saved successfully"})

        # TỐI ƯU: Xử lý video trong thread riêng để không block response
        def process_video_async():
            global cap, tracker, camera_running, video_fps, admin_frame_buffer, original_frame_buffer, cap_lock, is_video_upload_mode, detection_queue, current_video_path

            try:
                # Đợi thread dừng hoàn tất (tối đa 3 giây)
                stop_thread.join(timeout=3.0)

                # TỐI ƯU: Bật video upload mode để tối ưu tốc độ
                is_video_upload_mode = True
                print("[VIDEO UPLOAD] 🚀 Bật video upload mode - Tối ưu tốc độ xử lý")

                # TỐI ƯU: Tăng queue size khi upload video (tập trung tài nguyên)
                new_queue_size = get_detection_queue_size()
                if len(detection_queue) > 0:
                    # Tạo queue mới với size lớn hơn
                    old_queue = list(detection_queue)
                    detection_queue.clear()
                    detection_queue = deque(maxlen=new_queue_size)
                    # Không cần giữ lại frame cũ, bắt đầu fresh
                else:
                    detection_queue = deque(maxlen=new_queue_size)
                print(f"[VIDEO UPLOAD] ✅ Detection queue size: {new_queue_size} (tối ưu cho video upload)")

                # TỐI ƯU: Clear buffers để tránh frame cũ
                admin_frame_buffer.clear()  # Clear dict
                original_frame_buffer.clear()  # Clear dict
                # Clear stream_queue và violation_queue
                while not stream_queue.empty():
                    try:
                        stream_queue.get_nowait()
                    except queue.Empty:
                        break
                while not violation_queue.empty():
                    try:
                        violation_queue.get_nowait()
                    except queue.Empty:
                        break

                # ========================================
                # TỐI ƯU: Set current_video_path TRƯỚC khi start video thread
                # OfflineVideoReader sẽ tự mở video, không cần mở ở đây
                # ========================================
                # Set current_video_path TRƯỚC để video_thread() có thể bắt đầu ngay
                current_video_path = save_path

                # Lấy thông tin video nhanh để log (không cần lock vì chỉ đọc)
                temp_cap = cv2.VideoCapture(save_path)
                if temp_cap.isOpened():
                    video_fps = temp_cap.get(cv2.CAP_PROP_FPS) or 30
                    if video_fps <= 0:
                        video_fps = 30
                    video_width = int(temp_cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                    video_height = int(temp_cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                    total_frames = int(temp_cap.get(cv2.CAP_PROP_FRAME_COUNT))
                    temp_cap.release()
                    
                    print(f"[VIDEO UPLOAD] ✅ Video info: {video_width}x{video_height} @ {video_fps:.2f} FPS")
                    print(f"[VIDEO UPLOAD] Total frames: {total_frames} ({total_frames / video_fps:.2f}s)")
                else:
                    print(f"[VIDEO UPLOAD] ⚠️ Cannot read video info, using defaults")
                    video_fps = 30
                    video_width = 0
                    video_height = 0
                    total_frames = 0
                
                # video_fps đã được set ở trên và đã khai báo global ở đầu function

                # Khởi tạo tracker với pixel_to_meter phù hợp cho video upload
                tracker = SpeedTracker(pixel_to_meter=0.2)

                # QUAN TRỌNG: Set camera_running = True TRƯỚC khi start thread
                # Đảm bảo video_thread() không bị block
                camera_running = True
                print(f"[VIDEO UPLOAD] ✅ Set camera_running = True, current_video_path = {current_video_path}")
                
                # Start video thread (sẽ dùng OfflineVideoReader)
                start_video_thread()

                print("[VIDEO UPLOAD] ✅ Video processing started successfully")
            except Exception as e:
                print(f"[VIDEO UPLOAD] ❌ Error processing video: {e}")
                import traceback
                traceback.print_exc()
                camera_running = False
                with cap_lock:
                    if cap:
                        try:
                            cap.release()
                        except:
                            pass
                        cap = None

        # Chạy xử lý video trong thread riêng
        process_thread = threading.Thread(target=process_video_async, daemon=True)
        process_thread.start()

        # Trả về ngay lập tức (không chờ xử lý xong)
        return jsonify({"status": "ok", "msg": "upload_success", "processing": "Video đang được xử lý..."})

    except Exception as e:
        print(f"[VIDEO UPLOAD] ❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        camera_running = False
        if cap:
            try:
                cap.release()
            except:
                pass
            cap = None
        return jsonify({"status": "error", "msg": f"Unexpected error: {str(e)}"})

@app.route("/open_camera")
def open_camera():
    global cap, tracker, camera_running, video_fps, cap_lock, is_video_upload_mode, detection_queue
    camera_running = False
    is_video_upload_mode = False  # Tắt video upload mode khi mở camera
    # Reset queue size về mặc định
    detection_queue = deque(maxlen=get_detection_queue_size())
    time.sleep(0.5)  # Đợi thread cũ dừng
    with cap_lock:
        if cap:
            try:
                cap.release()
            except:
                pass
        cap = cv2.VideoCapture(0)
    # Camera thường chạy ở 30fps
    video_fps = 30
    tracker = SpeedTracker(pixel_to_meter=0.13)
    camera_running = True
    start_video_thread()
    return {"status": "ok"}

@app.route("/stop_camera")
def stop_camera():
    global cap, camera_running, cap_lock
    camera_running = False
    time.sleep(0.5)  # Đợi thread dừng
    with cap_lock:
        if cap:
            try:
                cap.release()
            except:
                pass
            cap = None
    return {"status": "ok"}

@app.route("/stop_video_upload")
def stop_video_upload():
    global cap, camera_running, is_video_upload_mode, detection_queue
    camera_running = False
    is_video_upload_mode = False  # Tắt video upload mode
    # Reset queue size về mặc định
    detection_queue = deque(maxlen=get_detection_queue_size())
    print("[VIDEO UPLOAD] 🛑 Đã dừng video upload, tắt tối ưu mode")
    if cap:
        try: cap.release()
        except: pass
        cap = None
    return {"status": "ok"}

# ======================
# HISTORY & AUTOCOMPLETE
# ======================
@app.route("/history")
@login_required
def history():
    """Trang lịch sử vi phạm - TỐI ƯU: Thêm LIMIT và index để query nhanh"""
    try:
        conn = mysql.connection
        if not conn:
            print("[ERROR] Database connection is None in history route")
            return render_template("view_violations.html", rows=[], violation_count=0)

        cursor = conn.cursor()
        plate = request.args.get("plate", "").strip()
        from_date = request.args.get("from_date", "").strip()
        to_date = request.args.get("to_date", "").strip()
        speed_over = request.args.get("speed_over", "").strip()

        # TỐI ƯU: Query với LIMIT để tránh load quá nhiều dữ liệu
        # CHỈ LẤY VI PHẠM CÓ BIỂN SỐ VIỆT NAM HỢP LỆ
        # Lấy dữ liệu từ bảng violations và JOIN với vehicle_owner để lấy thông tin chủ xe
        # Bảng violations KHÔNG có owner_name, address, phone - chỉ có trong vehicle_owner
        query = """SELECT v.id,
                      v.plate,
                      v.speed,
                      v.speed_limit,
                      v.image,
                      v.plate_image,
                      v.video,
                      v.time,
                      v.status,
                      v.vehicle_class,
                      o.owner_name,
                      o.address,
                      o.phone
               FROM violations v
               LEFT JOIN vehicle_owner o ON v.plate = o.plate
               WHERE v.plate IS NOT NULL
                 AND v.plate_image IS NOT NULL
                 AND (
                   -- Xe cá nhân: 2 số + 1 chữ + 5 số
                   v.plate REGEXP '^[0-9]{2}[A-Z][0-9]{5}$'
                   OR
                   -- Xe công vụ: 2 số + 2 chữ + 4 số
                   v.plate REGEXP '^[0-9]{2}[A-Z]{2}[0-9]{4}$'
                   OR
                   -- Xe ngoại giao: 2 số + NG + 4 số
                   v.plate REGEXP '^[0-9]{2}NG[0-9]{4}$'
                   OR
                   -- Xe quân đội/tạm thời: 2 số + 1 chữ + 4 số
                   v.plate REGEXP '^[0-9]{2}[A-Z][0-9]{4}$'
                 )"""
        params = []
        if plate:
            params.append(f"%{plate}%")
            query += " AND v.plate LIKE %s"
        if from_date:
            params.append(f"{from_date} 00:00:00")
            query += " AND v.time >= %s"
        if to_date:
            params.append(f"{to_date} 23:59:59")
            query += " AND v.time <= %s"
        if speed_over:
            params.append(float(speed_over))
            query += " AND v.speed > %s"

        # TỐI ƯU: Thêm LIMIT để chỉ load 100 records đầu tiên (có thể pagination sau)
        query += " ORDER BY v.time DESC LIMIT 100"
        cursor.execute(query, params)
        rows = cursor.fetchall()

        # TỐI ƯU: Chỉ count khi có filter (không cần count nếu không filter)
        violation_count = len(rows)
        if plate:
            cursor.execute("SELECT COUNT(*) AS cnt FROM violations v WHERE v.plate LIKE %s", (f"%{plate}%",))
            violation_count = cursor.fetchone()["cnt"]

        cursor.close()
        return render_template("view_violations.html", rows=rows, violation_count=violation_count)
    except Exception as e:
        print(f"[ERROR] history route: {e}")
        import traceback
        traceback.print_exc()
        return render_template("view_violations.html", rows=[], violation_count=0)

@app.route("/autocomplete")
def autocomplete():
    try:
        term = request.args.get("q", "").upper()
        conn = mysql.connection
        if not conn:
            return jsonify([])

        cursor = conn.cursor()
        cursor.execute("SELECT plate FROM vehicle_owner WHERE plate LIKE %s LIMIT 5", ("%" + term + "%",))
        rows = cursor.fetchall()
        cursor.close()
        return jsonify([row["plate"] for row in rows])
    except Exception as e:
        print(f"[ERROR] autocomplete route: {e}")
        return jsonify([])

@app.route("/violations")
def get_violations():
    """Tối ưu: Query nhanh với index, limit kết quả"""
    try:
        conn = mysql.connection
        if not conn:
            print("[ERROR] Database connection is None in get_violations route")
            return jsonify([])

        cursor = conn.cursor()
        # TỐI ƯU: Sử dụng index trên (plate, plate_image, time) để query nhanh hơn
        # QUAN TRỌNG: Phải SELECT v.plate_image để hiển thị ảnh biển số
        # CHỈ LẤY VI PHẠM CÓ BIỂN SỐ VIỆT NAM HỢP LỆ
        # Lấy dữ liệu từ bảng violations và JOIN với vehicle_owner để lấy thông tin chủ xe
        # Bảng violations KHÔNG có owner_name, address, phone - chỉ có trong vehicle_owner
        cursor.execute("""SELECT v.id,
                          v.plate,
                          v.speed,
                          v.speed_limit,
                          v.image,
                          v.plate_image,
                          v.time,
                          v.status,
                          v.vehicle_class,
                          o.owner_name,
                          o.address,
                          o.phone
                          FROM violations v
                          LEFT JOIN vehicle_owner o ON v.plate = o.plate
                          WHERE v.plate IS NOT NULL
                            AND v.plate_image IS NOT NULL
                            AND (
                              -- Xe cá nhân: 2 số + 1 chữ + 5 số
                              v.plate REGEXP '^[0-9]{2}[A-Z][0-9]{5}$'
                              OR
                              -- Xe công vụ: 2 số + 2 chữ + 4 số
                              v.plate REGEXP '^[0-9]{2}[A-Z]{2}[0-9]{4}$'
                              OR
                              -- Xe ngoại giao: 2 số + NG + 4 số
                              v.plate REGEXP '^[0-9]{2}NG[0-9]{4}$'
                              OR
                              -- Xe quân đội/tạm thời: 2 số + 1 chữ + 4 số
                              v.plate REGEXP '^[0-9]{2}[A-Z][0-9]{4}$'
                            )
                          ORDER BY v.time DESC LIMIT 20""")
        results = cursor.fetchall()
        cursor.close()
        return jsonify(results)
    except Exception as e:
        print(f"[ERROR] get_violations: {e}")
        return jsonify([])

@app.route("/view_violations")
@login_required
def view_violations():
    """Redirect về /history (đã được thay thế bằng view_violations.html)"""
    return redirect(url_for("history"))

@app.route("/get_stats")
def get_stats():
    """TỐI ƯU: Gộp tất cả queries thành 1 query duy nhất"""
    try:
        conn = mysql.connection
        if not conn:
            print("[ERROR] Database connection is None in get_stats route")
            return jsonify({"total": 0, "vehicles": 0, "avg_speed": 0})

        cursor = conn.cursor()
        # TỐI ƯU: Gộp 4 queries thành 1 query duy nhất
        cursor.execute("""
            SELECT
                COUNT(*) AS total,
                COUNT(DISTINCT plate) AS vehicles,
                COALESCE(AVG(speed), 0) AS avg_speed
            FROM violations
            WHERE plate IS NOT NULL AND plate_image IS NOT NULL
        """)
        stats = cursor.fetchone()

        # Query recent violations riêng (cần ORDER BY)
        cursor.execute("""
            SELECT plate, speed, time
            FROM violations
            WHERE plate IS NOT NULL AND plate_image IS NOT NULL
            ORDER BY time DESC
            LIMIT 5
        """)
        recent = cursor.fetchall()
        cursor.close()

        return jsonify({
            "total": stats["total"] if stats else 0,
            "vehicles": stats["vehicles"] if stats else 0,
            "avg_speed": round(stats["avg_speed"] or 0, 2),
            "recent": recent
        })
    except Exception as e:
        print(f"[ERROR] get_stats: {e}")
        return jsonify({"total": 0, "vehicles": 0, "avg_speed": 0, "recent": []})

@app.route("/stream")
def stream():
    global last_id
    def event_stream():
        global last_id
        while True:
            try:
                with app.app_context():
                    conn = mysql.connection
                    cursor = conn.cursor()
                    cursor.execute("""SELECT v.id, v.plate, v.speed, v.speed_limit, v.image, v.plate_image, v.video, v.time,
                                      o.owner_name, o.address, o.phone
                                      FROM violations v
                                      LEFT JOIN vehicle_owner o ON v.plate=o.plate
                                      WHERE v.plate IS NOT NULL AND v.plate_image IS NOT NULL
                                      ORDER BY v.id DESC LIMIT 1""")
                    row = cursor.fetchone()
                    cursor.close()
                    if row and row["id"] != last_id:
                        last_id = row["id"]
                        yield f"data: {json.dumps(row, default=str)}\n\n"
            except Exception as e:
                print(f"[ERROR] stream: {e}")
            # TỐI ƯU: Tăng sleep từ 1 giây lên 2 giây để giảm tải
            time.sleep(2)
    return Response(event_stream(), mimetype='text/event-stream')





#-----------------HOME------------
# ---------------- LOGIN ----------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        try:
            username = request.form["username"]
            password = request.form["password"]

            conn = mysql.connection
            if not conn:
                return render_template("login.html", error="Không thể kết nối database. Vui lòng kiểm tra MySQL đã chạy chưa.")

            cur = conn.cursor()
            cur.execute("SELECT * FROM users WHERE username=%s", (username,))
            user = cur.fetchone()
            cur.close()

            if user and password == user["password"]:
                session["user"] = user["username"]
                session["role"] = user["role"]
                return redirect(url_for("index"))

            return render_template("login.html", error="Sai tài khoản hoặc mật khẩu")
        except Exception as e:
            print(f"[ERROR] Login error: {e}")
            import traceback
            traceback.print_exc()
            return render_template("login.html", error=f"Lỗi đăng nhập: {str(e)}")

    return render_template("login.html")


# ---------------- HOME (trang chính) ----------------
@app.route("/home")
@login_required
def home():
    return render_template("home.html", user=session["user"], role=session["role"])


# ---------------- LOGOUT ----------------
@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")

# ---------------- DELETE: CHỈ ADMIN ----------------
@app.route("/delete/<plate>")
@admin_required
def delete_violation(plate):
    conn = mysql.connection
    cursor = conn.cursor()

    # xóa trong violations trước
    cursor.execute("DELETE FROM violations WHERE plate=%s", (plate,))
    conn.commit()

    # xóa trong owner
    cursor.execute("DELETE FROM vehicle_owner WHERE plate=%s", (plate,))
    conn.commit()

    return redirect(url_for("history"))

@app.route("/admin/vehicles")
@require_role("admin")
def manage_vehicle():
    """TỐI ƯU: Thêm LIMIT để tránh load quá nhiều dữ liệu"""
    try:
        # Lấy filter parameters từ request
        plate = request.args.get('plate', '').strip()
        owner_name = request.args.get('owner_name', '').strip()
        address = request.args.get('address', '').strip()
        phone = request.args.get('phone', '').strip()

        # Build query với filters
        cursor = mysql.connection.cursor()
        query = "SELECT * FROM vehicle_owner WHERE 1=1"
        params = []

        if plate:
            query += " AND plate LIKE %s"
            params.append(f"%{plate}%")

        if owner_name:
            query += " AND owner_name LIKE %s"
            params.append(f"%{owner_name}%")

        if address:
            query += " AND address LIKE %s"
            params.append(f"%{address}%")

        if phone:
            query += " AND phone LIKE %s"
            params.append(f"%{phone}%")

        # TỐI ƯU: Thêm LIMIT để chỉ load 200 records đầu tiên
        query += " ORDER BY plate ASC LIMIT 200"

        cursor.execute(query, params)
        data = cursor.fetchall()
        cursor.close()

        return render_template("admin_vehicle.html", data=data,
                              plate=plate, owner_name=owner_name,
                              address=address, phone=phone)
    except Exception as e:
        print(f"[ERROR] manage_vehicle: {e}")
        return render_template("admin_vehicle.html", data=[],
                              plate='', owner_name='', address='', phone='')

#------------------------------SỬA CHỦ XE----------------------
@app.route("/edit_owner/<plate>", methods=["GET", "POST"])
@admin_required
def edit_owner(plate):
    """TỐI ƯU: Thêm error handling và cursor.close()"""
    try:
        cursor = mysql.connection.cursor()

        if request.method == "POST":
            owner_name = request.form.get("owner_name", "").strip()
            address = request.form.get("address", "").strip()
            phone = request.form.get("phone", "").strip()

            cursor.execute("""
                UPDATE vehicle_owner
                SET owner_name=%s, address=%s, phone=%s
                WHERE plate=%s
            """, (owner_name, address, phone, plate))
            mysql.connection.commit()
            cursor.close()

            # Trả về JSON để hiển thị popup (không redirect)
            return jsonify({"status": "success", "message": "Đã sửa thông tin chủ xe thành công!"})

        cursor.execute("SELECT * FROM vehicle_owner WHERE plate=%s", (plate,))
        owner = cursor.fetchone()
        cursor.close()

        return render_template("edit_owner.html", owner=owner)
    except Exception as e:
        print(f"[ERROR] edit_owner: {e}")
        if 'cursor' in locals():
            cursor.close()
        return jsonify({"status": "error", "message": f"Lỗi: {e}"}), 500

#----------------------------------SỬA VI PHẠM--------------
@app.route("/edit_violation/<int:id>", methods=["GET", "POST"])
@admin_required
def edit_violation(id):
    """TỐI ƯU: Thêm error handling và cursor.close()"""
    try:
        cursor = mysql.connection.cursor()

        if request.method == "POST":
            speed = request.form.get("speed", "0")
            limit = request.form.get("limit", "40")

            cursor.execute("""
                UPDATE violations
                SET speed=%s, speed_limit=%s
                WHERE id=%s
            """, (float(speed), float(limit), id))
            mysql.connection.commit()
            cursor.close()

            return redirect("/history")

        cursor.execute("SELECT * FROM violations WHERE id=%s", (id,))
        data = cursor.fetchone()
        cursor.close()

        return render_template("edit_violation.html", data=data)
    except Exception as e:
        print(f"[ERROR] edit_violation: {e}")
        if 'cursor' in locals():
            cursor.close()
        return redirect("/history")

@app.route("/check_permission")
def check_permission():
    role = session.get("role")   # admin / user

    if role == "admin":
        return jsonify({"allowed": True})
    else:
        return jsonify({"allowed": False})

@app.route("/static/img/<filename>")
def serve_img(filename):
    """Serve images from img folder"""
    try:
        # Thử tìm trong static/img trước
        static_img_path = os.path.join("static", "img", filename)
        if os.path.exists(static_img_path):
            return send_from_directory("static/img", filename)
        # Nếu không có, thử tìm trong img/ (thư mục gốc)
        img_path = os.path.join("img", filename)
        if os.path.exists(img_path):
            return send_from_directory("img", filename)
        return jsonify({"error": f"Image not found: {filename}"}), 404
    except Exception as e:
        print(f"[ERROR] serve_img: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/violations/<path:filename>")
def serve_violation_file(filename):
    """
    Serve violation images, videos, and plate images from multiple locations:
    - violations/YYYY-MM-DD/PLATE/plate.jpg
    - static/uploads/ (vehicle images)
    - static/plate_images/ (plate images)
    - static/violation_videos/ (videos)
    """
    try:
        # Debug: Log incoming request (commented to reduce logs)
        # print(f"[SERVE FILE] Request: /violations/{filename}")
        # Thử tìm trong thư mục violations/ trước (cấu trúc cũ: violations/YYYY-MM-DD/PLATE/file)
        violations_path = os.path.join("violations", filename)
        if os.path.exists(violations_path):
            return send_from_directory("violations", filename)
        
        # Thử tìm trong static/uploads/ (vehicle images)
        # Strip 'violation_videos/' prefix if present
        clean_filename_uploads = filename.replace('violation_videos/', '').replace('violation_videos\\', '')
        uploads_path = os.path.join("static", "uploads", clean_filename_uploads)
        if os.path.exists(uploads_path):
            return send_from_directory("static/uploads", clean_filename_uploads)

        # Thử tìm trong static/plate_images/ (plate images)
        # Strip 'violation_videos/' prefix if present
        clean_filename_plate = filename.replace('violation_videos/', '').replace('violation_videos\\', '')
        plate_path = os.path.join("static", "plate_images", clean_filename_plate)
        if os.path.exists(plate_path):
            return send_from_directory("static/plate_images", clean_filename_plate)
        
        # Thử tìm trong static/violation_videos/ (videos)
        # Strip 'violation_videos/' prefix if present to avoid duplication
        clean_filename = filename.replace('violation_videos/', '').replace('violation_videos\\', '')
        # if clean_filename != filename:
        #     print(f"[SERVE FILE] Stripped prefix: '{filename}' → '{clean_filename}'")
        video_path = os.path.join("static", "violation_videos", clean_filename)
        # print(f"[SERVE FILE] Checking video path: {video_path} (exists: {os.path.exists(video_path)})")
        if os.path.exists(video_path):
            # Xác định MIME type cho video
            ext = os.path.splitext(filename)[1].lower()
            mime_types = {
                '.mp4': 'video/mp4',
                '.avi': 'video/x-msvideo',
                '.mov': 'video/quicktime',
                '.mkv': 'video/x-matroska',
                '.webm': 'video/webm'
            }
            mime_type = mime_types.get(ext, 'video/mp4')
            
            # Hỗ trợ Range requests cho video
            range_header = request.headers.get('Range', None)
            if range_header:
                # Xử lý Range request (giống serve_demo_video)
                file_size = os.path.getsize(video_path)
                start = 0
                end = file_size - 1
                
                range_match = range_header.replace('bytes=', '').split('-')
                if range_match[0]:
                    start = int(range_match[0])
                if range_match[1]:
                    end = int(range_match[1])
                
                content_length = end - start + 1
                
                with open(video_path, 'rb') as f:
                    f.seek(start)
                    data = f.read(content_length)
                
                response = make_response(data, 206)
                response.headers['Content-Type'] = mime_type
                response.headers['Content-Range'] = f'bytes {start}-{end}/{file_size}'
                response.headers['Accept-Ranges'] = 'bytes'
                response.headers['Content-Length'] = str(content_length)
                return response
            else:
                response = make_response(send_from_directory("static/violation_videos", clean_filename))
                response.headers['Content-Type'] = mime_type
                response.headers['Accept-Ranges'] = 'bytes'
                return response
        
        # 5. Nếu không tìm thấy theo đường dẫn đầy đủ, thử tìm theo tên file (basename)
        # Database có thể lưu đường dẫn như "2025-12-15/30G55473/plate.jpg" nhưng file thực tế ở "static/plate_images/plate_xxx.jpg"
        basename = os.path.basename(filename)
        
        # Thử tìm trong static/uploads/ (vehicle images) - theo tên file
        uploads_basename_path = os.path.join("static", "uploads", basename)
        if os.path.exists(uploads_basename_path):
            return send_from_directory("static/uploads", basename)
        
        # Thử tìm trong static/plate_images/ (plate images) - theo tên file
        plate_basename_path = os.path.join("static", "plate_images", basename)
        if os.path.exists(plate_basename_path):
            return send_from_directory("static/plate_images", basename)
        
        # Thử tìm trong static/violation_videos/ (videos) - theo tên file
        video_basename_path = os.path.join("static", "violation_videos", basename)
        if os.path.exists(video_basename_path):
            # Xử lý video với Range request
            ext = os.path.splitext(basename)[1].lower()
            mime_types = {
                '.mp4': 'video/mp4',
                '.avi': 'video/x-msvideo',
                '.mov': 'video/quicktime',
                '.mkv': 'video/x-matroska',
                '.webm': 'video/webm'
            }
            mime_type = mime_types.get(ext, 'video/mp4')
            
            range_header = request.headers.get('Range', None)
            if range_header:
                file_size = os.path.getsize(video_basename_path)
                range_match = re.match(r'bytes=(\d+)-(\d*)', range_header)
                if range_match:
                    start = int(range_match.group(1))
                    end = int(range_match.group(2)) if range_match.group(2) else file_size - 1
                    end = min(end, file_size - 1)
                    content_length = end - start + 1
                    
                    with open(video_basename_path, 'rb') as f:
                        f.seek(start)
                        data = f.read(content_length)
                    
                    response = make_response(data, 206)
                    response.headers['Content-Type'] = mime_type
                    response.headers['Content-Range'] = f'bytes {start}-{end}/{file_size}'
                    response.headers['Accept-Ranges'] = 'bytes'
                    response.headers['Content-Length'] = str(content_length)
                    return response
            else:
                response = make_response(send_from_directory("static/violation_videos", basename))
                response.headers['Content-Type'] = mime_type
                response.headers['Accept-Ranges'] = 'bytes'
                return response
        
        # Không tìm thấy file
        # print(f"[ERROR] Violation file not found: {filename} (also tried basename: {basename})")
        return jsonify({"error": f"File not found: {filename}"}), 404
        
    except Exception as e:
        print(f"[ERROR] serve_violation_file: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@app.route("/video_demo/<filename>")
def serve_demo_video(filename):
    """Serve demo videos from video_demo folder with proper MIME type and Range request support"""
    try:
        video_path = os.path.join("video_demo", filename)

        # Kiểm tra file có tồn tại không
        if not os.path.exists(video_path):
            print(f"[ERROR] Video not found: {video_path}")
            return jsonify({"error": f"Video not found: {filename}"}), 404

        # Xác định MIME type dựa trên extension
        mime_types = {
            '.mp4': 'video/mp4',
            '.avi': 'video/x-msvideo',
            '.mov': 'video/quicktime',
            '.mkv': 'video/x-matroska',
            '.webm': 'video/webm'
        }

        ext = os.path.splitext(filename)[1].lower()
        mime_type = mime_types.get(ext, 'video/mp4')

        # Hỗ trợ Range requests cho video seeking (HTML5 video cần điều này)
        range_header = request.headers.get('Range', None)
        if not range_header:
            # Nếu không có Range header, trả về toàn bộ file
            response = make_response(send_from_directory("video_demo", filename))
            response.headers['Content-Type'] = mime_type
            response.headers['Accept-Ranges'] = 'bytes'
            return response

        # Xử lý Range request
        file_size = os.path.getsize(video_path)
        start = 0
        end = file_size - 1

        # Parse Range header: "bytes=start-end"
        range_match = re.match(r'bytes=(\d+)-(\d*)', range_header)
        if range_match:
            start = int(range_match.group(1))
            if range_match.group(2):
                end = int(range_match.group(2))

        # Đảm bảo end không vượt quá file size
        end = min(end, file_size - 1)
        content_length = end - start + 1

        # Đọc phần file được yêu cầu
        with open(video_path, 'rb') as f:
            f.seek(start)
            data = f.read(content_length)

        # Tạo response với Range support
        response = Response(data, 206, mimetype=mime_type, direct_passthrough=True)
        response.headers.add('Content-Range', f'bytes {start}-{end}/{file_size}')
        response.headers.add('Accept-Ranges', 'bytes')
        response.headers.add('Content-Length', str(content_length))

        return response

    except Exception as e:
        print(f"[ERROR] Failed to serve video {filename}: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"Error serving video: {str(e)}"}), 500

# ======================
# ERROR HANDLERS
# ======================
from werkzeug.exceptions import RequestEntityTooLarge

@app.errorhandler(RequestEntityTooLarge)
def handle_file_too_large(e):
    """Xử lý lỗi khi file upload quá lớn"""
    print(f"[ERROR] File too large: {e}")
    return jsonify({
        "status": "error",
        "msg": f"File quá lớn! Giới hạn tối đa là 500MB. Vui lòng chọn file nhỏ hơn."
    }), 413

@app.errorhandler(413)
def handle_413(e):
    """Xử lý lỗi 413 Request Entity Too Large"""
    return jsonify({
        "status": "error",
        "msg": "File quá lớn! Giới hạn tối đa là 500MB."
    }), 413

@app.errorhandler(500)
def handle_500(e):
    """Xử lý lỗi server 500"""
    print(f"[ERROR] Server error: {e}")
    import traceback
    traceback.print_exc()
    return jsonify({
        "status": "error",
        "msg": "Lỗi server. Vui lòng thử lại sau."
    }), 500

# MAIN
# ======================
if __name__ == "__main__":
    # Lấy cấu hình từ environment variables hoặc dùng giá trị mặc định
    host = os.getenv('HOST', '0.0.0.0')
    port = int(os.getenv('PORT', 5000))
    debug = os.getenv('FLASK_DEBUG', 'False').lower() == 'true'

    print("=" * 60)
    print("🚗 PLATE VIOLATION SYSTEM - Starting...")
    print("=" * 60)
    print(f"📍 Server: http://{host}:{port}")
    print(f"🔧 Debug mode: {debug}")
    print(f"💾 Database: {app.config['MYSQL_HOST']}/{app.config['MYSQL_DB']}")
    print(f"📱 Telegram: {'Configured' if TELEGRAM_TOKEN else 'Not configured'}")
    print(f"🎯 Detection: Frequency={DETECTION_FREQUENCY}, Scale={DETECTION_SCALE}, Device={DEVICE}")

    # Khởi động Telegram worker thread
    start_telegram_worker()

    print("=" * 60)

    # Test database connection again before starting
    try:
        with app.app_context():
            conn = mysql.connection
            if conn:
                print("✅ Database ready")
            else:
                print("⚠️  Warning: Database connection may not be ready")
    except Exception as e:
        print(f"⚠️  Database warning: {e}")

    app.run(host=host, port=port, debug=debug, threaded=True)
