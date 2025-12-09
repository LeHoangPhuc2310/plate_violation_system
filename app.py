# import pymysql
# pymysql.install_as_MySQLdb()
from flask import Flask, Response, render_template, request, jsonify
from flask_mysqldb import MySQL
import cv2
import time
import json
import os
import requests
from collections import deque

# Lưu buffer 3 giây (90 frames nếu 30 FPS)
frame_buffer = deque(maxlen=90)

TELEGRAM_TOKEN = "8306836477:AAEJSaTQg2Pu7tZQMEHjoDPUSIC3Mz0QtGY"
TELEGRAM_CHAT_ID = 6680799636  # Chat ID của bạn


# biến toàn cục
# Lưu 90 frame cuối cùng (30fps → 3 giây)
buffer = deque(maxlen=90)

cap = cv2.VideoCapture("video.mp4")
fps = 30
width  = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

fourcc = cv2.VideoWriter_fourcc(*'mp4v')

violation_video_path = "violation_3s.mp4"

violation_detected = False
saved = False

while True:
    ret, frame = cap.read()
    if not ret:
        break

    # Lưu vào buffer (cho video trước khi vi phạm)
    buffer.append(frame)

    # -----------------------
    # GIẢ ĐỊNH: nếu tốc độ > 40 → vi phạm
    speed = 45
    if speed > 40:
        violation_detected = True

    # -----------------------
    # Khi phát hiện vi phạm → ghi 3 giây video
    if violation_detected and not saved:
        out = cv2.VideoWriter(violation_video_path, fourcc, fps, (width, height))

        # 1. Ghi 3 giây TRƯỚC khi vi phạm
        for f in buffer:
            out.write(f)

        # 2. Ghi tiếp 3 giây SAU khi vi phạm
        start = time.time()
        while time.time() - start < 3:
            ret2, f2 = cap.read()
            if not ret2:
                break
            out.write(f2)

        out.release()
        saved = True
        print(">>> Đã lưu video 3 giây vi phạm:", violation_video_path)

from detector import PlateDetector
from speed_tracker import SpeedTracker

# ======================
# FLASK APP
# ======================
app = Flask(__name__)

# ======================
# DATABASE CONFIG
# ======================
app.config['MYSQL_HOST'] = 'database-1.c5s02mk0i88r.ap-southeast-2.rds.amazonaws.com'
app.config['MYSQL_USER'] = 'plate_violation'
app.config['MYSQL_PASSWORD'] = '0948411795aZZ'
app.config['MYSQL_DB'] = 'plate_violation'
app.config['MYSQL_CURSORCLASS'] = 'DictCursor'


# app.config['MYSQL_HOST'] = 'localhost'
# app.config['MYSQL_USER'] = 'root'
# app.config['MYSQL_PASSWORD'] = '123aZZ'
# app.config['MYSQL_DB'] = 'plate_violation'
# app.config['MYSQL_CURSORCLASS'] = 'DictCursor'



mysql = MySQL(app)

# ======================
# GLOBAL VAR
# ======================
UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

cap = None
camera_running = False   # <-- cờ điều khiển camera
last_id = 0

detector = PlateDetector()
tracker = SpeedTracker(pixel_to_meter=0.13)

speed_limit = 40
last_violation_time = {}
VIOLATION_COOLDOWN = 3  # giây


# =====================================================
def send_telegram_alert(plate, speed, limit, image_path, video_path, owner_name, address, phone):
    try:
        # nếu ảnh/video không tồn tại -> dùng ảnh mặc định (để tránh lỗi)
        if not os.path.exists(image_path):
            image_path = os.path.abspath("static/no_image.jpg")
        else:
            image_path = os.path.abspath(image_path)

        if not os.path.exists(video_path):
            # nếu không có video, set None để không gửi
            video_path = None
        else:
            video_path = os.path.abspath(video_path)

        # message với thông tin chủ xe
        message = (
            f"🚨 *Cảnh báo vi phạm tốc độ!*\n\n"
            f"🔰 Biển số: *{plate}*\n"
            f"👤 Chủ xe: {owner_name}\n"
            f"🏠 Địa chỉ: {address}\n"
            f"📞 SĐT: {phone}\n\n"
            f"⚡ Tốc độ ghi nhận: *{round(speed,2)} km/h*\n"
            f"🔻 Giới hạn: *{limit} km/h*"
        )

        url_text = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        data_text = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "Markdown"
        }
        requests.post(url_text, data=data_text, timeout=10)

        # gửi ảnh (bắt buộc)
        url_photo = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
        with open(image_path, "rb") as imgf:
            files = {"photo": imgf}
            data_photo = {"chat_id": TELEGRAM_CHAT_ID}
            requests.post(url_photo, files=files, data=data_photo, timeout=20)

        # gửi video (nếu có)
        if video_path:
            url_video = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendVideo"
            with open(video_path, "rb") as vf:
                files = {"video": vf}
                data_video = {"chat_id": TELEGRAM_CHAT_ID, "caption": f"Video vi phạm: {plate}"}
                requests.post(url_video, files=files, data=data_video, timeout=30)

        print("[TELEGRAM] Đã gửi cảnh báo (ảnh + video nếu có).")
    except Exception as e:
        print("[TELEGRAM ERROR]", e)






# VIDEO GENERATOR
# =====================================================
def video_generator():
    global cap, tracker, camera_running, frame_buffer

    while camera_running:
        if cap is None:
            time.sleep(0.1)
            continue

        ret, frame = cap.read()
        if not ret:
            break

        # lưu frame vào buffer để tạo video 3 giây
        frame_buffer.append(frame.copy())

        plates = detector.detect(frame)

        for p in plates:
            x1, y1, x2, y2 = p["bbox"]
            plate = p["plate"]

            # ====== TÍNH TỐC ĐỘ ======
            v = tracker.update(plate, (x1, y1, x2, y2))

            # Vẽ lên frame
            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
            cv2.putText(frame, plate, (x1, y1 - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)

            if v:
                cv2.putText(frame, f"{v} km/h", (x1, y2 + 25),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)

            # ====== CHỈ LƯU KHI VI PHẠM ======
            now = time.time()
            if v and v > speed_limit:

                # CHẶN VI PHẠM TRÙNG TRONG 3 GIÂY
                if plate in last_violation_time:
                    if now - last_violation_time[plate] < VIOLATION_COOLDOWN:
                        continue

                last_violation_time[plate] = now

                # ====== TẠO VIDEO 3 GIÂY ======
                os.makedirs("static/violation_videos", exist_ok=True)
                video_name = f"{plate}_{int(time.time())}.mp4"
                video_path = os.path.join("static/violation_videos", video_name)

                h, w, _ = frame.shape
                fourcc = cv2.VideoWriter_fourcc(*'mp4v')
                out = cv2.VideoWriter(video_path, fourcc, 30, (w, h))

                for bf in list(frame_buffer):
                    out.write(bf)
                out.release()

                # ====== LƯU ẢNH ======
                os.makedirs("static/uploads", exist_ok=True)
                img_name = f"{plate}_{int(time.time())}.jpg"
                img_path = os.path.join("static/uploads", img_name)
                cv2.imwrite(img_path, frame[y1:y2, x1:x2])

                # ====== LƯU DB ======
                with app.app_context():
                    conn = mysql.connection
                    cursor = conn.cursor()

                    # kiểm tra chủ xe
                    cursor.execute("SELECT * FROM vehicle_owner WHERE plate=%s", (plate,))
                    owner = cursor.fetchone()
                    if not owner:
                        cursor.execute("""
                            INSERT INTO vehicle_owner (plate, owner_name, address, phone)
                            VALUES (%s, NULL, NULL, NULL)
                        """, (plate,))
                        conn.commit()

                    cursor.execute("""
                        INSERT INTO violations (plate, speed, speed_limit, image, video, time)
                        VALUES (%s, %s, %s, %s, %s, NOW())
                    """, (plate, v, speed_limit, img_name, video_name))
                    conn.commit()

                    # lấy chủ xe
                    cursor.execute("""
                        SELECT owner_name, address, phone
                        FROM vehicle_owner WHERE plate=%s
                    """, (plate,))
                    owner = cursor.fetchone()

                owner_name = owner["owner_name"] or "Không rõ"
                address = owner["address"] or "Không rõ"
                phone = owner["phone"] or "Không rõ"

                # ====== Gửi TELEGRAM ======
                send_telegram_alert(
                    plate, v, speed_limit,
                    os.path.abspath(img_path),
                    os.path.abspath(video_path),
                    owner_name, address, phone
                )

        # ====== STREAM RA WEB ======
        _, jpeg = cv2.imencode(".jpg", frame)
        yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" +
               jpeg.tobytes() + b"\r\n")

    # khi dừng camera
    if cap:
        try:
            cap.release()
        except:
            pass




# =====================================================
# ROUTES
# =====================================================

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/video_feed")
def video_feed():
    # Response sẽ dùng generator; khi generator kết thúc, stream dừng
    return Response(video_generator(),
                    mimetype="multipart/x-mixed-replace; boundary=frame")


# =====================================================
# UPLOAD VIDEO
# =====================================================
@app.route("/upload_video", methods=["POST"])
def upload_video():
    global cap, tracker, camera_running

    if "video" not in request.files:
        return {"status": "error", "msg": "No file"}

    file = request.files["video"]
    save_path = os.path.join(UPLOAD_FOLDER, "uploaded.mp4")
    file.save(save_path)

    # Mở file video làm nguồn
    if cap is not None:
        try:
            cap.release()
        except Exception:
            pass

    cap = cv2.VideoCapture(save_path)

    # RESET SPEED TRACKER
    tracker = SpeedTracker(pixel_to_meter=0.13)

    # Bật cờ chạy camera để generator phát frame
    camera_running = True

    return {"status": "ok", "msg": "upload_success"}


# =====================================================
# OPEN CAMERA
# =====================================================
@app.route("/open_camera")
def open_camera():
    global cap, tracker, camera_running

    # Nếu đang có cap, release trước
    if cap is not None:
        try:
            cap.release()
        except Exception:
            pass

    cap = cv2.VideoCapture(0)
    tracker = SpeedTracker(pixel_to_meter=0.13)
    camera_running = True

    return {"status": "ok"}


# =====================================================
# STOP CAMERA
# =====================================================
@app.route("/stop_camera")
def stop_camera():
    global cap, camera_running

    # Tắt cờ trước để generator có thể thoát
    camera_running = False

    # Giải phóng capture nếu đang mở
    if cap is not None:
        try:
            cap.release()
        except Exception:
            pass
        cap = None

    return {"status": "ok"}


# =====================LỌC VÀ TÌM KIẾM
@app.route("/history")
def history():
    conn = mysql.connection
    cursor = conn.cursor()

    plate = request.args.get("plate")
    from_date = request.args.get("from_date")
    to_date = request.args.get("to_date")
    speed_over = request.args.get("speed_over")

    query = """
        SELECT 
            v.plate,
            o.owner_name,
            o.address,
            o.phone,
            v.speed,
            v.speed_limit,
            v.time,
            v.image
        FROM violations v
        LEFT JOIN vehicle_owner o ON v.plate = o.plate
        WHERE 1=1
    """
    params = []

    if plate:
        query += " AND v.plate LIKE %s"
        params.append("%" + plate + "%")

    if from_date:
        query += " AND v.time >= %s"
        params.append(from_date + " 00:00:00")

    if to_date:
        query += " AND v.time <= %s"
        params.append(to_date + " 23:59:59")

    if speed_over:
        query += " AND v.speed > %s"
        params.append(speed_over)

    query += " ORDER BY v.time DESC"

    cursor.execute(query, params)
    rows = cursor.fetchall()

    return render_template("history.html", rows=rows)


@app.route("/autocomplete")
def autocomplete():
    term = request.args.get("q", "").upper()

    conn = mysql.connection
    cursor = conn.cursor()

    query = """
        SELECT plate 
        FROM vehicle_owner
        WHERE plate LIKE %s
        LIMIT 5
    """
    like = "%" + term + "%"
    cursor.execute(query, (like,))

    rows = cursor.fetchall()
    result = [row["plate"] for row in rows]

    return jsonify(result)



# API GET VIOLATIONS
# =====================================================
@app.route("/violations")
def get_violations():
    conn = mysql.connection
    cursor = conn.cursor()

    cursor.execute("""
        SELECT v.id, v.plate, v.speed, v.speed_limit, v.image, v.time,
               o.owner_name, o.address, o.phone
        FROM violations v
        LEFT JOIN vehicle_owner o ON v.plate = o.plate
        ORDER BY v.time DESC
        LIMIT 10
    """)

    rows = cursor.fetchall()
    return jsonify(rows)

# =====================================================
# STATS FUNCTIONS
# =====================================================
def get_total_violations():
    conn = mysql.connection
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) AS total FROM violations")
    return cursor.fetchone()["total"]


def get_vehicle_count():
    conn = mysql.connection
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(DISTINCT plate) AS vehicles FROM violations")
    return cursor.fetchone()["vehicles"]


def get_avg_speed():
    conn = mysql.connection
    cursor = conn.cursor()
    cursor.execute("SELECT AVG(speed) AS avg_speed FROM violations")
    result = cursor.fetchone()["avg_speed"]
    return round(result, 2) if result else 0


def get_recent():
    conn = mysql.connection
    cursor = conn.cursor()
    cursor.execute("""
        SELECT plate, speed, time 
        FROM violations 
        ORDER BY time DESC 
        LIMIT 5
    """)
    return cursor.fetchall()

@app.route("/get_stats")
def get_stats():
    stats = {
        "total": get_total_violations(),
        "vehicles": get_vehicle_count(),
        "avg_speed": get_avg_speed(),
        "recent": get_recent()
    }
    return jsonify(stats)

# =====================================================
# SSE STREAM
# =====================================================
@app.route("/stream")
def stream():
    global last_id

    def event_stream():
        global last_id

        while True:
            with app.app_context():
                conn = mysql.connection
                cursor = conn.cursor()

                cursor.execute("""
                    SELECT v.id, v.plate, v.speed, v.speed_limit, v.image, v.time,
                           o.owner_name, o.address, o.phone
                    FROM violations v
                    LEFT JOIN vehicle_owner o ON v.plate = o.plate
                    ORDER BY v.id DESC
                    LIMIT 1
                """)

                row = cursor.fetchone()

                if row and row["id"] != last_id:
                    last_id = row["id"]
                    yield f"data: {json.dumps(row, default=str)}\n\n"

            time.sleep(1)

    return Response(event_stream(), mimetype='text/event-stream')
# DUNG VIDEOUPLOAD
@app.route("/stop_video_upload")
def stop_video_upload():
    global cap, camera_running

    camera_running = False

    if cap is not None:
        try:
            cap.release()
        except:
            pass
        cap = None

    return {"status": "ok", "msg": "video_stopped"}

# =====================================================
# MAIN
# =====================================================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
