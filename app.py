from flask import Flask, Response, render_template, request, jsonify
from flask_mysqldb import MySQL
import cv2
import time
import os
import requests
from collections import deque

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
app.config['MYSQL_USER'] = 'root'
app.config['MYSQL_PASSWORD'] = '123aZZ'
app.config['MYSQL_DB'] = 'plate_violation'
app.config['MYSQL_CURSORCLASS'] = 'DictCursor'

mysql = MySQL(app)

# ======================
# GLOBAL VAR
# ======================
UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

cap = None
camera_running = False   # Cờ bật camera/video
frame_buffer = deque(maxlen=90)  # Lưu 3 giây video (30fps)
last_id = 0

detector = PlateDetector()
tracker = SpeedTracker(pixel_to_meter=0.13)
speed_limit = 40
last_violation_time = {}
VIOLATION_COOLDOWN = 3  # giây

# ======================
# TELEGRAM CONFIG
# ======================
TELEGRAM_TOKEN = "8306836477:AAEJSaTQg2Pu7tZQMEHjoDPUSIC3Mz0QtGY"
TELEGRAM_CHAT_ID = 6680799636

# ======================
# FUNCTIONS
# ======================
def send_telegram_alert(plate, speed, limit, image_path, video_path, owner_name, address, phone):
    try:
        if not os.path.exists(image_path):
            image_path = os.path.abspath("static/no_image.jpg")
        else:
            image_path = os.path.abspath(image_path)

        if not os.path.exists(video_path):
            video_path = None
        else:
            video_path = os.path.abspath(video_path)

        message = (
            f"🚨 *Cảnh báo vi phạm tốc độ!*\n\n"
            f"🔰 Biển số: *{plate}*\n"
            f"👤 Chủ xe: {owner_name}\n"
            f"🏠 Địa chỉ: {address}\n"
            f"📞 SĐT: {phone}\n\n"
            f"⚡ Tốc độ ghi nhận: *{round(speed,2)} km/h*\n"
            f"🔻 Giới hạn: *{limit} km/h*"
        )

        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                      data={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"},
                      timeout=10)

        with open(image_path, "rb") as imgf:
            requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto",
                          files={"photo": imgf}, data={"chat_id": TELEGRAM_CHAT_ID}, timeout=20)

        if video_path:
            with open(video_path, "rb") as vf:
                requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendVideo",
                              files={"video": vf},
                              data={"chat_id": TELEGRAM_CHAT_ID, "caption": f"Video vi phạm: {plate}"},
                              timeout=30)
        print("[TELEGRAM] Đã gửi cảnh báo.")
    except Exception as e:
        print("[TELEGRAM ERROR]", e)

# ======================
# VIDEO GENERATOR
# ======================
def video_generator():
    global cap, tracker, camera_running, frame_buffer

    while camera_running:
        if cap is None:
            time.sleep(0.1)
            continue

        ret, frame = cap.read()
        if not ret:
            break

        frame_buffer.append(frame.copy())
        plates = detector.detect(frame)

        for p in plates:
            x1, y1, x2, y2 = p["bbox"]
            plate = p["plate"]
            v = tracker.update(plate, (x1, y1, x2, y2))

            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
            cv2.putText(frame, plate, (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
            if v:
                cv2.putText(frame, f"{v} km/h", (x1, y2 + 25), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)

            now = time.time()
            if v and v > speed_limit:
                if plate in last_violation_time and now - last_violation_time[plate] < VIOLATION_COOLDOWN:
                    continue

                last_violation_time[plate] = now

                # ================== LƯU VIDEO 3 GIÂY
                os.makedirs("static/violation_videos", exist_ok=True)
                video_name = f"{plate}_{int(time.time())}.mp4"
                video_path = os.path.join("static/violation_videos", video_name)

                h, w, _ = frame.shape
                out = cv2.VideoWriter(video_path, cv2.VideoWriter_fourcc(*'mp4v'), 30, (w, h))
                for bf in list(frame_buffer):
                    out.write(bf)
                out.release()

                # ================== LƯU ẢNH
                os.makedirs("static/uploads", exist_ok=True)
                img_name = f"{plate}_{int(time.time())}.jpg"
                img_path = os.path.join("static/uploads", img_name)
                cv2.imwrite(img_path, frame[y1:y2, x1:x2])

                # ================== LƯU DB
                with app.app_context():
                    conn = mysql.connection
                    cursor = conn.cursor()

                    cursor.execute("SELECT * FROM vehicle_owner WHERE plate=%s", (plate,))
                    owner = cursor.fetchone()
                    if not owner:
                        cursor.execute("INSERT INTO vehicle_owner (plate, owner_name, address, phone) VALUES (%s, NULL, NULL, NULL)", (plate,))
                        conn.commit()

                    cursor.execute("INSERT INTO violations (plate, speed, speed_limit, image, video, time) VALUES (%s, %s, %s, %s, %s, NOW())",
                                   (plate, v, speed_limit, img_name, video_name))
                    conn.commit()

                    cursor.execute("SELECT owner_name, address, phone FROM vehicle_owner WHERE plate=%s", (plate,))
                    owner = cursor.fetchone()

                owner_name = owner["owner_name"] or "Không rõ"
                address = owner["address"] or "Không rõ"
                phone = owner["phone"] or "Không rõ"

                send_telegram_alert(plate, v, speed_limit, os.path.abspath(img_path), os.path.abspath(video_path),
                                    owner_name, address, phone)

        _, jpeg = cv2.imencode(".jpg", frame)
        yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg.tobytes() + b"\r\n")

    if cap:
        try: cap.release()
        except: pass

# ======================
# ROUTES
# ======================
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/video_feed")
def video_feed():
    return Response(video_generator(), mimetype="multipart/x-mixed-replace; boundary=frame")

@app.route("/upload_video", methods=["POST"])
def upload_video():
    global cap, tracker, camera_running

    if "video" not in request.files:
        return {"status": "error", "msg": "No file"}

    file = request.files["video"]
    save_path = os.path.join(UPLOAD_FOLDER, "uploaded.mp4")
    file.save(save_path)

    if cap is not None:
        try: cap.release()
        except: pass

    cap = cv2.VideoCapture(save_path)
    tracker = SpeedTracker(pixel_to_meter=0.13)
    camera_running = True

    return {"status": "ok", "msg": "upload_success"}

@app.route("/open_camera")
def open_camera():
    global cap, tracker, camera_running
    if cap is not None:
        try: cap.release()
        except: pass
    cap = cv2.VideoCapture(0)
    tracker = SpeedTracker(pixel_to_meter=0.13)
    camera_running = True
    return {"status": "ok"}

@app.route("/stop_camera")
def stop_camera():
    global cap, camera_running
    camera_running = False
    if cap:
        try: cap.release()
        except: pass
        cap = None
    return {"status": "ok"}

@app.route("/stop_video_upload")
def stop_video_upload():
    global cap, camera_running
    camera_running = False
    if cap:
        try: cap.release()
        except: pass
        cap = None
    return {"status": "ok"}

# ====================== HISTORY & AUTOCOMPLETE ======================
@app.route("/history")
def history():
    conn = mysql.connection
    cursor = conn.cursor()
    plate = request.args.get("plate")
    from_date = request.args.get("from_date")
    to_date = request.args.get("to_date")
    speed_over = request.args.get("speed_over")

    query = """SELECT v.plate, o.owner_name, o.address, o.phone, v.speed, v.speed_limit, v.time, v.image
               FROM violations v
               LEFT JOIN vehicle_owner o ON v.plate=o.plate
               WHERE 1=1"""
    params = []
    if plate: params += ["%" + plate + "%"]; query += " AND v.plate LIKE %s"
    if from_date: params += [from_date+" 00:00:00"]; query += " AND v.time >= %s"
    if to_date: params += [to_date+" 23:59:59"]; query += " AND v.time <= %s"
    if speed_over: params += [speed_over]; query += " AND v.speed > %s"
    query += " ORDER BY v.time DESC"

    cursor.execute(query, params)
    rows = cursor.fetchall()
    return render_template("history.html", rows=rows)

@app.route("/autocomplete")
def autocomplete():
    term = request.args.get("q", "").upper()
    conn = mysql.connection
    cursor = conn.cursor()
    cursor.execute("SELECT plate FROM vehicle_owner WHERE plate LIKE %s LIMIT 5", ("%" + term + "%",))
    rows = cursor.fetchall()
    return jsonify([row["plate"] for row in rows])

# ====================== VIOLATIONS API ======================
@app.route("/violations")
def get_violations():
    conn = mysql.connection
    cursor = conn.cursor()
    cursor.execute("""SELECT v.id, v.plate, v.speed, v.speed_limit, v.image, v.time,
                      o.owner_name, o.address, o.phone
                      FROM violations v
                      LEFT JOIN vehicle_owner o ON v.plate=o.plate
                      ORDER BY v.time DESC LIMIT 10""")
    return jsonify(cursor.fetchall())

# ====================== STATS ======================
@app.route("/get_stats")
def get_stats():
    conn = mysql.connection
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) AS total FROM violations")
    total = cursor.fetchone()["total"]

    cursor.execute("SELECT COUNT(DISTINCT plate) AS vehicles FROM violations")
    vehicles = cursor.fetchone()["vehicles"]

    cursor.execute("SELECT AVG(speed) AS avg_speed FROM violations")
    avg_speed = cursor.fetchone()["avg_speed"] or 0
    avg_speed = round(avg_speed,2)

    cursor.execute("SELECT plate, speed, time FROM violations ORDER BY time DESC LIMIT 5")
    recent = cursor.fetchall()

    return jsonify({"total": total, "vehicles": vehicles, "avg_speed": avg_speed, "recent": recent})

# ====================== SSE STREAM ======================
@app.route("/stream")
def stream():
    global last_id
    def event_stream():
        global last_id
        while True:
            with app.app_context():
                conn = mysql.connection
                cursor = conn.cursor()
                cursor.execute("""SELECT v.id, v.plate, v.speed, v.speed_limit, v.image, v.time,
                                  o.owner_name, o.address, o.phone
                                  FROM violations v
                                  LEFT JOIN vehicle_owner o ON v.plate=o.plate
                                  ORDER BY v.id DESC LIMIT 1""")
                row = cursor.fetchone()
                if row and row["id"] != last_id:
                    last_id = row["id"]
                    yield f"data: {json.dumps(row, default=str)}\n\n"
            time.sleep(1)
    return Response(event_stream(), mimetype='text/event-stream')

# ====================== MAIN ======================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
