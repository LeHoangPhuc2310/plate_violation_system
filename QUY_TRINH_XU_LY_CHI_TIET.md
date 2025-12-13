# 📋 QUY TRÌNH XỬ LÝ CHI TIẾT TỪ A-Z - HỆ THỐNG NHẬN DIỆN BIỂN SỐ & TÍNH TOÁN TỐC ĐỘ

## 🎯 TỔNG QUAN HỆ THỐNG

Hệ thống nhận diện biển số và tính toán tốc độ vi phạm giao thông sử dụng:
- **YOLOv11n**: Phát hiện xe (ô tô, xe máy, xe tải, xe bus)
- **OC-SORT/ByteTrack**: Theo dõi xe (tracking) với Kalman Filter
- **Fast-ALPR**: Đọc biển số xe Việt Nam
- **SpeedTracker**: Tính toán tốc độ dựa trên vị trí và thời gian
- **Flask**: Web framework để hiển thị và quản lý
- **MySQL**: Lưu trữ dữ liệu vi phạm
- **Telegram Bot**: Gửi thông báo vi phạm

---

## 🏗️ KIẾN TRÚC 4 THREAD ĐỘC LẬP

### THREAD 1: VIDEO THREAD (video_thread)
**Mục đích**: Đọc video/camera với tốc độ gốc, không bị block

### THREAD 2: DETECTION WORKER (detection_worker)
**Mục đích**: Xử lý detection, tracking, tính tốc độ, đọc biển số

### THREAD 3: VIOLATION WORKER (violation_worker)
**Mục đích**: Xử lý vi phạm, crop ảnh, lưu database, đẩy vào telegram queue

### THREAD 4: TELEGRAM WORKER (telegram_worker)
**Mục đích**: Gửi thông báo Telegram tuần tự (tránh spam API)

### THREAD 5: ALPR WORKER (alpr_worker_thread)
**Mục đích**: Xử lý đọc biển số từ ảnh vi phạm đã lưu (post-processing)

---

## 📊 QUY TRÌNH XỬ LÝ CHI TIẾT

### PHASE 1: KHỞI ĐỘNG HỆ THỐNG

#### 1.1. Import và Khởi tạo Flask App
```
app.py (dòng 1-76)
├── Import các thư viện: Flask, OpenCV, numpy, threading, queue
├── Import detectors: CombinedDetector, SpeedTracker, PlateDetector
├── Tạo Flask app và config database (MySQL)
└── Test database connection (async, không block startup)
```

#### 1.2. Auto-detect GPU/CPU
```
app.py (dòng 119-185)
├── Kiểm tra CUDA (GPU NVIDIA)
├── Kiểm tra MPS (GPU Apple Silicon)
└── Fallback về CPU nếu không có GPU
```

**Cấu hình theo device:**
- **GPU (CUDA)**: `DETECTION_FREQUENCY=1`, `DETECTION_SCALE=1.0`, buffer 90 frames
- **CPU**: `DETECTION_FREQUENCY=1`, `DETECTION_SCALE=0.7`, buffer 60 frames

#### 1.3. Lazy Loading Detectors
```
app.py (dòng 195-238)
├── init_detector() được gọi khi cần (không block startup)
├── CombinedDetector: YOLOv11n + OC-SORT/ByteTrack + Fast-ALPR
├── SpeedTracker: Tính tốc độ dựa trên pixel_to_meter
└── PlateDetector (post-processing): Enhanced hoặc Standard Fast-ALPR
```

#### 1.4. Khởi động 5 Thread
```
app.py (dòng 2437-2489)
├── Thread 1: video_thread (đọc video)
├── Thread 2: detection_worker (detect + track)
├── Thread 3: violation_worker (xử lý vi phạm)
├── Thread 4: telegram_worker (gửi Telegram)
└── Thread 5: alpr_worker_thread (post-processing ALPR)
```

---

### PHASE 2: ĐỌC VIDEO/CAMERA

#### 2.1. Video Thread (video_thread)
```
app.py (dòng 2192-2395)
```

**Quy trình:**
1. **Mở video source**:
   - Camera: `cv2.VideoCapture(0)` hoặc URL
   - Video file: `cv2.VideoCapture(file_path)`
   - Upload video: Lưu vào `uploads/uploaded.mp4`

2. **Đọc frame với tốc độ gốc**:
   ```python
   while camera_running:
       ret, frame = cap.read()
       if not ret: break
       
       # Lưu original frame
       original_frame = frame.copy()
       
       # Scale frame nếu cần (tối ưu performance)
       if DETECTION_SCALE < 1.0:
           detect_frame = cv2.resize(frame, (new_w, new_h))
       else:
           detect_frame = frame
       
       # Đẩy vào detection_queue (không block)
       frame_data = {
           'frame': detect_frame,
           'original': original_frame,
           'frame_id': frame_id
       }
       if len(detection_queue) < detection_queue.maxlen:
           detection_queue.append(frame_data)
       
       # Đọc với tốc độ FPS gốc
       time.sleep(1.0 / video_fps)
```

3. **Lưu frame vào buffers**:
   - `original_frame_buffer`: Frame gốc (không bbox) - dùng để crop
   - Chỉ lưu khi có detection (tối ưu memory)

---

### PHASE 3: DETECTION & TRACKING

#### 3.1. Detection Worker (detection_worker)
```
app.py (dòng 1618-1869)
```

**Quy trình chi tiết:**

##### Bước 3.1.1: Lấy frame từ queue
```python
frame_data = detection_queue.popleft()
detect_frame = frame_data['frame']      # Frame đã scale (nếu cần)
original_frame = frame_data['original'] # Frame gốc (full resolution)
```

##### Bước 3.1.2: Khởi tạo detector (lazy load)
```python
if detector is None:
    init_detector()  # Chỉ load khi cần
```

##### Bước 3.1.3: Detect xe bằng YOLO
```python
# combined_detector.py (dòng 161-296)
detections = detector.detect(detect_frame, enable_plate_detection=True)
```

**Chi tiết trong CombinedDetector.detect():**

**A. YOLO Detection:**
```python
# combined_detector.py (dòng 190-205)
results = self.yolo.predict(
    frame,
    device=self.device,      # GPU (cuda/mps) hoặc CPU
    classes=[2,3,5,7],       # car, motorcycle, bus, truck
    conf=0.3,                # Confidence threshold
    iou=0.5,                 # NMS threshold
    half=True if GPU else False,  # FP16 trên GPU
    max_det=50
)
```

**Classes được detect:**
- `2`: car (ô tô)
- `3`: motorcycle (xe máy)
- `5`: bus (xe bus)
- `7`: truck (xe tải)

**B. Tracking với OC-SORT hoặc ByteTrack:**
```python
# combined_detector.py (dòng 227-230)
if self.use_ocsort:
    online_targets = self.oc_sort.update(track_inputs, frame)
else:
    online_targets = self.byte_tracker.update(track_inputs, frame)
```

**OC-SORT Tracking (oc_sort.py):**
- Sử dụng Kalman Filter (7D state: x, y, aspect_ratio, height, vx, vy, va)
- Hungarian algorithm để match detection với track
- IoU threshold: 0.25 (điều chỉnh để theo kịp xe nhanh)
- max_age: 20 frames (xe mất dấu quá 20 frames thì xóa)

**ByteTrack Tracking (byte_tracker.py):**
- Fallback nếu OC-SORT không available
- Sử dụng Kalman Filter (8D state)
- Tương tự OC-SORT nhưng đơn giản hơn

**C. Scale bbox về kích thước gốc:**
```python
# app.py (dòng 1682-1696)
if DETECTION_SCALE < 1.0:
    scale_x = original_w / detect_w
    scale_y = original_h / detect_h
    # Scale bbox về frame gốc
    new_x1 = int(x1 * scale_x + 0.5)
    new_y1 = int(y1 * scale_y + 0.5)
    # ... (đảm bảo nằm trong frame)
```

##### Bước 3.1.4: Tính tốc độ (SpeedTracker)
```python
# app.py (dòng 1700-1710)
for det in detections:
    track_id = det['track_id']
    bbox = det['vehicle_bbox']
    
    # Cập nhật tracker
    speed = tracker.update(track_id, bbox)
    det['speed'] = speed
```

**SpeedTracker.update() (speed_tracker.py):**
```python
# speed_tracker.py (dòng 20-83)
def update(self, track_id, bbox):
    # Lấy center point
    cx = (x1 + x2) / 2.0
    cy = (y1 + y2) / 2.0
    now = time.time()
    
    # Thêm vào lịch sử vị trí (deque maxlen=8)
    self.position_history[track_id].append((now, (cx, cy)))
    
    # Tính khoảng cách pixel giữa 2 điểm gần nhất
    (t1, (x1_pos, y1_pos)) = history[-2]
    (t2, (x2_pos, y2_pos)) = history[-1]
    pixel_dist = sqrt((x2-x1)² + (y2-y1)²)
    time_passed = t2 - t1
    
    # Chuyển đổi sang mét
    meter_dist = pixel_dist * self.pixel_to_meter  # 0.13 cho camera, 0.2 cho video
    
    # Tính tốc độ
    speed_ms = meter_dist / time_passed  # m/s
    speed_kmh = speed_ms * 3.6
    
    # Smooth với exponential moving average (75% mới, 25% cũ)
    if item["speed"] is not None:
        speed_kmh = 0.75 * speed_kmh + 0.25 * item["speed"]
    
    return round(speed_kmh, 2)
```

**pixel_to_meter:**
- Camera: `0.13` (điều chỉnh theo góc camera)
- Video upload: `0.2` (có thể khác tùy video)

##### Bước 3.1.5: Đọc biển số (Fast-ALPR)
```python
# combined_detector.py (dòng 304-541)
if enable_plate_detection and self.plate_detector is not None:
    # Chỉ đọc tối đa 2 xe mỗi frame (tối ưu)
    plates_to_detect = detections[:2]
    
    for detection in plates_to_detect:
        # Crop vùng xe (có padding để bao hết biển số)
        vehicle_crop = frame[y1-padding:y2+padding, x1-padding:x2+padding]
        
        # Enhance ảnh (CLAHE, sharpen)
        enhanced = enhance_image(vehicle_crop)
        
        # Detect biển số với Fast-ALPR
        plate_results = self.plate_detector.detect(enhanced)
        
        # Chọn biển số tốt nhất (dựa trên confidence, kích thước, vị trí)
        best_plate = select_best_plate(plate_results)
        
        # Lưu vào detection
        detection['plate'] = best_plate['plate']
        detection['plate_bbox'] = best_plate['bbox']  # Trong hệ tọa độ gốc
```

**PlateDetector.detect() (detector.py):**
```python
# detector.py (dòng 73-166)
def detect(self, frame):
    # Gọi Fast-ALPR
    results = self.alpr.predict(frame)
    
    for r in results:
        # Lấy bbox từ Fast-ALPR
        x1 = int(r.detection.bounding_box.x1)
        y1 = int(r.detection.bounding_box.y1)
        x2 = int(r.detection.bounding_box.x2)
        y2 = int(r.detection.bounding_box.y2)
        
        # Lấy text từ OCR
        plate_text = r.ocr.text.strip()
        
        # Lấy confidence
        detection_conf = r.detection.confidence
        ocr_conf = r.ocr.confidence
        overall_confidence = detection_conf * 0.6 + ocr_conf * 0.4
        
        # Ổn định biển số (tránh nhảy liên tục)
        if bbox_hash in plate_memory:
            old_plate = plate_memory[bbox_hash]
            if similar(old_plate, plate_text) > 0.8:
                plate_text = old_plate  # Dùng biển cũ nếu giống >80%
        
        plates.append({
            'bbox': (x1, y1, x2, y2),
            'plate': plate_text,
            'confidence': overall_confidence
        })
    
    return plates
```

**Cache biển số:**
- Lưu `plate_cache[track_id]` để tránh đọc lại
- Cache age: 30 frames (nếu biển số >= 6 ký tự)

##### Bước 3.1.6: Vẽ bounding box và tốc độ
```python
# app.py (dòng 1720-1755)
admin_frame = original_frame.copy()

for det in detections:
    # Vẽ bbox và tốc độ lên admin_frame
    admin_frame = detector.draw_detections(
        admin_frame, det, 
        speed=det['speed'], 
        speed_limit=speed_limit
    )
```

**draw_detections() (combined_detector.py):**
```python
# combined_detector.py (dòng 543-622)
def draw_detections(self, frame, detection, speed=None, speed_limit=40):
    # Màu theo loại xe
    color_map = {
        'car': (0, 255, 0),      # Xanh lá
        'motorcycle': (255, 0, 0), # Xanh dương
        'bus': (0, 165, 255),      # Cam
        'truck': (0, 255, 255)     # Vàng
    }
    
    # Nếu vượt tốc độ → màu đỏ
    if speed and speed > speed_limit:
        color = (0, 0, 255)  # Đỏ
    
    # Vẽ bbox (thickness=1, mỏng nhất)
    cv2.rectangle(frame, (x1, y1), (x2, y2), color, 1)
    
    # Vẽ label: chỉ hiện tốc độ (ví dụ: "65.3 km/h")
    label = f"{speed:.1f} km/h"
    cv2.putText(frame, label, (x1+3, y1-5), ...)
```

##### Bước 3.1.7: Lưu frame vào buffers
```python
# app.py (dòng 1861-1869)
# Lưu admin_frame (có bbox) vào buffer để stream
admin_frame_buffer['global'].append({
    'frame': admin_frame,
    'frame_id': frame_id,
    'timestamp': time.time()
})

# Đẩy vào stream_queue (ưu tiên cho video_generator)
stream_queue.put(admin_frame, block=False)

# Lưu original_frame (không bbox) vào violation_frame_buffer nếu có vi phạm
if speed > speed_limit:
    if track_id not in violation_frame_buffer:
        violation_frame_buffer[track_id] = deque(maxlen=90)
    violation_frame_buffer[track_id].append(original_frame)
```

##### Bước 3.1.8: Phát hiện vi phạm và đẩy vào violation_queue
```python
# app.py (dòng 1750-1843)
for det in detections:
    track_id = det['track_id']
    speed = det.get('speed')
    plate = det.get('plate')
    
    # Kiểm tra vi phạm tốc độ
    if speed and speed > speed_limit:
        # Cooldown để tránh spam (3 giây)
        cooldown_key = f"{track_id}_{plate}"
        now = time.time()
        
        if cooldown_key not in last_violation_time or \
           now - last_violation_time[cooldown_key] >= VIOLATION_COOLDOWN:
            
            last_violation_time[cooldown_key] = now
            
            # Đẩy vào violation_queue
            violation_data = {
                'track_id': track_id,
                'detection': det,
                'speed': speed,
                'full_frame': original_frame,  # Frame gốc
                'plate': plate,
                'plate_bbox': det.get('plate_bbox'),
                'vehicle_bbox': det['vehicle_bbox'],
                'vehicle_class': det['vehicle_class']
            }
            violation_queue.put(violation_data, block=False)
```

---

### PHASE 4: XỬ LÝ VI PHẠM

#### 4.1. Violation Worker (violation_worker)
```
app.py (dòng 1894-2190)
```

**Quy trình chi tiết:**

##### Bước 4.1.1: Lấy dữ liệu vi phạm từ queue
```python
violation_data = violation_queue.get(timeout=1.0)
track_id = violation_data['track_id']
detection = violation_data['detection']
speed = violation_data['speed']
full_frame = violation_data['full_frame']  # Frame gốc
plate = violation_data.get('plate')
plate_bbox = violation_data.get('plate_bbox')
vehicle_bbox = violation_data['vehicle_bbox']
```

##### Bước 4.1.2: Tạo record tạm trong database
```python
# app.py (dòng 1942-2005)
with app.app_context():
    conn = mysql.connection
    cursor = conn.cursor()
    
    # Tạo violation record (chưa có biển số chính xác)
    cursor.execute("""
        INSERT INTO violations (speed, speed_limit, time, vehicle_class)
        VALUES (%s, %s, %s, %s)
    """, (speed, speed_limit, get_vietnam_time(), vehicle_class))
    
    violation_id = cursor.lastrowid
    conn.commit()
```

##### Bước 4.1.3: Crop và lưu ảnh vi phạm
```python
# app.py (dòng 2007-2090)
# Crop xe từ frame gốc
x1, y1, x2, y2 = vehicle_bbox
vehicle_img = full_frame[y1:y2, x1:x2].copy()

# Lưu ảnh vi phạm
timestamp = int(time.time())
violation_img_name = f"violation_{violation_id}_{timestamp}.jpg"
violation_img_path = os.path.join("static/uploads", violation_img_name)
cv2.imwrite(violation_img_path, vehicle_img, [cv2.IMWRITE_JPEG_QUALITY, 95])
```

##### Bước 4.1.4: Đẩy vào ALPR queue để đọc biển số từ ảnh
```python
# app.py (dòng 2092-2108)
alpr_queue.put({
    'violation_id': violation_id,
    'violation_img_path': violation_img_path,
    'vehicle_bbox': vehicle_bbox,
    'full_frame': full_frame,
    'speed': speed,
    'vehicle_class': vehicle_class
}, block=False)
```

##### Bước 4.1.5: Tạo video vi phạm (nếu có violation_frame_buffer)
```python
# app.py (dòng 2110-2185)
if track_id in violation_frame_buffer and len(violation_frame_buffer[track_id]) > 0:
    frames = list(violation_frame_buffer[track_id])
    
    # Tạo video từ frames (không có bbox)
    video_path = create_video_from_frames(frames, violation_id)
    
    # Xóa buffer sau khi tạo video
    del violation_frame_buffer[track_id]
```

---

### PHASE 5: POST-PROCESSING ALPR

#### 5.1. ALPR Worker Thread (alpr_worker_thread)
```
app.py (dòng 2300-2420)
```

**Quy trình chi tiết:**

##### Bước 5.1.1: Lấy task từ ALPR queue
```python
task = alpr_queue.get(timeout=1.0)
violation_id = task['violation_id']
violation_img_path = task['violation_img_path']
full_frame = task['full_frame']
vehicle_bbox = task['vehicle_bbox']
```

##### Bước 5.1.2: Đọc ảnh vi phạm đã lưu
```python
# app.py (dòng 1050-1105)
detection_frame = cv2.imread(violation_img_path)

# Gọi Fast-ALPR để đọc biển số từ ảnh tĩnh
if plate_detector_post is not None:
    plate_results_raw = plate_detector_post.detect(detection_frame)
else:
    plate_results_raw = []
```

**Enhanced Plate Detector (nếu available):**
- Thử Fast-ALPR với ảnh gốc
- Nếu không có kết quả, thử các preprocessing methods:
  - CLAHE (contrast enhancement)
  - Sharpen
  - Denoise
  - Brightness adjustment
  - Contrast enhancement
  - Combined (tất cả)
- Nếu vẫn không có, thử EasyOCR (fallback)
- Ensemble kết quả từ tất cả phương pháp

##### Bước 5.1.3: Validate và normalize biển số
```python
# app.py (dòng 1110-1180)
def is_valid_plate(plate):
    """Validate biển số Việt Nam: 2 số + 1 chữ cái + 5 số"""
    pattern = r"^[0-9]{2}[A-Z][0-9]{5}$"
    return re.match(pattern, plate) is not None

def normalize_plate(plate):
    """Loại bỏ khoảng trắng, ký tự đặc biệt"""
    return plate.replace(" ", "").replace(".", "").upper()

# Normalize và validate
detected_plate_text = normalize_plate(best_plate_result['plate'])
if not is_valid_plate(detected_plate_text):
    print("Biển số không hợp lệ, bỏ qua")
```

##### Bước 5.1.4: Crop và enhance ảnh biển số
```python
# app.py (dòng 1200-1468)
if plate_bbox:
    px1, py1, px2, py2 = plate_bbox
    
    # Crop biển số từ ảnh vi phạm
    plate_img = detection_frame[py1:py2, px1:px2].copy()
    
    # Enhance ảnh biển số
    # 1. Grayscale
    gray = cv2.cvtColor(plate_img, cv2.COLOR_BGR2GRAY)
    
    # 2. CLAHE (contrast enhancement)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
    enhanced = clahe.apply(gray)
    
    # 3. Sharpen
    gaussian = cv2.GaussianBlur(enhanced, (0, 0), 2.0)
    sharpened = cv2.addWeighted(enhanced, 1.5, gaussian, -0.5, 0)
    
    # 4. Tăng saturation (chuyển lại BGR)
    hsv = cv2.cvtColor(sharpened, cv2.COLOR_BGR2HSV)
    h, s, v = cv2.split(hsv)
    s = cv2.multiply(s, 1.2)  # Tăng saturation 20%
    hsv_enhanced = cv2.merge([h, s, v])
    sharpened = cv2.cvtColor(hsv_enhanced, cv2.COLOR_HSV2BGR)
    
    # 5. Resize nếu cần (tối thiểu 200px width)
    if w < 200:
        scale = 200 / w
        sharpened = cv2.resize(sharpened, (new_w, new_h), cv2.INTER_CUBIC)
    
    # Lưu ảnh biển số
    plate_img_name = f"{detected_plate_text}_{timestamp}_plate.jpg"
    plate_img_path = os.path.join("static/plate_images", plate_img_name)
    cv2.imwrite(plate_img_path, sharpened, [cv2.IMWRITE_JPEG_QUALITY, 95])
```

##### Bước 5.1.5: Cập nhật database với biển số chính xác
```python
# app.py (dòng 1476-1532)
with app.app_context():
    conn = mysql.connection
    cursor = conn.cursor()
    
    # Tạo hoặc cập nhật vehicle_owner
    cursor.execute("SELECT * FROM vehicle_owner WHERE plate=%s", (detected_plate_text,))
    owner = cursor.fetchone()
    if not owner:
        cursor.execute("""
            INSERT INTO vehicle_owner (plate, owner_name, address, phone)
            VALUES (%s, NULL, NULL, NULL)
        """, (detected_plate_text,))
        conn.commit()
    
    # Cập nhật violation với biển số và ảnh biển số
    cursor.execute("""
        UPDATE violations 
        SET plate=%s, plate_image=%s, vehicle_class=%s
        WHERE id=%s
    """, (detected_plate_text, plate_img_name, vehicle_class, violation_id))
    conn.commit()
    
    # Lấy thông tin owner
    cursor.execute("""
        SELECT owner_name, address, phone 
        FROM vehicle_owner 
        WHERE plate=%s
    """, (detected_plate_text,))
    owner = cursor.fetchone()
```

##### Bước 5.1.6: Xóa record nếu không có biển số hợp lệ
```python
# app.py (dòng 1533-1576)
if not detected_plate_text or not is_valid_plate(detected_plate_text) or \
   not plate_img_path or not os.path.exists(plate_img_path):
    
    # Xóa violation record
    cursor.execute("DELETE FROM violations WHERE id=%s", (violation_id,))
    conn.commit()
    
    # Xóa các file đã lưu
    if violation_img_path:
        os.remove(violation_img_path)
    if video_path:
        os.remove(video_path)
    
    print(f"Đã xóa violation ID {violation_id} vì thiếu biển số hợp lệ hoặc ảnh biển số")
```

##### Bước 5.1.7: Đẩy vào Telegram queue
```python
# app.py (dòng 1514-1528)
queue_telegram_alert(
    plate=detected_plate_text,
    speed=speed,
    limit=speed_limit,
    full_img_path=violation_img_path,
    plate_img_path=plate_img_path,
    video_path=video_path,
    owner_name=owner_name,
    address=address,
    phone=phone,
    vehicle_class=vehicle_class,
    violation_id=violation_id
)
```

---

### PHASE 6: GỬI TELEGRAM

#### 6.1. Telegram Worker (telegram_worker)
```
app.py (dòng 261-375)
```

**Quy trình chi tiết:**

##### Bước 6.1.1: Lấy vi phạm từ telegram_queue
```python
violation_data = telegram_queue.get(timeout=1)

full_img_path = violation_data.get('vehicle_image_path')
plate_img_path = violation_data.get('plate_image_path')
video_path = violation_data.get('video_path')
plate = violation_data.get('plate')
speed = violation_data.get('speed')
```

##### Bước 6.1.2: Gửi Telegram alert
```python
# app.py (dòng 288-300)
send_telegram_alert(
    plate=plate,
    speed=speed,
    limit=speed_limit,
    full_img_path=full_img_path,      # Ảnh xe vi phạm (clean, không bbox)
    plate_img_path=plate_img_path,    # Ảnh biển số
    video_path=video_path,            # Video vi phạm (clean, không bbox)
    owner_name=owner_name,
    address=address,
    phone=phone,
    vehicle_class=vehicle_class,
    violation_id=violation_id
)
```

**send_telegram_alert() (app.py dòng 378-500):**
```python
def send_telegram_alert(...):
    # Tạo message text
    message = f"""
🚨 VI PHẠM TỐC ĐỘ
    
Biển số: {plate}
Tốc độ: {speed} km/h
Giới hạn: {limit} km/h
Vượt quá: {speed - limit} km/h
    
Chủ xe: {owner_name}
Địa chỉ: {address}
SĐT: {phone}
    
Loại xe: {vehicle_class}
Thời gian: {format_vietnam_time()}
    """
    
    # Gửi ảnh xe vi phạm
    with open(full_img_path, 'rb') as photo:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto",
            data={'chat_id': TELEGRAM_CHAT_ID, 'caption': message},
            files={'photo': photo}
        )
    
    # Gửi ảnh biển số
    if plate_img_path:
        with open(plate_img_path, 'rb') as photo:
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto",
                data={'chat_id': TELEGRAM_CHAT_ID, 'caption': f"Biển số: {plate}"},
                files={'photo': photo}
            )
    
    # Gửi video (nếu có)
    if video_path:
        with open(video_path, 'rb') as video:
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendVideo",
                data={'chat_id': TELEGRAM_CHAT_ID, 'caption': f"Video vi phạm: {plate}"},
                files={'video': video}
            )
```

**Đảm bảo gửi tuần tự** (tránh spam API Telegram):
- Queue chỉ xử lý 1 item tại một thời điểm
- Đợi gửi xong mới lấy item tiếp theo

---

### PHASE 7: STREAM VIDEO LÊN WEB

#### 7.1. Video Generator (video_generator)
```
app.py (dòng 2499-2594)
```

**Quy trình:**

##### Bước 7.1.1: Lấy frame từ stream_queue hoặc admin_frame_buffer
```python
# Ưu tiên stream_queue (frame mới nhất từ detection_worker)
try:
    frame = stream_queue.get(timeout=0.05)
except queue.Empty:
    # Fallback: Lấy từ admin_frame_buffer
    if 'global' in admin_frame_buffer:
        frame = admin_frame_buffer['global'][-1]['frame']
```

##### Bước 7.1.2: Resize và encode JPEG
```python
# Resize để stream nhanh hơn
if original_w > STREAM_WIDTH:  # 1280px
    frame = cv2.resize(frame, (STREAM_WIDTH, new_h))

# Encode JPEG với quality 80
encode_params = [cv2.IMWRITE_JPEG_QUALITY, 80]
_, jpeg = cv2.imencode(".jpg", frame, encode_params)

# Yield MJPEG frame
yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg.tobytes() + b"\r\n")
```

##### Bước 7.1.3: Điều chỉnh tốc độ theo FPS
```python
target_fps = video_fps if video_fps > 0 else 30
frame_delay = 1.0 / target_fps

current_time = time.time()
elapsed = current_time - last_frame_time
if elapsed < frame_delay:
    time.sleep(frame_delay - elapsed)
```

##### Bước 7.1.4: Flask route /video_feed
```python
# app.py (dòng 2600-2605)
@app.route('/video_feed')
def video_feed():
    return Response(
        video_generator(),
        mimetype='multipart/x-mixed-replace; boundary=frame'
    )
```

**Frontend hiển thị:**
```html
<!-- templates/index.html -->
<img src="/video_feed" class="monitoring-video" />
```

---

## 🔄 LUỒNG DỮ LIỆU TỔNG QUAN

```
┌─────────────────┐
│  VIDEO SOURCE   │ (Camera/Video file)
│  (video_thread) │
└────────┬────────┘
         │ Frame
         ▼
┌─────────────────┐
│ detection_queue │ (deque, maxlen=15-20)
└────────┬────────┘
         │
         ▼
┌──────────────────────┐
│  DETECTION WORKER    │
│  (detection_worker)  │
├──────────────────────┤
│ 1. YOLO detect xe    │
│ 2. OC-SORT tracking  │
│ 3. SpeedTracker      │
│ 4. Fast-ALPR         │
│ 5. Vẽ bbox + speed   │
└────────┬─────────────┘
         │
         ├──► admin_frame ──► stream_queue ──► video_generator ──► /video_feed
         │
         ├──► original_frame ──► violation_frame_buffer[track_id]
         │
         └──► violation_data ──► violation_queue
                                      │
                                      ▼
                            ┌──────────────────┐
                            │ VIOLATION WORKER │
                            │(violation_worker)│
                            ├──────────────────┤
                            │ 1. Tạo DB record │
                            │ 2. Crop ảnh      │
                            │ 3. Tạo video     │
                            │ 4. ALPR queue    │
                            └────────┬─────────┘
                                     │
                                     ▼
                            ┌──────────────────┐
                            │   ALPR QUEUE     │
                            └────────┬─────────┘
                                     │
                                     ▼
                            ┌──────────────────┐
                            │  ALPR WORKER     │
                            │(alpr_worker_thread)│
                            ├──────────────────┤
                            │ 1. Đọc biển số   │
                            │ 2. Validate      │
                            │ 3. Crop ảnh BP   │
                            │ 4. Update DB     │
                            │ 5. Telegram queue│
                            └────────┬─────────┘
                                     │
                                     ▼
                            ┌──────────────────┐
                            │ TELEGRAM QUEUE   │
                            └────────┬─────────┘
                                     │
                                     ▼
                            ┌──────────────────┐
                            │ TELEGRAM WORKER  │
                            │(telegram_worker) │
                            ├──────────────────┤
                            │ Gửi ảnh + video  │
                            │ qua Telegram Bot │
                            └──────────────────┘
```

---

## 🎯 CÁC BUFFER VÀ QUEUE

### 1. detection_queue (deque)
- **Mục đích**: Queue frame từ video_thread → detection_worker
- **Kiểu**: `collections.deque`
- **Size**: 15-20 frames (tùy GPU/CPU và mode)
- **Dữ liệu**: `{'frame': detect_frame, 'original': original_frame, 'frame_id': id}`

### 2. stream_queue (queue.Queue)
- **Mục đích**: Queue frame có bbox từ detection_worker → video_generator
- **Kiểu**: `queue.Queue`
- **Size**: 30 frames
- **Dữ liệu**: `admin_frame` (numpy array)

### 3. violation_queue (queue.Queue)
- **Mục đích**: Queue vi phạm từ detection_worker → violation_worker
- **Kiểu**: `queue.Queue`
- **Size**: 20 items
- **Dữ liệu**: `{'track_id': int, 'detection': dict, 'speed': float, ...}`

### 4. alpr_queue (queue.Queue)
- **Mục đích**: Queue vi phạm cần đọc biển số → alpr_worker
- **Kiểu**: `queue.Queue`
- **Size**: 50 items
- **Dữ liệu**: `{'violation_id': int, 'violation_img_path': str, ...}`

### 5. telegram_queue (queue.Queue)
- **Mục đích**: Queue vi phạm cần gửi Telegram → telegram_worker
- **Kiểu**: `queue.Queue`
- **Size**: 50 items
- **Dữ liệu**: `{'plate': str, 'speed': float, 'full_img_path': str, ...}`

### 6. admin_frame_buffer (dict)
- **Mục đích**: Buffer frame có bbox (backup cho stream_queue)
- **Kiểu**: `dict['global'] -> deque`
- **Size**: 90 frames (GPU) hoặc 60 frames (CPU)
- **Dữ liệu**: `{'frame': admin_frame, 'frame_id': int, 'timestamp': float}`

### 7. violation_frame_buffer (dict)
- **Mục đích**: Buffer frame gốc theo track_id để tạo video vi phạm
- **Kiểu**: `dict[track_id] -> deque`
- **Size**: 90 frames mỗi track
- **Dữ liệu**: `original_frame` (numpy array, không có bbox)

---

## 🔧 CÁC THUẬT TOÁN QUAN TRỌNG

### 1. Kalman Filter (Tracking)
- **Mục đích**: Dự đoán vị trí xe tiếp theo (làm mượt tracking)
- **State**: [x, y, aspect_ratio, height, vx, vy, va] (OC-SORT) hoặc [x1, y1, x2, y2, vx1, vy1, vx2, vy2] (ByteTrack)
- **Update**: Khi có detection mới
- **Predict**: Khi không có detection (xe bị che khuất)

### 2. Hungarian Algorithm (Matching)
- **Mục đích**: Match detection với track hiện tại
- **Cost matrix**: 1 - IoU (IoU càng cao, cost càng thấp)
- **IoU threshold**: 0.25 (OC-SORT) hoặc 0.3 (ByteTrack)

### 3. Exponential Moving Average (Speed Smoothing)
- **Mục đích**: Làm mượt tốc độ (tránh nhảy liên tục)
- **Công thức**: `speed_new = 0.75 * speed_current + 0.25 * speed_old`
- **Lý do**: Tốc độ thay đổi từ từ, không đột ngột

### 4. Plate Memory (Stabilization)
- **Mục đích**: Ổn định biển số (tránh nhảy từ "ABC123" sang "ABC124")
- **Cơ chế**: Lưu biển số cũ, nếu biển số mới giống >80% thì dùng biển cũ
- **Similarity**: SequenceMatcher (difflib)

---

## 📊 DATABASE SCHEMA

### Table: violations
```sql
CREATE TABLE violations (
    id INT PRIMARY KEY AUTO_INCREMENT,
    plate VARCHAR(20),              -- Biển số (cập nhật sau khi ALPR)
    speed FLOAT,                    -- Tốc độ (km/h)
    speed_limit INT,                -- Giới hạn tốc độ (km/h)
    time DATETIME,                  -- Thời gian vi phạm (UTC+7)
    image VARCHAR(255),             -- Ảnh vi phạm (xe)
    plate_image VARCHAR(255),       -- Ảnh biển số
    video_path VARCHAR(255),        -- Video vi phạm (nếu có)
    vehicle_class VARCHAR(50)       -- Loại xe (car/motorcycle/bus/truck)
);
```

### Table: vehicle_owner
```sql
CREATE TABLE vehicle_owner (
    id INT PRIMARY KEY AUTO_INCREMENT,
    plate VARCHAR(20) UNIQUE,       -- Biển số
    owner_name VARCHAR(255),        -- Tên chủ xe
    address VARCHAR(255),           -- Địa chỉ
    phone VARCHAR(20)               -- Số điện thoại
);
```

---

## 🚀 TỐI ƯU HIỆU SUẤT

### 1. GPU Acceleration
- YOLO: FP16 trên GPU CUDA (tăng tốc 2x)
- Fast-ALPR: GPU support
- PyTorch: CUDA/MPS

### 2. Multi-threading
- 5 thread độc lập (không block lẫn nhau)
- Queue-based communication (thread-safe)

### 3. Frame Scaling
- GPU: Scale 1.0 (full resolution)
- CPU: Scale 0.7 (giảm 30% để tăng tốc)

### 4. Plate Detection Optimization
- Chỉ đọc tối đa 2 biển số mỗi frame
- Cache biển số (30 frames)
- Skip nếu biển số >= 6 ký tự và cache còn mới

### 5. Memory Management
- Cleanup old tracks (SpeedTracker)
- Limited buffer size (deque maxlen)
- Xóa violation_frame_buffer sau khi tạo video

---

## 📝 GHI CHÚ QUAN TRỌNG

1. **Frame gốc (original_frame)**: Không bao giờ vẽ bbox lên frame này (dùng để crop và gửi Telegram)

2. **Admin frame (admin_frame)**: Frame có bbox và tốc độ (dùng để stream lên web)

3. **Cooldown vi phạm**: 3 giây để tránh spam (cùng track_id + plate)

4. **Validate biển số**: Chỉ lưu vi phạm có biển số hợp lệ (format: 2 số + 1 chữ + 5 số)

5. **Timezone**: Tất cả thời gian lưu ở UTC+7 (Vietnam)

---

## 🎬 KẾT LUẬN

Hệ thống được thiết kế với kiến trúc đa luồng, tách biệt rõ ràng giữa các giai đoạn xử lý. Mỗi thread có nhiệm vụ riêng và giao tiếp qua queue, đảm bảo không block lẫn nhau và tận dụng tối đa GPU.

**Ưu điểm:**
- Xử lý real-time mượt mà
- Tận dụng GPU tối đa
- Không block video stream
- Scalable (có thể thêm thread)

**Hạn chế:**
- Yêu cầu GPU để đạt hiệu suất tốt
- Memory usage cao (nhiều buffer)
- Phức tạp trong debugging (multi-threading)

---

*Tài liệu này mô tả chi tiết quy trình xử lý từ A-Z của hệ thống nhận diện biển số và tính toán tốc độ vi phạm giao thông.*

