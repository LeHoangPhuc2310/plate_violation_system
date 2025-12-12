from flask import Flask, Response, render_template, request, jsonify, redirect, session, url_for, send_from_directory, make_response
from flask_mysqldb import MySQL
import cv2
import numpy as np
import time
import json
import os
import re
import requests
import threading
from collections import deque
import queue
from datetime import datetime, timezone, timedelta

from combined_detector import CombinedDetector
from speed_tracker import SpeedTracker
from detector import PlateDetector
# Thử import Enhanced Plate Detector (có fallback)
try:
    from enhanced_plate_detector import EnhancedPlateDetector
    ENHANCED_DETECTOR_AVAILABLE = True
except ImportError:
    ENHANCED_DETECTOR_AVAILABLE = False
    print(">>> ⚠️ Enhanced Plate Detector not available - using standard PlateDetector")

# ======================
# TIMEZONE CONFIG (Vietnam UTC+7)
# ======================
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

# ======================
# FLASK APP
# ======================
app = Flask(__name__)
app.secret_key = "your-secret-key-123"  # đổi nếu cần


# ======================
# DATABASE CONFIG
# ======================
# Sử dụng environment variables cho AWS deployment, fallback về local

app.config['MYSQL_HOST'] = os.getenv('MYSQL_HOST', 'localhost')
app.config['MYSQL_USER'] = os.getenv('MYSQL_USER', 'root')
app.config['MYSQL_PASSWORD'] = os.getenv('MYSQL_PASSWORD', '')
app.config['MYSQL_DB'] = os.getenv('MYSQL_DB', 'plate_violation')
app.config['MYSQL_CURSORCLASS'] = 'DictCursor'
app.config['MYSQL_CONNECT_TIMEOUT'] = 5  # TỐI ƯU: Giảm timeout từ 10 xuống 5 giây
# Cho phép upload video lớn (tối đa 500MB)
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  # 500MB

mysql = MySQL(app)

# Test database connection - NON-BLOCKING (trong thread riêng)
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

# Khởi động thread test DB (non-blocking)
db_test_thread = threading.Thread(target=test_db_connection_async, daemon=True)
db_test_thread.start()

# ======================
# GLOBAL VAR
# ======================
UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs("static/uploads", exist_ok=True)
os.makedirs("static/plate_images", exist_ok=True)  # Thư mục cho ảnh biển số
os.makedirs("static/violation_videos", exist_ok=True)  # Thư mục cho video vi phạm

cap = None
camera_running = False
last_id = 0
video_fps = 30  # FPS mặc định, sẽ được cập nhật từ video gốc
is_video_upload_mode = False  # Flag để phân biệt video upload vs camera (để tối ưu riêng)
# Thread lock để bảo vệ VideoCapture (không thread-safe)
cap_lock = threading.Lock()

# Auto-detect GPU và cấu hình detector - BẮT BUỘC GPU
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
        DETECTION_FREQUENCY = 1  # Detect mỗi frame để tracking kịp nhất
        DETECTION_SCALE = 1.0  # KHÔNG scale để tracking chính xác, GPU đủ mạnh
        admin_frame_buffer = deque(maxlen=90)  # Frame có bounding box + thông tin tốc độ (cho admin)
        original_frame_buffer = deque(maxlen=90)  # Frame gốc (cho crop xe/biển số)
        violation_frame_buffer = {}  # Dict: track_id -> deque of frames full màn hình CÓ bounding box (cho người vi phạm)
        sent_violation_tracks = set()  # Set các track_id đã gửi video để không gửi lại

    elif hasattr(torch.backends, 'mps') and torch.backends.mps.is_available():
        DEVICE = 'mps'
        print("🚀 GPU MPS (Apple Silicon) detected")
        DETECTION_FREQUENCY = 1  # Detect mỗi frame
        DETECTION_SCALE = 0.8  # Scale nhẹ để tăng tốc
        admin_frame_buffer = deque(maxlen=90)  # Frame có bounding box + thông tin tốc độ (cho admin)
        original_frame_buffer = deque(maxlen=90)  # Frame gốc (cho crop xe/biển số)
        violation_frame_buffer = {}  # Dict: track_id -> deque of frames full màn hình CÓ bounding box (cho người vi phạm)
        sent_violation_tracks = set()  # Set các track_id đã gửi video để không gửi lại
    else:
        # Cho phép chạy trên CPU với WARNING (không phải error)
        DEVICE = 'cpu'
        print("⚠️  WARNING: No GPU detected! System will run on CPU (SLOW performance)")
        print("⚠️  For optimal performance, please install CUDA and PyTorch with CUDA support:")
        print("    1. Install CUDA: https://developer.nvidia.com/cuda-downloads")
        print("    2. Install PyTorch with CUDA: pip install torch torchvision --index-url https://download.pytorch.org/whl/cu118")
        print("    3. Update GPU drivers")
        DETECTION_FREQUENCY = 1  # Detect mỗi frame
        DETECTION_SCALE = 0.7  # Scale để tăng tốc trên CPU
        admin_frame_buffer = deque(maxlen=60)  # Giảm buffer cho CPU
        original_frame_buffer = deque(maxlen=60)  # Giảm buffer cho CPU
        violation_frame_buffer = {}  # Dict: track_id -> deque of frames full màn hình CÓ bounding box (cho người vi phạm)
        sent_violation_tracks = set()  # Set các track_id đã gửi video để không gửi lại
except ImportError as e:
    print(f"⚠️  WARNING: PyTorch is not installed! Please install: pip install torch torchvision")
    print(f"    Error: {e}")
    print("⚠️  System will attempt to run without PyTorch (may cause errors)")
    DEVICE = 'cpu'
    DETECTION_FREQUENCY = 1
    DETECTION_SCALE = 0.7
    admin_frame_buffer = deque(maxlen=60)
    original_frame_buffer = deque(maxlen=60)
    violation_frame_buffer = {}
    sent_violation_tracks = set()
except Exception as e:
    print(f"⚠️  WARNING: Error detecting GPU: {e}")
    print("⚠️  System will run on CPU (SLOW performance)")
    DEVICE = 'cpu'
    DETECTION_FREQUENCY = 1
    DETECTION_SCALE = 0.7
    admin_frame_buffer = deque(maxlen=60)
    original_frame_buffer = deque(maxlen=60)
    violation_frame_buffer = {}
    sent_violation_tracks = set()

# LAZY LOADING: Chỉ khởi tạo detector khi cần (tránh block startup)
detector = None
tracker = None
plate_detector_post = None
speed_limit = 40
last_violation_time = {}
VIOLATION_COOLDOWN = 3  # giây

def init_detector():
    """Khởi tạo detector - LAZY LOAD (chỉ khi cần)"""
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
        # TỐI ƯU: pixel_to_meter được điều chỉnh theo từng nguồn video
        # Camera: 0.13, Video upload: 0.2 (sẽ được set lại khi upload video)
        tracker = SpeedTracker(pixel_to_meter=0.13)
        print(">>> ✅ SpeedTracker initialized!")
    
    if plate_detector_post is None:
        # Enhanced Plate Detector để đọc biển số từ ảnh vi phạm đã lưu
        # Sử dụng Fast-ALPR + EasyOCR fallback + nhiều preprocessing methods
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

# Tối ưu performance (đã được set dựa trên GPU/CPU)
# DETECTION_FREQUENCY và DETECTION_SCALE đã được set ở trên

# ======================
# TELEGRAM CONFIG
# ======================
# Sử dụng environment variables cho AWS deployment
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN', '8306836477:AAEJSaTQg2Pu7tZQMEHjoDPUSIC3Mz0QtGY')
TELEGRAM_CHAT_ID = int(os.getenv('TELEGRAM_CHAT_ID', '6680799636'))

# ======================
# TELEGRAM QUEUE
# ======================
# Hàng đợi để gửi Telegram tuần tự (gửi xong 1 vi phạm rồi mới gửi tiếp)
telegram_queue = queue.Queue()
telegram_worker_running = False
telegram_worker_thread = None

# ======================
# TELEGRAM WORKER THREAD
# ======================
def telegram_worker():
    """
    THREAD 4: Telegram Worker Thread (telegram_worker)
    - Lấy item từ telegram_queue
    - Gửi ảnh + video KHÔNG bounding box (clean)
    - KHÔNG sử dụng admin_frame_buffer
    - Đảm bảo gửi tuần tự để tránh spam API Telegram
    """
    global telegram_worker_running, speed_limit
    telegram_worker_running = True
    print("[TELEGRAM THREAD] ✅ Worker thread đã khởi động - sẵn sàng xử lý hàng đợi")
    
    while telegram_worker_running:
        try:
            # Lấy vi phạm từ queue (blocking, đợi đến khi có)
            violation_data = telegram_queue.get(timeout=1)
            
            if violation_data is None:  # Signal để dừng
                break
            
            # Xử lý cấu trúc dữ liệu mới từ violation_worker
            # Có thể có vehicle_image_path hoặc full_img_path (backward compatibility)
            full_img_path = violation_data.get('vehicle_image_path') or violation_data.get('full_img_path')
            plate_img_path = violation_data.get('plate_image_path') or violation_data.get('plate_img_path')
            video_path = violation_data.get('video_path')
            
            # Gửi Telegram alert với ảnh/video clean (không có bbox)
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
            
            # Đánh dấu task đã hoàn thành
            telegram_queue.task_done()
            
            # Delay nhỏ giữa các lần gửi để tránh spam Telegram API
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
    """Khởi động worker thread cho Telegram queue"""
    global telegram_worker_thread, telegram_worker_running
    
    if telegram_worker_thread is None or not telegram_worker_thread.is_alive():
        telegram_worker_thread = threading.Thread(target=telegram_worker, daemon=True)
        telegram_worker_thread.start()
        print("[TELEGRAM QUEUE] 🚀 Đã khởi động Telegram worker thread")

def queue_telegram_alert(plate, speed, limit, full_img_path, plate_img_path, video_path, owner_name, address, phone, vehicle_class="N/A", violation_id=None):
    """
    Thêm vi phạm vào hàng đợi Telegram (thay vì gửi trực tiếp)
    Worker thread sẽ xử lý tuần tự
    """
    # Đảm bảo worker thread đang chạy
    start_telegram_worker()
    
    # Thêm vào queue
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

# ======================


def admin_required(f):
    def wrapper(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("login"))

        if session.get("role") != "admin":
            # show alert và redirect về /history
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
    """
    Gửi cảnh báo vi phạm qua Telegram với đầy đủ thông tin BẮT BUỘC:
    1. Message text với thông tin chi tiết (BẮT BUỘC: plate, owner_name, address, phone)
    2. Ảnh phương tiện vi phạm (BẮT BUỘC: full_img_path phải có)
    3. Ảnh biển số (đã crop) - tùy chọn
    4. Video khoanh vùng đối tượng vi phạm - tùy chọn
    
    violation_id: ID của violation để cập nhật status sau khi gửi
    """
    try:
        if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
            print("[TELEGRAM] Token hoặc Chat ID chưa được cấu hình")
            # Cập nhật status thành 'failed' nếu không có config
            if violation_id:
                update_telegram_status(violation_id, 'failed')
            return
        
        # KIỂM TRA THÔNG TIN BẮT BUỘC
        if not plate:
            print("[TELEGRAM] ❌ BẮT BUỘC: Biển số không được để trống!")
            # Xóa ảnh nếu có
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
        
        # Validate biển số Việt Nam hợp lệ
        normalized_plate = normalize_plate(plate)
        if not is_valid_plate(normalized_plate):
            print(f"[TELEGRAM] ❌ BẮT BUỘC: Biển số không hợp lệ '{plate}' (normalized: {normalized_plate})")
            # XÓA ẢNH VÌ BIỂN SỐ KHÔNG HỢP LỆ
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
        
        # Sử dụng biển số đã normalize
        plate = normalized_plate
        
        if not full_img_path or not os.path.exists(full_img_path):
            print(f"[TELEGRAM] ❌ BẮT BUỘC: Ảnh vi phạm xe không tồn tại: {full_img_path}")
            # Xóa ảnh biển số nếu có
            if plate_img_path and os.path.exists(plate_img_path):
                try:
                    os.remove(plate_img_path)
                    print(f"[TELEGRAM] 🗑️ Đã xóa ảnh biển số vì không có ảnh xe: {plate_img_path}")
                except Exception as e:
                    print(f"[TELEGRAM] Lỗi xóa ảnh biển số: {e}")
            if violation_id:
                update_telegram_status(violation_id, 'failed')
            return
        
        # Thông tin chủ xe (có thể None nếu không có trong database)
        # Nhưng vẫn gửi được, chỉ hiển thị "N/A" hoặc "Chưa có thông tin"
        if not owner_name:
            owner_name = "Chưa có thông tin"
        if not address:
            address = "Chưa có thông tin"
        if not phone:
            phone = "Chưa có thông tin"
        
        # Đánh dấu đang gửi
        send_success = True
        
        # Kiểm tra và xử lý đường dẫn ảnh full frame
        if not full_img_path or not os.path.exists(full_img_path):
            full_img_path = None
        else:
            full_img_path = os.path.abspath(full_img_path)

        # Kiểm tra và xử lý đường dẫn ảnh biển số
        if not plate_img_path or not os.path.exists(plate_img_path):
            plate_img_path = None
        else:
            plate_img_path = os.path.abspath(plate_img_path)

        # Kiểm tra và xử lý đường dẫn video
        if not video_path or not os.path.exists(video_path):
            video_path = None
        else:
            video_path = os.path.abspath(video_path)

        # Format loại xe sang tiếng Việt
        vehicle_type_map = {
            'car': 'Ô TÔ',
            'motorcycle': 'XE GẮN MÁY',
            'bus': 'XE BUS',
            'truck': 'XE TẢI'
        }
        vehicle_type_display = vehicle_type_map.get(vehicle_class.lower(), vehicle_class.upper())

        # Tính vượt quá
        exceeded = round(speed - limit, 2)

        # Tạo message chi tiết với đầy đủ thông tin BẮT BUỘC
        # BẮT BUỘC: plate, owner_name, address, phone
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

        # 1. GỬI MESSAGE
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

        # 2. GỬI ẢNH PHƯƠNG TIỆN VI PHẠM (BẮT BUỘC - khoanh vùng xe vi phạm)
        # full_img_path đã được kiểm tra ở trên, chắc chắn tồn tại
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

        # 3. GỬI ẢNH BIỂN SỐ (đã crop)
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

        # 4. GỬI VIDEO KHOANH VÙNG ĐỐI TƯỢNG VI PHẠM
        if video_path:
            try:
                # Kiểm tra kích thước file (Telegram giới hạn 50MB)
                file_size = os.path.getsize(video_path)
                if file_size > 50 * 1024 * 1024:  # 50MB
                    print(f"[TELEGRAM] Video quá lớn ({file_size / 1024 / 1024:.2f}MB), bỏ qua")
                else:
                    with open(video_path, "rb") as vf:
                        caption = (
                            f"🎥 Video khoanh vùng đối tượng vi phạm\n"
                            f"Biển số: {plate}\n"
                            f"Loại xe: {vehicle_type_display}\n"
                            f"Tốc độ: {round(speed, 2)} km/h (Vượt quá: {exceeded} km/h)"
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
                            print(f"[TELEGRAM] ✓ Đã gửi video khoanh vùng đối tượng vi phạm")
            except Exception as e:
                print(f"[TELEGRAM] Video send error: {e}")
                send_success = False
        
        # Cập nhật status trong database
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
    """
    Validate biển số Việt Nam hợp lệ
    Hỗ trợ các format phổ biến:
    - Xe cá nhân: 2 số + 1 chữ + 5 số (VD: 29A12345)
    - Xe công vụ: 2 số + 2 chữ + 4 số (VD: 29AB1234)
    - Xe ngoại giao: 2 số + NG + 4 số (VD: 29NG1234)
    - Xe quân đội: 2 số + 1 chữ + 4 số (VD: 29A1234)
    - Xe tạm thời: 2 số + 1 chữ + 4 số (VD: 29A1234)
    """
    if not plate:
        return False
    
    # Normalize: loại bỏ khoảng trắng, dấu chấm, dấu gạch ngang, chuyển thành chữ hoa
    plate = plate.replace(" ", "").replace(".", "").replace("-", "").replace("_", "").upper()
    
    # Kiểm tra độ dài tối thiểu
    if len(plate) < 7 or len(plate) > 9:
        return False
    
    # Pattern 1: Xe cá nhân - 2 số + 1 chữ + 5 số (VD: 29A12345)
    pattern1 = r"^[0-9]{2}[A-Z][0-9]{5}$"
    if re.match(pattern1, plate):
        return True
    
    # Pattern 2: Xe công vụ - 2 số + 2 chữ + 4 số (VD: 29AB1234)
    pattern2 = r"^[0-9]{2}[A-Z]{2}[0-9]{4}$"
    if re.match(pattern2, plate):
        return True
    
    # Pattern 3: Xe ngoại giao - 2 số + NG + 4 số (VD: 29NG1234)
    pattern3 = r"^[0-9]{2}NG[0-9]{4}$"
    if re.match(pattern3, plate):
        return True
    
    # Pattern 4: Xe quân đội/tạm thời - 2 số + 1 chữ + 4 số (VD: 29A1234)
    pattern4 = r"^[0-9]{2}[A-Z][0-9]{4}$"
    if re.match(pattern4, plate):
        return True
    
    return False

def normalize_plate(plate):
    """
    Normalize biển số: loại bỏ ký tự đặc biệt, khoảng trắng, chuyển thành chữ hoa
    """
    if not plate:
        return ""
    return plate.replace(" ", "").replace(".", "").replace("-", "").replace("_", "").upper()


# HANDLE VIOLATION
# ======================
def save_violation_data(detection, speed, frame):
    """
    Lưu dữ liệu vi phạm vào database NGAY LẬP TỨC (không chờ Fast-ALPR)
    Sau đó gửi ảnh đã lưu cho Fast-ALPR đọc biển số (async)
    
    FLOW MỚI:
    1. Lưu ảnh vi phạm vào database ngay (với biển số tạm thời từ tracking)
    2. Gửi ảnh đã lưu cho Fast-ALPR đọc (async) - tránh làm chậm tracking
    3. Fast-ALPR đọc từ ảnh tĩnh đã lưu trong database
    4. Cập nhật lại biển số vào database sau khi Fast-ALPR đọc xong
    
    detection: Dict chứa thông tin xe và biển số
    speed: Tốc độ xe (km/h)
    frame: Frame GỐC (KHÔNG CÓ BOUNDING BOX) - để lưu ảnh vi phạm
    """
    try:
        plate = detection.get('plate')  # Biển số tạm thời từ tracking (có thể None hoặc không chính xác)
        vehicle_class = detection['vehicle_class']
        track_id = detection['track_id']
        vehicle_bbox = detection['vehicle_bbox']
        timestamp = int(time.time())
        
        # Normalize biển số tạm thời (nếu có)
        temp_plate = normalize_plate(plate) if plate else None
        
        # CHẤP NHẬN BIỂN SỐ TẠM THỜI (hoặc NULL) - sẽ được cập nhật sau khi Fast-ALPR đọc xong
        # Không bỏ qua nếu biển số không hợp lệ - vẫn lưu để Fast-ALPR đọc lại
        
        os.makedirs("static/uploads", exist_ok=True)
        os.makedirs("static/plate_images", exist_ok=True)
        os.makedirs("static/violation_videos", exist_ok=True)
        
        # 1. LƯU ẢNH XE VI PHẠM (KHÔNG CÓ BOUNDING BOX) - LƯU NGAY ĐỂ Fast-ALPR ĐỌC SAU
        padding = 50
        x1, y1, x2, y2 = vehicle_bbox
        crop_x1 = max(0, x1 - padding)
        crop_y1 = max(0, y1 - padding)
        crop_x2 = min(frame.shape[1], x2 + padding)
        crop_y2 = min(frame.shape[0], y2 + padding)
        
        violation_frame = frame[crop_y1:crop_y2, crop_x1:crop_x2].copy()
        
        # Tạo tên file dựa trên timestamp (không dùng biển số vì có thể chưa chính xác)
        violation_img_name = f"violation_{timestamp}_{track_id}.jpg"
        violation_img_path = os.path.join("static/uploads", violation_img_name)
        cv2.imwrite(violation_img_path, violation_frame)
        print(f"[SAVED] ✅ Đã lưu ảnh vi phạm: {violation_img_name} (sẽ gửi cho Fast-ALPR đọc sau)")
        
        # 2. LƯU ẢNH XE (crop vùng xe) - để hiển thị trên web
        x1, y1, x2, y2 = vehicle_bbox
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(frame.shape[1], x2), min(frame.shape[0], y2)
        
        vehicle_img_name = f"vehicle_{timestamp}_{track_id}.jpg"
        vehicle_img_path = os.path.join("static/uploads", vehicle_img_name)
        if x2 > x1 and y2 > y1:
            vehicle_img = frame[y1:y2, x1:x2]
            cv2.imwrite(vehicle_img_path, vehicle_img)
        else:
            print(f"[ERROR] Invalid bbox coordinates: ({x1}, {y1}, {x2}, {y2})")
            vehicle_img_path = None

        # 3. TẠO VIDEO TỪ violation_frame_buffer[track_id] (FULL MÀN HÌNH CÓ BOUNDING BOX)
        # Video cho người vi phạm: Full màn hình, có bounding box cho xe vi phạm
        video_telegram_name = f"violation_telegram_{timestamp}_{track_id}.mp4"
        video_telegram_path = os.path.join("static/violation_videos", video_telegram_name)
        
        # Video detection: Có bounding box, text overlay (cho admin/web)
        video_detection_name = f"violation_{timestamp}_{track_id}.mp4"
        video_detection_path = os.path.join("static/violation_videos", video_detection_name)
        
        # Dùng video_telegram_path cho Telegram (gửi cho người vi phạm)
        video_path = video_telegram_path
        
        try:
            h, w, _ = frame.shape
            fps = video_fps if video_fps > 0 else 30
            
            # Sử dụng H.264 codec (tương thích với Telegram)
            # Thử các codec H.264 phổ biến
            codec_options = [
                ('avc1', 'H.264/AVC'),  # Apple H.264
                ('h264', 'H.264'),      # H.264
                ('X264', 'x264'),        # x264 encoder
                ('mp4v', 'MPEG-4')       # Fallback
            ]
            
            def create_video_writer(video_path, fps, width, height):
                """Helper function để tạo video writer với FPS chính xác"""
                # Đảm bảo FPS hợp lệ (từ 1 đến 60)
                fps = max(1.0, min(60.0, float(fps)))
                
                for codec, name in codec_options:
                    try:
                        fourcc = cv2.VideoWriter_fourcc(*codec)
                        out = cv2.VideoWriter(video_path, fourcc, fps, (int(width), int(height)))
                        if out.isOpened():
                            print(f"[VIDEO] Sử dụng codec: {name} ({codec}), FPS: {fps:.2f}, Size: {int(width)}x{int(height)}")
                            return out, name
                        else:
                            out.release()
                    except Exception as e:
                        print(f"[VIDEO] Lỗi codec {codec}: {e}")
                        continue
                return None, None
            
            # ========== VIDEO TELEGRAM (FULL MÀN HÌNH CÓ BOUNDING BOX) ==========
            # Dùng để gửi cho người vi phạm xem lại
            # Lấy từ violation_frame_buffer[track_id] (full màn hình CÓ bounding box)
            global sent_violation_tracks
            
            out_telegram, codec_telegram = create_video_writer(video_telegram_path, fps, w, h)
            frames_written_telegram = 0
            
            if out_telegram and out_telegram.isOpened():
                # Lấy tất cả frames từ violation_frame_buffer[track_id] (full màn hình CÓ bounding box)
                if track_id in violation_frame_buffer and len(violation_frame_buffer[track_id]) > 0:
                    frames_telegram = list(violation_frame_buffer[track_id])
                    num_frames = len(frames_telegram)
                    print(f"[VIDEO TELEGRAM] Lấy {num_frames} frames từ violation_frame_buffer[track_id={track_id}] (full màn hình, có bounding box)")
                    
                    # Tính toán FPS chính xác dựa trên số frame thực tế
                    # Mục tiêu: 5 giây video, FPS = số frame / thời gian mong muốn
                    target_duration = 5.0  # 5 giây
                    calculated_fps = max(20, min(30, num_frames / target_duration))  # Giới hạn FPS từ 20-30
                    print(f"[VIDEO TELEGRAM] FPS tính toán: {calculated_fps:.2f} (từ {num_frames} frames cho {target_duration}s)")
                    
                    # Tạo lại video writer với FPS chính xác
                    out_telegram.release()
                    out_telegram, codec_telegram = create_video_writer(video_telegram_path, calculated_fps, w, h)
                    
                    if out_telegram and out_telegram.isOpened():
                        for frame_telegram in frames_telegram:
                            # Kiểm tra kích thước frame
                            if frame_telegram.shape[0] != h or frame_telegram.shape[1] != w:
                                # Resize nếu cần
                                frame_telegram = cv2.resize(frame_telegram, (w, h), interpolation=cv2.INTER_LINEAR)
                            
                            # Ghi frame vào video telegram (full màn hình, CÓ BOUNDING BOX)
                            out_telegram.write(frame_telegram)
                            frames_written_telegram += 1
                        
                        out_telegram.release()
                        if frames_written_telegram > 0:
                            duration = frames_written_telegram / calculated_fps
                            print(f"[VIDEO TELEGRAM] ✅ Đã tạo video telegram: {video_telegram_name} ({frames_written_telegram} frames, {duration:.2f}s, FPS: {calculated_fps:.2f}, codec: {codec_telegram})")
                            # Đánh dấu track_id đã gửi để không gửi lại
                            sent_violation_tracks.add(track_id)
                            print(f"[VIDEO TELEGRAM] ✅ Đã đánh dấu track_id {track_id} là đã gửi")
                        else:
                            print(f"[VIDEO TELEGRAM] ⚠️ Không có frame nào được ghi")
                            video_telegram_path = None
                    else:
                        print(f"[VIDEO TELEGRAM] ❌ Không thể tạo lại video writer với FPS {calculated_fps}")
                        if os.path.exists(video_telegram_path):
                            try:
                                os.remove(video_telegram_path)
                            except:
                                pass
                        video_telegram_path = None
                else:
                    print(f"[VIDEO TELEGRAM] ⚠️ Không có frames trong violation_frame_buffer[track_id={track_id}]")
                    video_telegram_path = None
            else:
                print(f"[VIDEO TELEGRAM] ❌ Không thể tạo video writer")
                video_telegram_path = None
            
            # ========== VIDEO DETECTION (FULL MÀN HÌNH CÓ BOUNDING BOX CHO 1 XE VI PHẠM) ==========
            # Dùng để hiển thị trên web/admin - giống video telegram
            # Lấy từ violation_frame_buffer[track_id] (full màn hình, CÓ BOUNDING BOX cho 1 xe vi phạm)
            out_detection, codec_detection = create_video_writer(video_detection_path, fps, w, h)
            frames_written_detection = 0
            
            if out_detection and out_detection.isOpened():
                # Lấy frames từ violation_frame_buffer[track_id] (full màn hình, CÓ BOUNDING BOX cho 1 xe vi phạm)
                if track_id in violation_frame_buffer and len(violation_frame_buffer[track_id]) > 0:
                    frames_detection = list(violation_frame_buffer[track_id])
                    num_frames_detection = len(frames_detection)
                    print(f"[VIDEO DETECTION] Lấy {num_frames_detection} frames từ violation_frame_buffer[track_id={track_id}] (full màn hình, có bounding box cho 1 xe vi phạm)")
                    
                    # Tính toán FPS chính xác dựa trên số frame thực tế (giống video telegram)
                    target_duration = 5.0  # 5 giây
                    calculated_fps_detection = max(20, min(30, num_frames_detection / target_duration))
                    print(f"[VIDEO DETECTION] FPS tính toán: {calculated_fps_detection:.2f} (từ {num_frames_detection} frames cho {target_duration}s)")
                    
                    # Tạo lại video writer với FPS chính xác
                    out_detection.release()
                    out_detection, codec_detection = create_video_writer(video_detection_path, calculated_fps_detection, w, h)
                    
                    if out_detection and out_detection.isOpened():
                        for frame_detection in frames_detection:
                            # Kiểm tra kích thước frame
                            if frame_detection.shape[0] != h or frame_detection.shape[1] != w:
                                # Resize nếu cần
                                frame_detection = cv2.resize(frame_detection, (w, h), interpolation=cv2.INTER_LINEAR)
                            
                            # Ghi frame vào video detection (full màn hình, CÓ BOUNDING BOX cho 1 xe vi phạm)
                            out_detection.write(frame_detection)
                            frames_written_detection += 1
                        
                        out_detection.release()
                        if frames_written_detection > 0:
                            duration = frames_written_detection / calculated_fps_detection
                            print(f"[VIDEO DETECTION] ✅ Đã lưu video detection: {video_detection_name} ({frames_written_detection} frames, {duration:.2f}s, FPS: {calculated_fps_detection:.2f}, codec: {codec_detection})")
                        else:
                            print(f"[VIDEO DETECTION] ⚠️ Không có frame nào được ghi")
                            if os.path.exists(video_detection_path):
                                try:
                                    os.remove(video_detection_path)
                                except:
                                    pass
                            video_detection_path = None
                    else:
                        print(f"[VIDEO DETECTION] ❌ Không thể tạo lại video writer với FPS {calculated_fps_detection}")
                        if os.path.exists(video_detection_path):
                            try:
                                os.remove(video_detection_path)
                            except:
                                pass
                        video_detection_path = None
                else:
                    print(f"[VIDEO DETECTION] ⚠️ Không có frames trong violation_frame_buffer[track_id={track_id}]")
                    video_detection_path = None
            else:
                print(f"[VIDEO DETECTION] ❌ Không thể tạo video writer")
                video_detection_path = None
            
            # Dùng video telegram cho Telegram (gửi cho người vi phạm)
            if video_telegram_path and os.path.exists(video_telegram_path):
                video_path = video_telegram_path
            else:
                video_path = None
        except Exception as e:
            print(f"[ERROR] Video writing failed: {e}")
            import traceback
            traceback.print_exc()
            video_path = None

        # 4. LƯU VÀO DATABASE NGAY (KHÔNG CHỜ Fast-ALPR) - với biển số tạm thời hoặc NULL
        # TỐI ƯU: Batch insert, connection pooling, async
        violation_id = None
        try:
            with app.app_context():
                conn = mysql.connection
                cursor = conn.cursor()
                cursor.execute("SET time_zone = '+07:00'")
                
                # Lưu với biển số tạm thời (nếu hợp lệ) hoặc NULL
                # Fast-ALPR sẽ cập nhật lại sau
                db_plate = temp_plate if (temp_plate and is_valid_plate(temp_plate)) else None
                
                # TỐI ƯU: Tạo hoặc cập nhật vehicle_owner nếu có biển số tạm thời (INSERT IGNORE để tránh duplicate)
                if db_plate:
                    cursor.execute("INSERT IGNORE INTO vehicle_owner (plate, owner_name, address, phone) VALUES (%s, NULL, NULL, NULL)", (db_plate,))
                    conn.commit()
                
                # TỐI ƯU: Lưu violation với single query (plate có thể NULL - sẽ được cập nhật sau)
                # status mặc định là 'pending' (chưa gửi Telegram)
                video_name_for_db = video_detection_name if video_detection_path and os.path.exists(video_detection_path) else (video_telegram_name if video_telegram_path and os.path.exists(video_telegram_path) else None)
                cursor.execute("""
                    INSERT INTO violations (plate, speed, speed_limit, image, plate_image, video, status, vehicle_class, time) 
                    VALUES (%s, %s, %s, %s, %s, %s, 'pending', %s, CONVERT_TZ(NOW(), @@session.time_zone, '+07:00'))
                """, (
                    db_plate, 
                    speed, 
                    speed_limit, 
                    vehicle_img_name if vehicle_img_path else None,
                    None,  # plate_image sẽ được cập nhật sau khi Fast-ALPR đọc xong
                    video_name_for_db,  # Lưu video detection (full màn hình, có bounding box cho 1 xe vi phạm) cho admin
                    vehicle_class  # Lưu loại xe ngay từ đầu
                ))
                conn.commit()
                violation_id = cursor.lastrowid
                cursor.close()
                print(f"[DB] ✅ Đã lưu violation vào database (ID: {violation_id}, Plate tạm: {db_plate or 'NULL'})")
        except Exception as e:
            print(f"[ERROR] Database error: {e}")
            import traceback
            traceback.print_exc()
            return  # Không tiếp tục nếu lưu database lỗi

        # 5. GỬI ẢNH ĐÃ LƯU CHO ALPR WORKER THREAD (QUA QUEUE) - KHÔNG BLOCK TRACKING
        # ALPR Worker Thread sẽ đọc từ ảnh tĩnh đã lưu và cập nhật lại database
        if violation_id and violation_img_path and os.path.exists(violation_img_path):
            print(f"[ALPR QUEUE] 📤 Gửi ảnh đã lưu vào ALPR queue (async): {violation_img_name}")
            
            # Đảm bảo ALPR worker thread đang chạy
            start_alpr_worker()
            
            # Gửi vào ALPR queue
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
                }, block=False)  # Không block nếu queue đầy
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
    """
    Đọc biển số từ ảnh vi phạm ĐÃ LƯU trong database bằng Fast-ALPR
    Sau đó cập nhật lại database với biển số chính xác và ảnh biển số
    
    QUAN TRỌNG: Hàm này chạy ASYNC, không block tracking
    Fast-ALPR chỉ đọc ảnh tĩnh đã lưu, không đọc từ video stream
    """
    try:
        print(f"[FAST-ALPR] 🔍 Bắt đầu đọc biển số từ ảnh đã lưu: {os.path.basename(violation_img_path)}")
        
        # Kiểm tra ảnh tồn tại
        if not os.path.exists(violation_img_path):
            print(f"[FAST-ALPR] ❌ Ảnh không tồn tại: {violation_img_path}")
            return
        
        # Đọc ảnh từ disk (ảnh tĩnh đã lưu)
        violation_frame = cv2.imread(violation_img_path)
        if violation_frame is None:
            print(f"[FAST-ALPR] ❌ Không thể đọc ảnh: {violation_img_path}")
            return
        
        print(f"[FAST-ALPR] ✅ Đã đọc ảnh từ disk: {violation_frame.shape[1]}x{violation_frame.shape[0]}")
        
        # Resize ảnh nếu quá lớn để tăng tốc
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
        
        # GỌI Fast-ALPR ĐỌC BIỂN SỐ TỪ ẢNH TĨNH
        plate_img_path = None
        plate_img_name = None
        detected_plate_text = None
        detected_plate_bbox = None
        
        try:
            # Kiểm tra plate_detector_post có sẵn không
            if plate_detector_post is None:
                print(f"[FAST-ALPR] ⚠️ Plate detector not available, skipping plate detection")
                plate_results_raw = []
            else:
                # GỌI Fast-ALPR ĐỌC BIỂN SỐ TỪ ẢNH TĨNH ĐÃ LƯU
                plate_results_raw = plate_detector_post.detect(detection_frame)
            
            if not plate_results_raw:
                print(f"[FAST-ALPR] ⚠️ Fast-ALPR không phát hiện biển số")
                plate_results = []
                # Xóa ảnh vi phạm vì không đọc được biển số
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
                print(f"[FAST-ALPR] ⚡ Phát hiện {len(plate_results_raw)} biển số (thời gian nhanh)")
                
                # Scale lại bbox về kích thước gốc nếu đã resize
                plate_results = []
                seen_plates = set()
                
                for result in plate_results_raw:
                    plate_text = result.get('plate', '').strip()
                    if not plate_text:
                        continue
                    
                    # Scale lại bbox về kích thước gốc (CHÍNH XÁC)
                    if scale_factor != 1.0:
                        px1, py1, px2, py2 = result['bbox']
                        # Scale về kích thước gốc
                        px1 = int(px1 / scale_factor)
                        py1 = int(py1 / scale_factor)
                        px2 = int(px2 / scale_factor)
                        py2 = int(py2 / scale_factor)
                        result['bbox'] = (px1, py1, px2, py2)
                    
                    # Normalize biển số
                    normalized = normalize_plate(plate_text)
                    if normalized and normalized not in seen_plates:
                        seen_plates.add(normalized)
                        # Cập nhật plate text đã normalize
                        result['plate'] = normalized
                        result['plate_original'] = plate_text
                        plate_results.append(result)
            
            # Xử lý kết quả
            if plate_results and len(plate_results) > 0:
                print(f"[FAST-ALPR] ✅ Tổng cộng phát hiện {len(plate_results)} biển số unique trong ảnh vi phạm")
                
                # Chọn biển số tốt nhất (ưu tiên confidence cao và text đầy đủ)
                best_plate = None
                best_score = 0
                
                for plate_result in plate_results:
                    plate_text = plate_result['plate']
                    plate_bbox_crop = plate_result['bbox']
                    plate_conf = plate_result.get('confidence', 0.5)
                    detection_conf = plate_result.get('detection_conf', 0.5)
                    ocr_conf = plate_result.get('ocr_conf', 0.5)
                    
                    # Normalize lại để chắc chắn
                    plate_text = normalize_plate(plate_text)
                    if not plate_text:
                        continue
                    
                    # 🚫 CHỈ CHỌN BIỂN SỐ HỢP LỆ - Validation ngay từ đầu
                    if not is_valid_plate(plate_text):
                        print(f"[FAST-ALPR] ⚠️ Bỏ qua biển số không hợp lệ: {plate_text} (original: {plate_result.get('plate_original', '')})")
                        continue
                    
                    # Tính điểm để chọn biển số tốt nhất
                    score = plate_conf * 50  # Confidence tổng hợp có trọng số cao
                    score += detection_conf * 20  # Detection confidence
                    score += ocr_conf * 15  # OCR confidence
                    
                    # Ưu tiên biển số đầy đủ (>= 8 ký tự)
                    if len(plate_text) >= 8:
                        score += 30
                    elif len(plate_text) >= 6:
                        score += 20
                    else:
                        continue  # Bỏ qua biển số không đầy đủ
                    
                    # Kiểm tra bbox hợp lệ
                    px1, py1, px2, py2 = plate_bbox_crop
                    if px2 <= px1 or py2 <= py1:
                        continue
                    
                    # Điểm cho kích thước bbox hợp lý
                    bbox_w = px2 - px1
                    bbox_h = py2 - py1
                    bbox_area = bbox_w * bbox_h
                    
                    # Kích thước hợp lý cho biển số
                    if 50 <= bbox_w <= 500 and 20 <= bbox_h <= 150:
                        score += 10
                    if bbox_area >= 2000:
                        score += 5
                    
                    # Điểm cho tỷ lệ khung hình (biển số thường rộng hơn cao)
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
                    detected_plate_text = normalize_plate(best_plate['plate'])  # Normalize lại
                    detected_plate_bbox = best_plate['bbox']
                    print(f"[FAST-ALPR] ✅ Bước 3: Fast-ALPR đã đọc được biển số: {detected_plate_text} "
                          f"(conf={best_plate['confidence']:.2f}, det={best_plate['detection_conf']:.2f}, ocr={best_plate['ocr_conf']:.2f}, score={best_score:.1f})")
                    print(f"[FAST-ALPR] 📦 Bước 4: Bounding box biển số: ({detected_plate_bbox[0]}, {detected_plate_bbox[1]}, {detected_plate_bbox[2]}, {detected_plate_bbox[3]})")
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
        
        # 3. CROP ẢNH BIỂN SỐ TỪ BOUNDING BOX CỦA FAST-ALPR
        # Bước 5: Sau khi Fast-ALPR đã đọc được biển số và trả về bounding box, crop ảnh biển số
        # Bước 6: Lưu ảnh biển số đã crop để hiển thị
        if detected_plate_bbox:
            print(f"[PLATE CROP] ✂️ Bước 5: Đang crop ảnh biển số từ bounding box của Fast-ALPR...")
            try:
                px1, py1, px2, py2 = detected_plate_bbox
                
                # Validate và log bbox ban đầu (bbox từ Fast-ALPR là tương đối với violation_frame)
                h, w = violation_frame.shape[:2]
                print(f"[PLATE CROP] Fast-ALPR bbox: ({px1}, {py1}, {px2}, {py2}), Violation frame size: {w}x{h}")
                
                # Validate bbox trước - đảm bảo nằm trong violation_frame
                px1 = max(0, min(px1, w - 1))
                py1 = max(0, min(py1, h - 1))
                px2 = max(px1 + 1, min(px2, w))
                py2 = max(py1 + 1, min(py2, h))
                
                # Kiểm tra bbox hợp lệ
                if px2 <= px1 or py2 <= py1:
                    print(f"[ERROR] Plate bbox không hợp lệ sau validate: ({px1}, {py1}, {px2}, {py2})")
                else:
                    # Mở rộng bbox một chút để bao hết biển số (tránh bị cắt)
                    # Padding nhỏ hơn để crop chính xác hơn, chỉ bao quanh biển số
                    # Tính padding dựa trên kích thước bbox để tỷ lệ hợp lý
                    bbox_w_orig = px2 - px1
                    bbox_h_orig = py2 - py1
                    
                    # Padding tỷ lệ với kích thước bbox (5-10% mỗi bên)
                    padding_x = max(5, int(bbox_w_orig * 0.05))  # Tối thiểu 5px, tối đa 5% width
                    padding_y = max(3, int(bbox_h_orig * 0.05))  # Tối thiểu 3px, tối đa 5% height
                    
                    # Giới hạn padding để không quá lớn
                    padding_x = min(padding_x, 10)
                    padding_y = min(padding_y, 8)
                    
                    px1 = max(0, px1 - padding_x)
                    py1 = max(0, py1 - padding_y)
                    px2 = min(w, px2 + padding_x)
                    py2 = min(h, py2 + padding_y)
                    
                    # Đảm bảo kích thước tối thiểu hợp lý
                    bbox_w = px2 - px1
                    bbox_h = py2 - py1
                    
                    print(f"[PLATE CROP] After padding: ({px1}, {py1}, {px2}, {py2}), Size: {bbox_w}x{bbox_h} (padding: {padding_x}x{padding_y})")
                    
                    if bbox_w >= 30 and bbox_h >= 15:
                        # Crop ảnh biển số từ violation_frame (đã lưu) - CHÍNH XÁC TỪ BBOX CỦA FAST-ALPR
                        plate_img = violation_frame[py1:py2, px1:px2].copy()
                        
                        if plate_img.size == 0:
                            print(f"[ERROR] ❌ Plate crop rỗng: ({px1}, {py1}, {px2}, {py2})")
                        else:
                            print(f"[PLATE CROP] ✅ Bước 5: Crop thành công ảnh biển số: {plate_img.shape[1]}x{plate_img.shape[0]}")
                            print(f"[PLATE CROP] 🎨 Bước 6: Đang enhance và lưu ảnh biển số để hiển thị...")
                            
                            # ENHANCE ẢNH MÀU để rõ nét hơn - GIỮ MÀU GỐC (KHÔNG CHUYỂN SANG ĐEN TRẮNG)
                            try:
                                # Đảm bảo ảnh có 3 kênh màu (BGR) - LUÔN GIỮ MÀU
                                if len(plate_img.shape) == 2:
                                    # Nếu là grayscale, chuyển sang BGR (tạo ảnh màu từ grayscale)
                                    plate_img = cv2.cvtColor(plate_img, cv2.COLOR_GRAY2BGR)
                                elif len(plate_img.shape) == 3 and plate_img.shape[2] == 3:
                                    # Đã là BGR, giữ nguyên
                                    pass
                                else:
                                    # Nếu không phải BGR, chuyển sang BGR
                                    plate_img = cv2.cvtColor(plate_img, cv2.COLOR_GRAY2BGR)
                                
                                # Đảm bảo ảnh là BGR (3 kênh màu)
                                if len(plate_img.shape) != 3 or plate_img.shape[2] != 3:
                                    raise ValueError(f"Ảnh không phải BGR: shape={plate_img.shape}")
                                
                                # Enhance từng kênh màu riêng biệt để giữ màu gốc
                                # Chuyển sang LAB color space để enhance tốt hơn (giữ màu tốt)
                                lab = cv2.cvtColor(plate_img, cv2.COLOR_BGR2LAB)
                                l, a, b = cv2.split(lab)
                                
                                # Tăng contrast và brightness cho kênh L (Lightness) bằng CLAHE
                                clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(4,4))
                                l_enhanced = clahe.apply(l)
                                
                                # Merge lại - GIỮ NGUYÊN kênh a và b (màu sắc)
                                lab_enhanced = cv2.merge([l_enhanced, a, b])
                                
                                # Chuyển lại về BGR - ĐẢM BẢO CÓ MÀU
                                enhanced = cv2.cvtColor(lab_enhanced, cv2.COLOR_LAB2BGR)
                                
                                # Kiểm tra lại đảm bảo có màu
                                if len(enhanced.shape) != 3 or enhanced.shape[2] != 3:
                                    raise ValueError(f"Ảnh enhanced không phải BGR: shape={enhanced.shape}")
                                
                                # Unsharp masking để làm rõ nét (tăng độ sắc nét) - trên ảnh màu
                                gaussian = cv2.GaussianBlur(enhanced, (0, 0), 1.5)
                                sharpened = cv2.addWeighted(enhanced, 1.5, gaussian, -0.5, 0)
                                
                                # Tăng saturation một chút để màu đẹp hơn
                                hsv = cv2.cvtColor(sharpened, cv2.COLOR_BGR2HSV)
                                h, s, v = cv2.split(hsv)
                                s = cv2.multiply(s, 1.2)  # Tăng saturation 20%
                                s = cv2.min(s, 255)  # Đảm bảo không vượt quá 255
                                hsv_enhanced = cv2.merge([h, s, v])
                                sharpened = cv2.cvtColor(hsv_enhanced, cv2.COLOR_HSV2BGR)
                                
                                # Kiểm tra lại đảm bảo có màu
                                if len(sharpened.shape) != 3 or sharpened.shape[2] != 3:
                                    raise ValueError(f"Ảnh sharpened không phải BGR: shape={sharpened.shape}")
                                
                                # Resize nếu quá nhỏ để dễ đọc hơn (tối thiểu 200px width, không quá lớn)
                                h_img, w_img = sharpened.shape[:2]
                                target_width = 200  # Giảm từ 250 xuống 200 để không quá lớn
                                max_width = 400  # Giới hạn tối đa
                                
                                if w_img < target_width:
                                    scale = target_width / w_img
                                    new_w = int(w_img * scale)
                                    new_h = int(h_img * scale)
                                    # Đảm bảo không quá lớn
                                    if new_w > max_width:
                                        scale = max_width / w_img
                                        new_w = int(w_img * scale)
                                        new_h = int(h_img * scale)
                                    # Dùng INTER_CUBIC để chất lượng tốt hơn
                                    sharpened = cv2.resize(sharpened, (new_w, new_h), interpolation=cv2.INTER_CUBIC)
                                elif w_img > max_width:
                                    # Nếu quá lớn, resize xuống
                                    scale = max_width / w_img
                                    new_w = int(w_img * scale)
                                    new_h = int(h_img * scale)
                                    sharpened = cv2.resize(sharpened, (new_w, new_h), interpolation=cv2.INTER_CUBIC)
                                
                                # Đảm bảo cuối cùng vẫn là BGR (3 kênh màu)
                                if len(sharpened.shape) != 3 or sharpened.shape[2] != 3:
                                    raise ValueError(f"Ảnh cuối cùng không phải BGR: shape={sharpened.shape}")
                                
                                plate_img_final = sharpened
                                
                                # Lưu ảnh với quality cao (95) để giữ chất lượng
                                # CHỈ LƯU NẾU BIỂN SỐ HỢP LỆ
                                # Validate lại biển số trước khi lưu
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
                                # Fallback: Lưu ảnh gốc nếu enhance lỗi
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
        
        # 4. CẬP NHẬT DATABASE - CHỈ LƯU NẾU CÓ CẢ BIỂN SỐ VÀ ẢNH BIỂN SỐ
        # YÊU CẦU: Phải có CẢ biển số hợp lệ VÀ ảnh biển số mới được lưu
        if detected_plate_text and is_valid_plate(detected_plate_text) and plate_img_path and os.path.exists(plate_img_path):
            try:
                with app.app_context():
                    conn = mysql.connection
                    cursor = conn.cursor()
                    cursor.execute("SET time_zone = '+07:00'")
                    
                    # Tạo hoặc cập nhật vehicle_owner với biển số chính xác
                    cursor.execute("SELECT * FROM vehicle_owner WHERE plate=%s", (detected_plate_text,))
                    owner = cursor.fetchone()
                    if not owner:
                        cursor.execute("INSERT INTO vehicle_owner (plate, owner_name, address, phone) VALUES (%s, NULL, NULL, NULL)", (detected_plate_text,))
                        conn.commit()
                    
                    # Cập nhật violation với biển số chính xác, ảnh biển số và vehicle_class
                    cursor.execute("""
                        UPDATE violations 
                        SET plate=%s, plate_image=%s, vehicle_class=%s
                        WHERE id=%s
                    """, (
                        detected_plate_text,
                        plate_img_name,  # Đảm bảo có ảnh biển số
                        vehicle_class,  # Lưu loại xe
                        violation_id
                    ))
                    conn.commit()
                    
                    # Lấy thông tin owner
                    cursor.execute("SELECT owner_name, address, phone FROM vehicle_owner WHERE plate=%s", (detected_plate_text,))
                    owner = cursor.fetchone()
                    owner_name = owner["owner_name"] or "Không rõ" if owner else "Không rõ"
                    address = owner["address"] or "Không rõ" if owner else "Không rõ"
                    phone = owner["phone"] or "Không rõ" if owner else "Không rõ"
                    
                    print(f"[DB] ✅ Đã cập nhật violation ID {violation_id} với biển số: {detected_plate_text} và ảnh biển số: {plate_img_name}")
                    
                    # Gửi Telegram alert với biển số chính xác (qua queue để gửi tuần tự)
                    full_img_path = violation_img_path  # Ảnh vi phạm đã lưu
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
            # XÓA RECORD TẠM NẾU KHÔNG CÓ ĐẦY ĐỦ THÔNG TIN
            # Chỉ lưu những vi phạm có CẢ biển số VÀ ảnh biển số
            try:
                with app.app_context():
                    conn = mysql.connection
                    cursor = conn.cursor()
                    cursor.execute("DELETE FROM violations WHERE id=%s", (violation_id,))
                    conn.commit()
                    
                    # Xóa các file đã lưu (tùy chọn - có thể giữ lại để debug)
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
                    print(f"[SKIP]    → Chỉ lưu những vi phạm có CẢ biển số nhìn rõ VÀ ảnh biển số")
            except Exception as e:
                print(f"[ERROR] Cleanup error: {e}")
                import traceback
                traceback.print_exc()
        
        print(f"[FAST-ALPR] ✅ Hoàn thành xử lý ảnh vi phạm ID {violation_id}")
        
    except Exception as e:
        print(f"[ERROR] process_plate_from_saved_image failed: {e}")
        import traceback
        traceback.print_exc()

# ======================
# VIDEO PROCESSING THREAD
# ======================
# Tách detection ra thread riêng để không block video stream
# TỐI ƯU GPU: Tăng queue size để GPU luôn có việc làm (BẮT BUỘC GPU)
# TỐI ƯU: Khi upload video, tăng queue size để xử lý nhanh hơn
def get_detection_queue_size():
    """Tính queue size dựa trên device và mode"""
    base_size = 15 if DEVICE == 'cuda' else 10
    # Khi upload video, tăng queue size để xử lý nhanh hơn (tập trung tài nguyên)
    if is_video_upload_mode:
        return base_size + 5  # Tăng thêm 5 cho video upload
    return base_size

# ======================
# QUEUES VÀ BUFFERS CHO 4 THREAD
# ======================
detection_queue = deque(maxlen=get_detection_queue_size())  # Queue động dựa trên mode
stream_queue = queue.Queue(maxsize=30)  # Queue để gửi frame có bbox cho admin stream
violation_queue = queue.Queue(maxsize=20)  # Queue để gửi dữ liệu vi phạm từ DetectThread sang ViolationThread
telegram_queue = queue.Queue(maxsize=50)  # Queue để gửi vi phạm cho TelegramThread

# Buffers theo track_id để tránh nhầm xe
original_frame_buffer = {}  # Dict[track_id] -> deque of frames gốc (không có bbox) - dùng để crop và tạo video clean
admin_frame_buffer = {}  # Dict[track_id] -> deque of frames có bbox (cho admin stream) - dùng để stream /video_feed
violation_frame_buffer = {}  # Dict[track_id] -> deque of frames gốc cho xe vi phạm (không có bbox) - dùng để tạo video vi phạm gửi Telegram
current_detections = {}  # Lưu detections hiện tại để vẽ lên frame
sent_violation_tracks = set()  # Set các track_id đã gửi video để không gửi lại

# ALPR queue (giữ nguyên cho ALPR worker)
alpr_queue = queue.Queue(maxsize=50)
alpr_worker_running = False

def detection_worker():
    """
    THREAD 2: Detection Worker Thread (detection_worker)
    - Lấy frame từ detection_queue
    - Chạy YOLO để detect xe → trả bbox + class
    - Chạy OC-SORT/ByteTrack để gán track_id
    - Chạy SpeedTracker → tính tốc độ
    - Chạy FastALPR tối đa 2 biển số mỗi frame để tránh chậm
    - Tạo frame_admin = frame.copy()
    - Vẽ bounding box + tốc độ lên frame_admin
    - Lưu frame_admin vào admin_frame_buffer để stream lên web
    - Lưu frame gốc theo từng track vào violation_frame_buffer[track_id]
    - Nếu tốc độ vượt ngưỡng hoặc là vi phạm:
        → Đẩy dữ liệu vào violation_queue (async)
    - Tuyệt đối không vẽ bounding box lên frame dùng cho Telegram/Database
    """
    global current_detections, is_video_upload_mode, stream_queue, admin_frame_buffer, violation_frame_buffer, original_frame_buffer, violation_queue, detector, tracker
    
    # Đợi detector được khởi tạo (lazy load)
    while detector is None or tracker is None:
        init_detector()
        if detector is None or tracker is None:
            print("[DETECTION WORKER] Waiting for detector initialization...")
            time.sleep(1)
    
    while camera_running:
        if len(detection_queue) == 0:
            # TỐI ƯU: Khi upload video, giảm sleep time để xử lý nhanh hơn
            if is_video_upload_mode:
                sleep_time = 0.0001 if DEVICE == 'cuda' else 0.0005  # Rất ngắn cho video upload
            else:
                sleep_time = 0.0005 if DEVICE == 'cuda' else 0.001  # GPU xử lý rất nhanh
            time.sleep(sleep_time)
            continue
        
        try:
            # Kiểm tra detector đã sẵn sàng chưa
            if detector is None or tracker is None:
                time.sleep(0.1)
                continue
            
            frame_data = detection_queue.popleft()
            detect_frame = frame_data['frame']
            original_frame = frame_data['original']
            frame_id = frame_data.get('frame_id', frame_data.get('id', 0))
            
            # Detect xe + FastALPR (tối đa 2 biển số mỗi frame)
            # enable_plate_detection=True: Chạy FastALPR tối đa 2 biển số để tránh chậm
            detections = detector.detect(detect_frame, enable_plate_detection=True)
            
            # Tạo admin_frame để vẽ bbox (từ original_frame)
            admin_frame = original_frame.copy()
            
            # Scale lại bbox về kích thước gốc nếu cần (CHÍNH XÁC HÓA)
            if DETECTION_SCALE < 1.0:
                original_h, original_w = original_frame.shape[:2]
                detect_h, detect_w = detect_frame.shape[:2]
                scale_x = original_w / detect_w
                scale_y = original_h / detect_h
                
                for det in detections:
                    x1, y1, x2, y2 = det['vehicle_bbox']
                    # Scale chính xác hơn - dùng float trước rồi mới làm tròn
                    new_x1 = max(0, min(int(x1 * scale_x + 0.5), original_w - 1))
                    new_y1 = max(0, min(int(y1 * scale_y + 0.5), original_h - 1))
                    new_x2 = max(new_x1 + 1, min(int(x2 * scale_x + 0.5), original_w))
                    new_y2 = max(new_y1 + 1, min(int(y2 * scale_y + 0.5), original_h))
                    
                    det['vehicle_bbox'] = (new_x1, new_y1, new_x2, new_y2)
                    
                    # LƯU Ý: plate_bbox sẽ luôn là None vì không chạy ALPR trong detection worker
                    # ALPR sẽ chạy async trong ALPR worker thread
            
            # Xử lý từng detection và vẽ bbox lên admin_frame
            new_detections = {}
            for detection in detections:
                track_id = detection['track_id']
                vehicle_bbox = detection['vehicle_bbox']
                vehicle_class = detection['vehicle_class']
                plate = detection.get('plate')  # Biển số từ FastALPR (có thể None)
                plate_bbox = detection.get('plate_bbox')  # Bbox biển số (có thể None)
                
                # Tính tốc độ
                speed = tracker.update(track_id, vehicle_bbox)
                
                # Smooth speed với detection cũ
                if track_id in current_detections:
                    old_det = current_detections[track_id]
                    if old_det.get('speed') is not None:
                        if speed is not None:
                            speed = 0.75 * speed + 0.25 * old_det['speed']
                        else:
                            speed = old_det['speed']
                
                detection['speed'] = speed
                new_detections[track_id] = detection
                
                # Lưu frame gốc theo track_id vào original_frame_buffer[track_id]
                # Dùng để crop xe và biển số, tạo video clean
                if track_id not in original_frame_buffer:
                    original_frame_buffer[track_id] = deque(maxlen=90)
                original_frame_buffer[track_id].append({
                    'frame': original_frame.copy(),
                    'frame_id': frame_id,
                    'timestamp': time.time()
                })
                
                # Vẽ bbox lên admin_frame (chỉ cho admin stream)
                try:
                    detector.draw_detections(admin_frame, detection, speed, speed_limit)
                except Exception as e:
                    print(f"[DETECT THREAD] Error drawing detection: {e}")
                
                # Lưu frame gốc vào violation_frame_buffer[track_id] nếu vi phạm
                # Frame này KHÔNG có bbox, dùng để tạo video clean gửi Telegram
                if speed and speed > speed_limit:
                    if track_id not in violation_frame_buffer:
                        violation_frame_buffer[track_id] = deque(maxlen=90)
                    violation_frame_buffer[track_id].append({
                        'frame': original_frame.copy(),  # Frame gốc, KHÔNG có bbox
                        'frame_id': frame_id,
                        'timestamp': time.time()
                    })
                    
                    now = time.time()
                    # Dùng track_id + plate làm cooldown key
                    cooldown_key = f"{track_id}_{plate}" if plate else f"{track_id}"
                    if cooldown_key not in last_violation_time or \
                       now - last_violation_time[cooldown_key] >= VIOLATION_COOLDOWN:
                        last_violation_time[cooldown_key] = now
                        
                        # FASTALPR CHỈ CHẠY TRONG DETECTION THREAD
                        # Crop plate ngay từ ORIGINAL FRAME của cùng thời điểm
                        refined_plate = None
                        refined_plate_bbox = None
                        plate_crop = None
                        
                        try:
                            # Crop vùng xe từ frame gốc để FastALPR detect chính xác hơn
                            x1, y1, x2, y2 = vehicle_bbox
                            padding = 100  # Padding lớn hơn để bao hết biển số
                            crop_x1 = max(0, x1 - padding)
                            crop_y1 = max(0, y1 - padding)
                            crop_x2 = min(original_frame.shape[1], x2 + padding)
                            crop_y2 = min(original_frame.shape[0], y2 + padding)
                            
                            vehicle_region = original_frame[crop_y1:crop_y2, crop_x1:crop_x2].copy()
                            
                            # Dùng FastALPR để detect biển số trên vùng xe
                            if plate_detector_post is not None:
                                plate_results = plate_detector_post.detect(vehicle_region)
                                
                                if plate_results and len(plate_results) > 0:
                                    # Lấy biển số có confidence cao nhất
                                    best_plate = max(plate_results, key=lambda p: p.get('confidence', 0))
                                    
                                    detected_plate = best_plate.get('plate', plate)
                                    # Normalize và validate biển số
                                    normalized_detected = normalize_plate(detected_plate)
                                    
                                    # CHỈ CHẤP NHẬN BIỂN SỐ VIỆT NAM HỢP LỆ
                                    if normalized_detected and is_valid_plate(normalized_detected):
                                        refined_plate = normalized_detected
                                        print(f"[DETECT THREAD] ✅ FastALPR detect biển số hợp lệ: {refined_plate}")
                                        
                                        plate_bbox_local = best_plate.get('bbox')
                                        
                                        if plate_bbox_local:
                                            # Chuyển bbox từ local (vehicle_region) về global (original_frame)
                                            px1_local, py1_local, px2_local, py2_local = plate_bbox_local
                                            refined_plate_bbox = (
                                                crop_x1 + px1_local,
                                                crop_y1 + py1_local,
                                                crop_x1 + px2_local,
                                                crop_y1 + py2_local
                                            )
                                            
                                            # CROP PLATE NGAY TỪ ORIGINAL FRAME (CÙNG THỜI ĐIỂM)
                                            px1, py1, px2, py2 = refined_plate_bbox
                                            
                                            # THÊM PADDING ĐỂ CROP RỘNG HƠN, TRÁNH CẮT MẤT KÝ TỰ
                                            padding_x = max(10, int((px2 - px1) * 0.2))  # 20% padding
                                            padding_y = max(5, int((py2 - py1) * 0.2))   # 20% padding
                                            
                                            px1_padded = max(0, px1 - padding_x)
                                            py1_padded = max(0, py1 - padding_y)
                                            px2_padded = min(original_frame.shape[1], px2 + padding_x)
                                            py2_padded = min(original_frame.shape[0], py2 + padding_y)
                                            
                                            # Đảm bảo bbox nằm trong frame
                                            px1_padded = max(0, min(px1_padded, original_frame.shape[1] - 1))
                                            py1_padded = max(0, min(py1_padded, original_frame.shape[0] - 1))
                                            px2_padded = max(px1_padded + 1, min(px2_padded, original_frame.shape[1]))
                                            py2_padded = max(py1_padded + 1, min(py2_padded, original_frame.shape[0]))
                                            
                                            if px2_padded > px1_padded and py2_padded > py1_padded:
                                                # CROP PLATE TỪ ORIGINAL FRAME - GIỮ NGUYÊN ẢNH GỐC
                                                plate_crop = original_frame[py1_padded:py2_padded, px1_padded:px2_padded].copy()
                                                print(f"[DETECT THREAD] ✅ Đã crop plate từ original frame: {refined_plate} (bbox: {px1_padded}, {py1_padded}, {px2_padded}, {py2_padded})")
                                            else:
                                                print(f"[DETECT THREAD] ⚠️ Bbox plate không hợp lệ sau padding")
                                        else:
                                            print(f"[DETECT THREAD] ⚠️ FastALPR detect được biển số hợp lệ nhưng không có bbox: {refined_plate}")
                                    else:
                                        print(f"[DETECT THREAD] ⚠️ FastALPR detect biển số không hợp lệ: {detected_plate} (normalized: {normalized_detected})")
                                else:
                                    print(f"[DETECT THREAD] ⚠️ FastALPR không detect được biển số trên vùng xe")
                        except Exception as e:
                            print(f"[DETECT THREAD] Lỗi khi dùng FastALPR detect biển số: {e}")
                            import traceback
                            traceback.print_exc()
                        
                        # ĐẨY VÀO QUEUE: Nếu có biển số hợp lệ thì gửi plate_crop, nếu không thì chỉ gửi full_frame
                        # Luôn gửi full_frame (original frame của violation) để violation_worker có thể save
                        violation_data = {
                            'track_id': track_id,
                            'detection': detection,
                            'speed': speed,
                            'full_frame': original_frame.copy(),  # ORIGINAL FRAME của cùng thời điểm
                            'plate': refined_plate,  # Biển số từ FastALPR (có thể None)
                            'plate_bbox': refined_plate_bbox,  # Bbox biển số (có thể None)
                            'plate_crop': plate_crop,  # Plate đã crop từ original frame (có thể None)
                            'vehicle_bbox': vehicle_bbox,
                            'vehicle_class': vehicle_class,
                            'timestamp': time.time()
                        }
                        
                        try:
                            violation_queue.put(violation_data, block=False)
                            if refined_plate:
                                print(f"[DETECT THREAD] ✅ Đã đẩy vi phạm vào queue: plate={refined_plate}, track_id={track_id}, có plate_crop={plate_crop is not None}")
                            else:
                                print(f"[DETECT THREAD] ✅ Đã đẩy vi phạm vào queue (không có biển số): track_id={track_id}")
                        except queue.Full:
                            print(f"[DETECT THREAD] Violation queue đầy, bỏ qua vi phạm track_id={track_id}")
            
            # Cập nhật current_detections
            current_detections = new_detections
            
            # Lưu frame_admin (có bbox) vào admin_frame_buffer để stream lên web
            # Lưu vào buffer chung trước, sau đó video_generator sẽ lấy
            if 'global' not in admin_frame_buffer:
                admin_frame_buffer['global'] = deque(maxlen=90)
            admin_frame_buffer['global'].append({
                'frame': admin_frame,
                'frame_id': frame_id,
                'timestamp': time.time()
            })
            
            # ĐẨY ADMIN_FRAME (CÓ BBOX) VÀO STREAM_QUEUE để hiển thị trên web
            try:
                stream_queue.put(admin_frame, block=False)
            except queue.Full:
                # Nếu queue đầy, bỏ qua frame này (không block)
                pass
            
            # TỐI ƯU MEMORY: Cleanup old tracks (chỉ giữ tracks đang active)
            if tracker is not None:
                active_track_ids = set(det['track_id'] for det in detections)
                tracker.cleanup_old_tracks(active_track_ids)
            
        except Exception as e:
            print(f"[ERROR] Detection worker error: {e}")

# ======================
# THREAD 3: VIOLATION THREAD
# ======================
def violation_worker():
    """
    THREAD 3: Violation Worker Thread (violation_worker)
    - Lấy item từ violation_queue
    - KHÔNG chạy FastALPR (đã chạy trong Detection Thread)
    - KHÔNG crop gì cả (đã crop trong Detection Thread)
    - Chỉ:
        + Lấy full_frame và plate_crop từ queue
        + Crop xe từ full_frame (nếu cần)
        + Lưu ảnh/video sạch vào ổ cứng
        + Viết bản ghi MySQL
        + Đẩy message vào telegram_queue
    """
    global violation_queue, telegram_queue, original_frame_buffer, violation_frame_buffer, camera_running, video_fps, mysql, app, speed_limit
    
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
            
            # Kiểm tra full_frame có sẵn không
            if full_frame is None:
                print(f"[VIOLATION THREAD] ⚠️ Không có full_frame trong violation_data, bỏ qua")
                continue
            
            # Crop xe từ full_frame (original frame của violation)
            x1, y1, x2, y2 = vehicle_bbox
            padding = 50
            crop_x1 = max(0, x1 - padding)
            crop_y1 = max(0, y1 - padding)
            crop_x2 = min(full_frame.shape[1], x2 + padding)
            crop_y2 = min(full_frame.shape[0], y2 + padding)
            
            vehicle_crop = full_frame[crop_y1:crop_y2, crop_x1:crop_x2].copy()
            
            # plate_crop đã được crop trong Detection Thread từ cùng full_frame
            # Không cần crop lại, chỉ cần sử dụng plate_crop từ queue
            
            # Tạo video clean từ violation_frame_buffer[track_id] (nếu có)
            video_clean_path = None
            if track_id in violation_frame_buffer and len(violation_frame_buffer[track_id]) > 0:
                try:
                    h, w = full_frame.shape[:2]
                    fps = video_fps if video_fps > 0 else 30
                    timestamp_str = int(time.time())
                    
                    video_clean_name = f"violation_clean_{timestamp_str}_{track_id}.mp4"
                    video_clean_path = os.path.join("static/violation_videos", video_clean_name)
                    
                    # Tạo video writer
                    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
                    out = cv2.VideoWriter(video_clean_path, fourcc, fps, (w, h))
                    
                    if out.isOpened():
                        # Lấy frames từ violation_frame_buffer[track_id] (frame gốc, không có bbox)
                        frames = list(violation_frame_buffer[track_id])
                        for frame_data in frames:
                            frame = frame_data['frame'] if isinstance(frame_data, dict) else frame_data
                            out.write(frame)
                        out.release()
                        print(f"[VIOLATION THREAD] ✅ Đã tạo video clean: {video_clean_name}")
                    else:
                        print(f"[VIOLATION THREAD] ⚠️ Không thể tạo video writer")
                        video_clean_path = None
                except Exception as e:
                    print(f"[VIOLATION THREAD] Lỗi tạo video clean: {e}")
                    import traceback
                    traceback.print_exc()
                    video_clean_path = None
            
            # Tạo video clean từ violation_frame_buffer[track_id] (không có bbox)
            video_clean_path = None
            if track_id in violation_frame_buffer and len(violation_frame_buffer[track_id]) > 0:
                try:
                    h, w = full_frame.shape[:2]
                    fps = video_fps if video_fps > 0 else 30
                    timestamp_str = int(time.time())
                    
                    video_clean_name = f"violation_clean_{timestamp_str}_{track_id}.mp4"
                    video_clean_path = os.path.join("static/violation_videos", video_clean_name)
                    
                    # Tạo video writer
                    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
                    out = cv2.VideoWriter(video_clean_path, fourcc, fps, (w, h))
                    
                    if out.isOpened():
                        # Lấy frames từ violation_frame_buffer[track_id] (frame gốc, không có bbox)
                        frames = list(violation_frame_buffer[track_id])
                        for frame_data in frames:
                            frame = frame_data['frame'] if isinstance(frame_data, dict) else frame_data
                            out.write(frame)
                        out.release()
                        print(f"[VIOLATION THREAD] ✅ Đã tạo video clean: {video_clean_name}")
                    else:
                        print(f"[VIOLATION THREAD] ⚠️ Không thể tạo video writer")
                        video_clean_path = None
                except Exception as e:
                    print(f"[VIOLATION THREAD] Lỗi tạo video clean: {e}")
                    import traceback
                    traceback.print_exc()
                    video_clean_path = None
            
            # CHỈ LƯU ẢNH NẾU BIỂN SỐ HỢP LỆ
            # Validate biển số trước khi lưu ảnh
            normalized_plate = normalize_plate(plate) if plate else None
            is_plate_valid = normalized_plate and is_valid_plate(normalized_plate)
            
            if not is_plate_valid:
                print(f"[VIOLATION THREAD] ❌ Biển số không hợp lệ '{plate}' (normalized: {normalized_plate}), KHÔNG lưu ảnh và KHÔNG gửi Telegram")
                continue  # Bỏ qua vi phạm này, không lưu ảnh và không gửi
            
            # Lưu ảnh xe và biển số vào ổ cứng (CHỈ KHI BIỂN SỐ HỢP LỆ)
            os.makedirs("static/uploads", exist_ok=True)
            os.makedirs("static/plate_images", exist_ok=True)
            
            timestamp_str = int(time.time())
            vehicle_img_path = None
            plate_img_path = None
            
            # Lưu ảnh xe (toàn cảnh) - BẮT BUỘC
            if vehicle_crop.size > 0:
                vehicle_img_name = f"vehicle_{timestamp_str}_{track_id}.jpg"
                vehicle_img_path = os.path.join("static/uploads", vehicle_img_name)
                cv2.imwrite(vehicle_img_path, vehicle_crop)
                print(f"[VIOLATION THREAD] ✅ Đã lưu ảnh xe (toàn cảnh): {vehicle_img_name}")
            else:
                print(f"[VIOLATION THREAD] ⚠️ Không thể crop ảnh xe, bỏ qua vi phạm")
                continue
            
            # Lưu ảnh biển số (crop) - CHỈ KHI CÓ plate_crop
            if plate_crop is not None and plate_crop.size > 0:
                plate_img_name = f"plate_{timestamp_str}_{track_id}.jpg"
                plate_img_path = os.path.join("static/plate_images", plate_img_name)
                cv2.imwrite(plate_img_path, plate_crop)
                print(f"[VIOLATION THREAD] ✅ Đã lưu ảnh biển số (crop): {plate_img_name}")
            else:
                print(f"[VIOLATION THREAD] ⚠️ Không có ảnh biển số crop, chỉ gửi ảnh xe")
            
            # Viết bản ghi MySQL
            violation_id = None
            try:
                with app.app_context():
                    conn = mysql.connection
                    if conn:
                        cursor = conn.cursor()
                        
                        # Normalize biển số
                        normalized_plate = normalize_plate(plate) if plate else None
                        
                        # Tính exceeded
                        exceeded = speed - speed_limit if speed > speed_limit else 0
                        
                        # Lấy thông tin chủ xe từ database (nếu có)
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
                                # Bảng vehicle_registry không tồn tại hoặc có lỗi - bỏ qua, tiếp tục với None
                                print(f"[VIOLATION THREAD] ⚠️ Không thể lấy thông tin chủ xe từ vehicle_registry: {e}")
                                print(f"[VIOLATION THREAD]    → Tiếp tục lưu vi phạm mà không có thông tin chủ xe")
                                owner_name = None
                                address = None
                                phone = None
                        
                        # Insert vào database - Dùng đúng tên cột trong bảng violations
                        # Bảng violations KHÔNG có owner_name, address, phone - phải lưu vào vehicle_owner
                        # Lấy tên file từ đường dẫn đầy đủ
                        vehicle_img_name = os.path.basename(vehicle_img_path) if vehicle_img_path else None
                        plate_img_name = os.path.basename(plate_img_path) if plate_img_path else None
                        video_name = os.path.basename(video_clean_path) if video_clean_path else None
                        
                        # 1. Lưu hoặc cập nhật thông tin chủ xe vào bảng vehicle_owner
                        if normalized_plate:
                            try:
                                # Kiểm tra xem đã có trong vehicle_owner chưa
                                cursor.execute("SELECT plate FROM vehicle_owner WHERE plate = %s", (normalized_plate,))
                                existing_owner = cursor.fetchone()
                                
                                if existing_owner:
                                    # Cập nhật nếu có thông tin mới
                                    if owner_name or address or phone:
                                        cursor.execute("""
                                            UPDATE vehicle_owner 
                                            SET owner_name = COALESCE(%s, owner_name),
                                                address = COALESCE(%s, address),
                                                phone = COALESCE(%s, phone)
                                            WHERE plate = %s
                                        """, (owner_name, address, phone, normalized_plate))
                                else:
                                    # Tạo mới nếu chưa có
                                    cursor.execute("""
                                        INSERT INTO vehicle_owner (plate, owner_name, address, phone)
                                        VALUES (%s, %s, %s, %s)
                                    """, (normalized_plate, owner_name, address, phone))
                                conn.commit()
                                print(f"[VIOLATION THREAD] ✅ Đã lưu/cập nhật thông tin chủ xe: {normalized_plate}")
                            except Exception as e:
                                print(f"[VIOLATION THREAD] ⚠️ Lỗi khi lưu thông tin chủ xe: {e}")
                                conn.rollback()
                        
                        # 2. Lưu violation vào bảng violations (KHÔNG có owner_name, address, phone)
                        cursor.execute("""
                            INSERT INTO violations 
                            (plate, vehicle_class, speed, speed_limit, image, plate_image, video, status, time)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, 'pending', %s)
                        """, (
                            normalized_plate, vehicle_class,
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
            
            # KIỂM TRA THÔNG TIN BẮT BUỘC TRƯỚC KHI GỬI TELEGRAM
            # BẮT BUỘC: plate (biển số đã drop), vehicle_image_path (ảnh vi phạm xe)
            final_plate = normalized_plate if normalized_plate else plate
            
            if not final_plate:
                print(f"[VIOLATION THREAD] ❌ Bỏ qua vi phạm: Không có biển số (track_id={track_id})")
                continue
            
            if not vehicle_img_path or not os.path.exists(vehicle_img_path):
                print(f"[VIOLATION THREAD] ❌ Bỏ qua vi phạm: Không có ảnh vi phạm xe (track_id={track_id}, path={vehicle_img_path})")
                continue
            
            # Đẩy message vào telegram_queue với đầy đủ thông tin BẮT BUỘC
            # BẮT BUỘC: plate (biển số đã drop), vehicle_image_path (ảnh vi phạm xe)
            # owner_name, address, phone có thể None (sẽ hiển thị "Chưa có thông tin")
            telegram_data = {
                'violation_id': violation_id,
                'plate': final_plate,  # BẮT BUỘC: Biển số đã drop (nhận diện)
                'speed': speed,
                'limit': speed_limit,
                'vehicle_type': vehicle_class,
                'exceeded': exceeded,
                'vehicle_image_path': vehicle_img_path,  # BẮT BUỘC: Ảnh vi phạm xe
                'plate_image_path': plate_img_path,  # Ảnh biển số (có thể None)
                'video_path': video_clean_path,  # Video clean, không có bbox (có thể None)
                'owner_name': owner_name,  # Thông tin chủ xe (có thể None)
                'address': address,  # Thông tin chủ xe (có thể None)
                'phone': phone,  # Thông tin chủ xe (có thể None)
                'timestamp': timestamp
            }
            
            try:
                telegram_queue.put(telegram_data, block=False)
                print(f"[VIOLATION THREAD] ✅ Đã đẩy vào telegram_queue: plate={final_plate}, owner={owner_name}, ảnh={vehicle_img_path}")
            except queue.Full:
                print(f"[VIOLATION THREAD] ⚠️ Telegram queue đầy, bỏ qua")
            
        except queue.Empty:
            # Queue rỗng, tiếp tục chờ
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
    THREAD 1: VideoThread (video_reader)
    - Đọc video đúng FPS gốc
    - KHÔNG chạy AI trong thread này
    - Push frame vào detection_queue mỗi N frame (DETECTION_FREQUENCY)
    - Lưu frame gốc vào original_frame_buffer để dùng cho:
        + crop xe và biển số
        + tạo video sạch (clean)
        + lưu database/telegram
    - KHÔNG vẽ bounding box ở thread này
    """
    global cap, camera_running, original_frame_buffer, detection_queue, video_fps, cap_lock, DETECTION_FREQUENCY, DETECTION_SCALE
    
    frame_count = 0
    last_frame_time = time.time()
    
    # Tính delay dựa trên FPS để video chạy đúng tốc độ gốc
    target_fps = video_fps if video_fps > 0 else 30
    frame_delay = 1.0 / target_fps
    
    print(f"[VIDEO THREAD] ✅ Đã khởi động - Đọc video với tốc độ gốc ({target_fps:.2f} FPS)")
    print(f"[VIDEO THREAD] Detection frequency: {DETECTION_FREQUENCY} (push mỗi {DETECTION_FREQUENCY} frame vào detection_queue)")
    
    while camera_running:
        if cap is None:
            time.sleep(0.1)
            continue
        
        # Điều chỉnh tốc độ capture theo FPS của video (đảm bảo chạy đúng tốc độ gốc)
        current_time = time.time()
        elapsed = current_time - last_frame_time
        
        # Đợi đúng thời gian delay trước khi đọc frame tiếp theo
        if elapsed < frame_delay:
            time.sleep(frame_delay - elapsed)
        
        # Đọc frame từ video (thread-safe)
        frame = None
        ret = False
        with cap_lock:
            if cap is None or not cap.isOpened():
                time.sleep(0.1)
                continue
            ret, frame = cap.read()
        
        # Cập nhật thời gian SAU KHI đọc frame
        last_frame_time = time.time()
        
        if not ret or frame is None:
            # Video kết thúc - loop lại từ đầu
            with cap_lock:
                if cap and cap.isOpened():
                    try:
                        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                        print("[VIDEO THREAD] Video kết thúc, loop lại từ đầu...")
                        time.sleep(0.1)
                        continue
                    except Exception as e:
                        print(f"[VIDEO THREAD] Lỗi khi loop video: {e}")
                        break
                else:
                    print("[VIDEO THREAD] Video capture không mở được, dừng xử lý...")
                    break
        
        frame_count += 1
        
        # Lưu frame gốc vào buffer (KHÔNG CÓ BOUNDING BOX)
        # Lưu vào buffer chung trước, sau đó DetectThread sẽ phân loại theo track_id
        original_frame = frame.copy()
        
        # Lưu frame gốc vào buffer chung (sẽ được phân loại theo track_id bởi DetectThread)
        if 'global' not in original_frame_buffer:
            original_frame_buffer['global'] = deque(maxlen=90)
        
        original_frame_buffer['global'].append({
            'frame': original_frame,
            'frame_id': frame_count,
            'timestamp': time.time()
        })
        
        # Push frame vào detection_queue mỗi N frame (DETECTION_FREQUENCY)
        # Điều này giúp giảm tải cho Detection Thread
        if frame_count % DETECTION_FREQUENCY == 0:
            try:
                if len(detection_queue) < detection_queue.maxlen:
                    # Chuẩn bị detect_frame (resize nếu cần)
                    if DETECTION_SCALE < 1.0:
                        original_h, original_w = frame.shape[:2]
                        detect_w = int(original_w * DETECTION_SCALE)
                        detect_h = int(original_h * DETECTION_SCALE)
                        detect_frame = cv2.resize(frame, (detect_w, detect_h), interpolation=cv2.INTER_LINEAR)
                    else:
                        detect_frame = frame
                    
                    detection_queue.append({
                        'frame': detect_frame,
                        'original': original_frame,
                        'frame_id': frame_count,
                        'timestamp': time.time()
                    })
            except Exception as e:
                print(f"[VIDEO THREAD] Detection queue error: {e}")

# ======================
# THREAD 2: FRAME CAPTURE THREAD
# ======================
def frame_capture_thread():
    """
    THREAD 2: Frame Capture Thread
    - Lấy frame từ original_frame_buffer (đã được Video Stream Thread đọc)
    - Mỗi N frame (ví dụ 3 frame) mới gửi 1 frame vào detection_queue
    - Mục tiêu giảm tải cho detection, tránh bị nghẽn
    - KHÔNG đọc frame trực tiếp từ VideoCapture để tránh skip frame
    """
    global camera_running, detection_queue, original_frame_buffer, DETECTION_FREQUENCY, DETECTION_SCALE
    
    frame_count = 0
    last_processed_frame_id = 0
    
    print(f"[FRAME CAPTURE THREAD] ✅ Đã khởi động - Lấy frame từ buffer, gửi mỗi {DETECTION_FREQUENCY} frame vào detection_queue")
    
    while camera_running:
        if 'global' not in original_frame_buffer or len(original_frame_buffer['global']) == 0:
            time.sleep(0.01)  # Đợi ngắn để có frame mới
            continue
        
        try:
            # Lấy frame mới nhất từ buffer (frame đã được Video Stream Thread đọc)
            # Sử dụng frame mới nhất để đảm bảo không bỏ sót
            if 'global' in original_frame_buffer and len(original_frame_buffer['global']) > 0:
                frame_data = original_frame_buffer['global'][-1]  # Frame mới nhất
                # Lấy frame từ dict hoặc trực tiếp
                if isinstance(frame_data, dict):
                    frame = frame_data['frame']
                    frame_id = frame_data.get('frame_id', frame_count)
                else:
                    frame = frame_data
                    frame_id = frame_count
                
                frame_count += 1
                
                # Chỉ gửi mỗi N frame vào detection_queue
                if frame_count % DETECTION_FREQUENCY == 0:
                    # Chỉ thêm vào queue nếu còn chỗ (không đợi, tránh lag)
                    if len(detection_queue) < detection_queue.maxlen:
                        # Chuẩn bị detect_frame (resize nếu cần)
                        if DETECTION_SCALE < 1.0:
                            original_h, original_w = frame.shape[:2]
                            detect_w = int(original_w * DETECTION_SCALE)
                            detect_h = int(original_h * DETECTION_SCALE)
                            detect_frame = cv2.resize(frame, (detect_w, detect_h), interpolation=cv2.INTER_LINEAR)
                        else:
                            detect_frame = frame
                        
                        # Gửi vào detection_queue
                        detection_queue.append({
                            'frame': detect_frame,
                            'original': frame,
                            'frame_id': frame_id,
                            'timestamp': time.time()
                        })
        except Exception as e:
            print(f"[FRAME CAPTURE] Error: {e}")
            time.sleep(0.01)


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
    
    if not alpr_worker_running:
        alpr_worker_thread_obj = threading.Thread(target=alpr_worker_thread, daemon=True)
        alpr_worker_thread_obj.start()
        print("[ALPR WORKER] 🚀 Đã khởi động ALPR worker thread")

alpr_worker_thread_obj = None

# ======================
# START ALL THREADS
# ======================
def start_video_thread():
    """
    Khởi động 4 thread độc lập:
    1. Video Thread (video_reader) - đọc video đúng FPS gốc, push mỗi N frame vào detection_queue
    2. Detection Thread (detection_worker) - YOLO + tracking + speed + FastALPR (tối đa 2 biển số)
    3. Violation Thread (violation_worker) - crop xe/biển số, tạo video clean, lưu DB, đẩy vào telegram_queue
    4. Telegram Thread (telegram_worker) - gửi ảnh/video clean (không bbox)
    """
    global camera_running
    
    print("[THREAD MANAGER] 🚀 Khởi động 4 thread độc lập...")
    
    # THREAD 1: Video Thread (đọc video với tốc độ gốc)
    try:
        video_stream = threading.Thread(target=video_thread, daemon=True)
        video_stream.start()
        print("[THREAD MANAGER] ✅ Thread 1: Video Thread (video_reader) started")
    except Exception as e:
        print(f"[THREAD MANAGER] ❌ Error starting Video Thread: {e}")
    
    # THREAD 2: Detection Worker Thread
    try:
        detection_worker_thread = threading.Thread(target=detection_worker, daemon=True)
        detection_worker_thread.start()
        print("[THREAD MANAGER] ✅ Thread 2: Detection Worker Thread (detection_worker) started")
    except Exception as e:
        print(f"[THREAD MANAGER] ❌ Error starting Detection Worker Thread: {e}")
    
    # THREAD 3: Violation Worker Thread
    try:
        violation_worker_thread = threading.Thread(target=violation_worker, daemon=True)
        violation_worker_thread.start()
        print("[THREAD MANAGER] ✅ Thread 3: Violation Worker Thread (violation_worker) started")
    except Exception as e:
        print(f"[THREAD MANAGER] ❌ Error starting Violation Worker Thread: {e}")
    
    # THREAD 4: Telegram Worker Thread (đã có sẵn)
    try:
        if not telegram_worker_running:
            telegram_worker_thread_obj = threading.Thread(target=telegram_worker, daemon=True)
            telegram_worker_thread_obj.start()
            print("[THREAD MANAGER] ✅ Thread 4: Telegram Worker Thread (telegram_worker) started")
    except Exception as e:
        print(f"[THREAD MANAGER] ❌ Error starting Telegram Worker Thread: {e}")
    
    # THREAD 4: ALPR Worker Thread
    try:
        start_alpr_worker()
        print("[THREAD MANAGER] ✅ Thread 4: ALPR Worker Thread started")
    except Exception as e:
        print(f"[THREAD MANAGER] ❌ Error starting ALPR Worker Thread: {e}")
    
    print("[THREAD MANAGER] ✅ Tất cả 4 thread đã được khởi động!")

# ======================
# VIDEO GENERATOR (STREAM TO WEB)
# ======================
# Tối ưu streaming: resize frame và giảm JPEG quality để stream mượt hơn
STREAM_WIDTH = 1280  # Width cho video stream (giảm để stream nhanh hơn)
STREAM_JPEG_QUALITY = 80  # JPEG quality (80 = tốc độ tốt, chất lượng đủ dùng)
STREAM_FPS = 30  # FPS mặc định cho stream (sẽ được điều chỉnh theo video)

def video_generator():
    """
    Stream Admin - Detection stream: Có bounding box, text overlay, thông tin tốc độ
    Dùng để hiển thị trên giao diện web (frontend) hoặc trả về cho admin
    TỐI ƯU: Đợi buffer có frame trước khi stream để tránh màn hình đen
    """
    global cap, camera_running, admin_frame_buffer, video_fps
    
    # Tính delay dựa trên FPS để video chạy đúng tốc độ
    target_fps = video_fps if video_fps > 0 else STREAM_FPS
    frame_delay = 1.0 / target_fps  # Thời gian delay giữa các frame
    
    last_frame_time = time.time()
    max_wait_time = 5.0  # Đợi tối đa 5 giây để buffer có frame
    wait_start = time.time()
    
    while camera_running:
        if cap is None:
            time.sleep(0.1)
            continue
        
        # TỐI ƯU: Đợi buffer có frame (tối đa 5 giây) thay vì hiển thị màn hình đen ngay
        # Kiểm tra stream_queue trước (frame có bbox từ DetectThread)
        if stream_queue.empty() and ('global' not in admin_frame_buffer or len(admin_frame_buffer['global']) == 0):
            elapsed_wait = time.time() - wait_start
            if elapsed_wait < max_wait_time:
                # Đợi thêm một chút để buffer có frame
                time.sleep(0.05)
                continue
            else:
                # Sau 5 giây vẫn không có frame, hiển thị thông báo
                black_frame = np.zeros((480, 640, 3), dtype=np.uint8)
                cv2.putText(black_frame, "Waiting for video...", (50, 240), 
                           cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
                encode_params = [int(cv2.IMWRITE_JPEG_QUALITY), STREAM_JPEG_QUALITY]
                _, jpeg = cv2.imencode(".jpg", black_frame, encode_params)
                yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg.tobytes() + b"\r\n")
                time.sleep(0.1)
                continue
        
        # Reset wait timer khi đã có frame
        wait_start = time.time()
        
        # Điều chỉnh tốc độ stream theo FPS của video
        current_time = time.time()
        elapsed = current_time - last_frame_time
        
        if elapsed < frame_delay:
            time.sleep(frame_delay - elapsed)
        
        last_frame_time = time.time()
        
        # Lấy frame từ stream_queue (frame có bbox từ DetectThread) - ưu tiên
        # Fallback: Nếu stream_queue rỗng, lấy từ admin_frame_buffer
        frame = None
        try:
            frame = stream_queue.get(timeout=0.05)  # Lấy từ queue, timeout ngắn hơn
        except queue.Empty:
            # Fallback: Lấy từ admin_frame_buffer nếu stream_queue rỗng
            try:
                if 'global' in admin_frame_buffer and len(admin_frame_buffer['global']) > 0:
                    frame_data = admin_frame_buffer['global'][-1]
                    frame = frame_data['frame'] if isinstance(frame_data, dict) else frame_data
                else:
                    # Nếu cả hai đều rỗng, tạo frame đen
                    raise IndexError("No frame available")
            except (IndexError, KeyError, TypeError):
                # Nếu không có frame, tạo frame đen với thông báo
                black_frame = np.zeros((480, 640, 3), dtype=np.uint8)
                cv2.putText(black_frame, "Waiting for video...", (50, 240), 
                           cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
                encode_params = [int(cv2.IMWRITE_JPEG_QUALITY), STREAM_JPEG_QUALITY]
                _, jpeg = cv2.imencode(".jpg", black_frame, encode_params)
                yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg.tobytes() + b"\r\n")
                time.sleep(0.1)
                continue
        
        if frame is None:
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
    
    # Cleanup khi stream kết thúc
    print("[VIDEO STREAM CLEAN] Stream ended")

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

@app.route("/video_feed")
def video_feed():
    """Stream 2 - Detection stream: Có bounding box, text overlay (cho web/admin)"""
    return Response(video_generator(), mimetype="multipart/x-mixed-replace; boundary=frame")

@app.route("/video_feed_clean")
def video_feed_clean():
    """Stream 1 - Clean stream: Không có bounding box (cho người vi phạm)"""
    return Response(video_generator_clean(), mimetype="multipart/x-mixed-replace; boundary=frame")

@app.route("/upload_video", methods=["POST"])
@login_required
def upload_video():
    """Tối ưu: Upload video nhanh, async processing, immediate response"""
    global cap, tracker, camera_running, video_fps
    
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
        
        # Kiểm tra file có tên không (người dùng đã chọn file)
        if file.filename == '':
            print("[VIDEO UPLOAD] ❌ Empty filename")
            return jsonify({"status": "error", "msg": "Chưa chọn file. Vui lòng chọn file video để upload."})
        
        # Kiểm tra định dạng file
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
            global cap, tracker, camera_running, video_fps, admin_frame_buffer, original_frame_buffer, cap_lock, is_video_upload_mode, detection_queue
            
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
                
                # TỐI ƯU: Sử dụng lock để mở VideoCapture an toàn
                with cap_lock:
                    # Mở video
                    new_cap = cv2.VideoCapture(save_path)
                    
                    # Kiểm tra video có mở được không
                    if not new_cap.isOpened():
                        print(f"[VIDEO UPLOAD] ❌ Error: Cannot open video file: {save_path}")
                        return
                    
                    # TỐI ƯU: Đọc frame đầu tiên ngay để buffer có dữ liệu
                    ret, first_frame = new_cap.read()
                    if ret and first_frame is not None:
                        # Reset video về đầu
                        new_cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                        # Thêm frame vào buffer ngay (buffers là dict, cần khởi tạo 'global' key)
                        if 'global' not in original_frame_buffer:
                            original_frame_buffer['global'] = deque(maxlen=90)
                        if 'global' not in admin_frame_buffer:
                            admin_frame_buffer['global'] = deque(maxlen=90)
                        
                        original_frame_buffer['global'].append({
                            'frame': first_frame.copy(),
                            'frame_id': 0,
                            'timestamp': time.time()
                        })
                        admin_frame_buffer['global'].append({
                            'frame': first_frame.copy(),
                            'frame_id': 0,
                            'timestamp': time.time()
                        })
                        print(f"[VIDEO UPLOAD] ✅ First frame loaded into buffer")
                    
                    # Gán cap sau khi đã mở và đọc frame thành công
                    cap = new_cap
                    
                    # Lấy FPS từ video gốc để chạy đúng tốc độ (vẫn trong lock để an toàn)
                    video_fps = new_cap.get(cv2.CAP_PROP_FPS) or 30
                    if video_fps <= 0:
                        video_fps = 30
                    
                    # KHÔNG giới hạn FPS - để video chạy đúng tốc độ gốc
                    # Nếu video có FPS cao (ví dụ 60 FPS), vẫn chạy đúng tốc độ đó
                    print(f"[VIDEO] FPS gốc của video: {video_fps:.2f} (sẽ chạy đúng tốc độ này)")
                    
                    # Lấy thông tin video (vẫn trong lock)
                    video_width = int(new_cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                    video_height = int(new_cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                    total_frames = int(new_cap.get(cv2.CAP_PROP_FRAME_COUNT))
                    
                    # Đặt frame rate cho video capture
                    new_cap.set(cv2.CAP_PROP_FPS, video_fps)
                
                # In thông tin video (sau khi ra khỏi lock)
                print(f"[VIDEO UPLOAD] ✅ Video opened successfully. FPS: {video_fps}")
                print(f"[VIDEO UPLOAD] Video size: {video_width}x{video_height}")
                print(f"[VIDEO UPLOAD] Total frames: {total_frames}")
                
                # Khởi tạo tracker với pixel_to_meter phù hợp cho video upload
                tracker = SpeedTracker(pixel_to_meter=0.2)
                
                # Reset camera_running và start thread
                camera_running = True
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
    port_str = os.getenv('PORT', '5000')
    port = int(port_str) if port_str.isdigit() else 5000
    
    # FORCE tắt debug mode trong production để tránh block
    debug_env = os.getenv('FLASK_DEBUG', 'False').lower()
    debug = debug_env == 'true' and os.getenv('FLASK_ENV', 'production') == 'development'
    
    # Force production mode nếu không phải development
    if os.getenv('FLASK_ENV', 'production') != 'development':
        debug = False
        os.environ['FLASK_DEBUG'] = '0'
        os.environ['FLASK_ENV'] = 'production'
    
    print("=" * 60)
    print("🚗 PLATE VIOLATION SYSTEM - Starting...")
    print("=" * 60)
    print(f"📍 Server: http://{host}:{port}")
    print(f"🔧 Debug mode: {debug} (FORCED OFF in production)")
    print(f"💾 Database: {app.config['MYSQL_HOST']}/{app.config['MYSQL_DB']}")
    print(f"📱 Telegram: {'Configured' if TELEGRAM_TOKEN else 'Not configured'}")
    print(f"🎯 Detection: Frequency={DETECTION_FREQUENCY}, Scale={DETECTION_SCALE}, Device={DEVICE}")
    print("=" * 60)
    
    # Khởi động Telegram worker thread (non-blocking)
    start_telegram_worker()
    
    # Khởi tạo detector trong thread riêng (lazy load, không block startup)
    def init_detector_async():
        time.sleep(2)  # Đợi 2 giây sau khi server start
        print(">>> Initializing detectors in background...")
        init_detector()
        print(">>> ✅ Detectors initialized!")
    
    detector_thread = threading.Thread(target=init_detector_async, daemon=True)
    detector_thread.start()
    
    print("🚀 Server starting on http://{}:{}".format(host, port))
    print("Press CTRL+C to quit")
    print("=" * 60)
    
    # Chạy server - TẮT reloader và debugger để tránh block
    app.run(
        host=host,
        port=port,
        debug=False,  # Force tắt debug
        threaded=True,
        use_reloader=False,  # Tắt reloader
        use_debugger=False  # Tắt debugger
    )
