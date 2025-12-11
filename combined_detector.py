# combined_detector.py
"""
Detector tối ưu cho web: Nhẹ, mượt, tách biệt rõ ràng
- Vehicle Detection & Tracking: Chỉ tính toán tracking và detection
- Fast-ALPR: Sử dụng PlateDetector từ detector.py (đã chạy ổn)
"""
import cv2
import numpy as np

# Import YOLO với error handling
try:
    from ultralytics import YOLO
    YOLO_AVAILABLE = True
except Exception as e:
    YOLO_AVAILABLE = False
    print(f"⚠️  YOLO import failed: {e}")

# Import PlateDetector từ detector.py (đã chạy ổn)
try:
    from detector import PlateDetector
    PLATE_DETECTOR_AVAILABLE = True
except Exception as e:
    PLATE_DETECTOR_AVAILABLE = False
    print(f"⚠️  PlateDetector import failed: {e}")

# OC-SORT tracking - TỐI ƯU CHO WEB
try:
    from oc_sort import OCSort
    OCSORT_AVAILABLE = True
except Exception as e:
    OCSORT_AVAILABLE = False
    # Fallback to ByteTrack
    try:
        from byte_tracker import BYTETracker
        BYTETRACK_AVAILABLE = True
    except:
        BYTETRACK_AVAILABLE = False


class CombinedDetector:
    def __init__(self, yolo_model='yolo11n.pt', device=None):
        """
        Khởi tạo detector tối ưu cho web - BẮT BUỘC GPU
        - Vehicle detection: YOLO (nhẹ, nhanh) - GPU REQUIRED
        - Tracking: OC-SORT hoặc ByteTrack (mượt) - GPU REQUIRED
        - Plate reading: Fast-ALPR (chỉ chạy khi có xe) - GPU REQUIRED
        """
        # Auto-detect device
        if device is None:
            try:
                import torch
                if torch.cuda.is_available():
                    device = 'cuda'
                    gpu_name = torch.cuda.get_device_name(0)
                    gpu_memory = torch.cuda.get_device_properties(0).total_memory / 1024**3
                    print(f"🚀 GPU CUDA detected: {gpu_name} ({gpu_memory:.1f} GB)")
                elif hasattr(torch.backends, 'mps') and torch.backends.mps.is_available():
                    device = 'mps'
                    print("🚀 GPU MPS (Apple Silicon) detected")
                else:
                    device = 'cpu'
                    print("⚠️  WARNING: No GPU detected!")
            except Exception as e:
                print(f"⚠️  PyTorch import error: {e}")
                device = 'cpu'
        
        # Cho phép CPU với WARNING (không phải error)
        if device == 'cpu':
            print("⚠️  WARNING: CombinedDetector will run on CPU (SLOW performance!)")
            print("⚠️  For optimal performance, please install CUDA and ensure GPU is available")
            print("⚠️  Install CUDA: https://developer.nvidia.com/cuda-downloads")
        
        if not YOLO_AVAILABLE:
            raise ImportError("YOLO is not available. Please install: pip install ultralytics")
        
        # ============================================
        # 1. VEHICLE DETECTION (YOLO) - NHẸ, NHANH
        # ============================================
        print(f">>> Loading YOLO Vehicle Detector on {device.upper()}...")
        try:
            self.yolo = YOLO(yolo_model)
            self.device = device
        except Exception as e:
            print(f"⚠️  YOLO model loading failed: {e}")
            raise
        
        # Các class ID của xe trong COCO dataset
        self.vehicle_classes = {
            2: 'car',
            3: 'motorcycle', 
            5: 'bus',
            7: 'truck'
        }
        
        # ============================================
        # 2. TRACKING - OC-SORT (MỰỢT) hoặc ByteTrack - CẢI THIỆN ĐỘ CHÍNH XÁC
        # ============================================
        if OCSORT_AVAILABLE:
            print(">>> Loading OC-SORT (smooth & accurate tracking)...")
            try:
                # Cải thiện tracking: theo kịp xe nhanh hơn
                self.oc_sort = OCSort(
                    det_thresh=0.25,   # Tăng từ 0.2 lên 0.25 để chính xác hơn
                    max_age=20,        # Giảm từ 30 xuống 20 để phản ứng nhanh hơn
                    min_hits=2,        # Giảm từ 3 xuống 2 để confirm track nhanh hơn
                    iou_threshold=0.25  # Giảm từ 0.3 xuống 0.25 để dễ match hơn, theo kịp xe nhanh hơn
                )
                self.use_ocsort = True
                self.use_bytetrack = False
                print("    ✅ OC-SORT enabled - Tracking chính xác & mượt")
            except Exception as e:
                print(f"    ⚠️  OC-SORT init failed: {e}")
                self.oc_sort = None
                self.use_ocsort = False
                self.use_bytetrack = False
        elif BYTETRACK_AVAILABLE:
            print(">>> Loading ByteTrack (fallback)...")
            try:
                self.byte_tracker = BYTETracker(
                    frame_rate=30,
                    track_thresh=0.25,  # Tăng từ 0.15 lên 0.25 để chính xác hơn
                    track_buffer=20,     # Giảm từ 30 xuống 20 để phản ứng nhanh hơn
                    match_thresh=0.3     # Giảm từ 0.4 xuống 0.3 để dễ match hơn, theo kịp xe nhanh hơn
                )
                self.use_bytetrack = True
                self.use_ocsort = False
                print("    ✅ ByteTrack enabled")
            except Exception as e:
                print(f"    ⚠️  ByteTrack init failed: {e}")
                self.byte_tracker = None
                self.use_bytetrack = False
                self.use_ocsort = False
        else:
            self.use_ocsort = False
            self.use_bytetrack = False
            print(">>> Using YOLO built-in tracking (fallback)")
        
        # ============================================
        # 3. FAST-ALPR - SỬ DỤNG PlateDetector TỪ detector.py
        # ============================================
        if not PLATE_DETECTOR_AVAILABLE:
            print("⚠️  PlateDetector not available - plate detection will be disabled")
            self.plate_detector = None
        else:
            print(f">>> Loading PlateDetector từ detector.py on {device.upper()}...")
            try:
                # Pass device to PlateDetector (có thể là CPU hoặc GPU)
                self.plate_detector = PlateDetector(device=device)
                print(f"    ✅ PlateDetector loaded on {device.upper()} - Sẵn sàng đọc biển số")
            except Exception as e:
                print(f"⚠️  PlateDetector loading failed: {e}")
                print(f"⚠️  Plate detection will be disabled. System will continue without plate detection.")
                self.plate_detector = None  # Disable plate detection thay vì crash
        
        # Cache biển số để tránh đọc lại nhiều lần
        self.plate_cache = {}  # track_id -> {'plate': str, 'bbox': tuple, 'frame_count': int}
        self.plate_cache_max_age = 30  # Giữ cache 30 frames
        
        print(">>> ✅ Combined Detector Loaded - Tối ưu cho web!")
    
    def detect(self, frame, enable_plate_detection=True):
        """
        Phát hiện xe và biển số trong frame
        TỐI ƯU: Chỉ đọc biển số khi có phương tiện
        
        Args:
            frame: Frame cần detect
            enable_plate_detection: Nếu False, chỉ detect xe, không đọc biển số (tối ưu tốc độ)
        
        Returns:
            List các dict: {
                'vehicle_bbox': (x1, y1, x2, y2),
                'vehicle_class': 'car/motorcycle/bus/truck',
                'confidence': 0.xx,
                'track_id': int,
                'plate': 'ABC123' hoặc None,
                'plate_bbox': (x1, y1, x2, y2) hoặc None
            }
        """
        # ============================================
        # BƯỚC 1: DETECT XE BẰNG YOLO (NHẸ, NHANH)
        # ============================================
        detections = []
        
        if self.use_ocsort or self.use_bytetrack:
            # Dùng YOLO chỉ để detect (không tracking tích hợp)
            # TỐI ƯU GPU: Sử dụng FP16 và batch processing
            use_half = (self.device == 'cuda')  # FP16 trên GPU CUDA
            
            results = self.yolo.predict(
                frame, 
                verbose=False, 
                classes=list(self.vehicle_classes.keys()),
                device=self.device,  # BẮT BUỘC GPU
                conf=0.3,   # Tăng từ 0.25 lên 0.3 để chính xác hơn
                iou=0.5,    # Tăng từ 0.45 lên 0.5 để giảm false positive
                half=use_half,  # FP16 trên GPU - TĂNG TỐC 2X
                agnostic_nms=True,  # NMS nhanh hơn
                max_det=50,  # Giữ nguyên
                imgsz=640,   # Tối ưu cho GPU
                stream=False,
                # TỐI ƯU GPU: Thêm các tham số để tăng tốc
                augment=False,  # Tắt augmentation để tăng tốc
                visualize=False  # Tắt visualization để tăng tốc
            )
            
            if results[0].boxes is not None and len(results[0].boxes) > 0:
                boxes = results[0].boxes
                
                # Chuẩn bị dữ liệu cho tracking
                track_inputs = []
                for box in boxes:
                    x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
                    conf = float(box.conf[0].cpu().numpy())
                    cls_id = int(box.cls[0].cpu().numpy())
                    
                    # Chỉ lấy detection có confidence cao để tracking chính xác hơn
                    if conf >= 0.3 and cls_id in self.vehicle_classes:
                        # Đảm bảo bbox hợp lệ
                        if x2 > x1 and y2 > y1:
                            track_inputs.append([x1, y1, x2, y2, conf, cls_id])
                
                # Tracking với OC-SORT hoặc ByteTrack
                if len(track_inputs) > 0:
                    track_inputs = np.array(track_inputs, dtype=np.float32)
                    
                    if self.use_ocsort:
                        online_targets = self.oc_sort.update(track_inputs, frame)
                    else:
                        online_targets = self.byte_tracker.update(track_inputs, frame)
                    
                    # Chuyển đổi kết quả tracking thành detections
                    for track in online_targets:
                        x1, y1, x2, y2 = track.tlbr.astype(int)
                        track_id = int(track.track_id)
                        conf = float(track.score)
                        cls_id = int(track.cls)
                        
                        # Đảm bảo bbox hợp lệ và nằm trong frame
                        h, w = frame.shape[:2]
                        x1 = max(0, min(x1, w - 1))
                        y1 = max(0, min(y1, h - 1))
                        x2 = max(x1 + 1, min(x2, w))
                        y2 = max(y1 + 1, min(y2, h))
                        
                        if cls_id in self.vehicle_classes and x2 > x1 and y2 > y1:
                            detection = {
                                'vehicle_bbox': (int(x1), int(y1), int(x2), int(y2)),
                                'vehicle_class': self.vehicle_classes[cls_id],
                                'confidence': conf,
                                'track_id': track_id,
                                'plate': None,
                                'plate_bbox': None
                            }
                            detections.append(detection)
        else:
            # Fallback: Dùng YOLO tracking tích hợp
            results = self.yolo.track(
                frame, 
                persist=True, 
                verbose=False, 
                classes=list(self.vehicle_classes.keys()),
                device=self.device,
                conf=0.25
            )
            
            if results[0].boxes is not None and len(results[0].boxes) > 0:
                boxes = results[0].boxes
                
                for box in boxes:
                    x1, y1, x2, y2 = box.xyxy[0].cpu().numpy().astype(int)
                    cls_id = int(box.cls[0].cpu().numpy())
                    confidence = float(box.conf[0].cpu().numpy())
                    
                    if box.id is not None:
                        track_id = int(box.id[0].cpu().numpy())
                    else:
                        track_id = hash((x1, y1, x2, y2)) % 100000
                    
                    # Đảm bảo bbox hợp lệ và nằm trong frame
                    h, w = frame.shape[:2]
                    x1 = max(0, min(x1, w - 1))
                    y1 = max(0, min(y1, h - 1))
                    x2 = max(x1 + 1, min(x2, w))
                    y2 = max(y1 + 1, min(y2, h))
                    
                    if confidence > 0.3 and cls_id in self.vehicle_classes and x2 > x1 and y2 > y1:
                        detection = {
                            'vehicle_bbox': (int(x1), int(y1), int(x2), int(y2)),
                            'vehicle_class': self.vehicle_classes[cls_id],
                            'confidence': confidence,
                            'track_id': track_id,
                            'plate': None,
                            'plate_bbox': None
                        }
                        detections.append(detection)
        
        # ============================================
        # BƯỚC 2: ĐỌC BIỂN SỐ (CHỈ KHI CÓ XE) - SỬ DỤNG PlateDetector
        # ============================================
        # TỐI ƯU: Chỉ đọc biển số cho tối đa 2 xe mỗi frame (nhẹ hơn)
        # Ưu tiên xe chưa có biển số hoặc biển số không đầy đủ
        # Nếu enable_plate_detection=False, bỏ qua bước này để tăng tốc độ
        if enable_plate_detection and self.plate_detector is not None and len(detections) > 0:
            # Lọc xe cần đọc biển số
            plates_to_detect = []
            for det in detections:
                track_id = det['track_id']
                
                # Kiểm tra cache
                if track_id in self.plate_cache:
                    cached = self.plate_cache[track_id]
                    # Nếu cache còn mới và biển số đầy đủ (>= 6 ký tự), dùng cache
                    if cached['frame_count'] < self.plate_cache_max_age and len(cached['plate']) >= 6:
                        det['plate'] = cached['plate']
                        det['plate_bbox'] = cached['bbox']
                        continue
                
                # Xe chưa có biển số hoặc biển số không đầy đủ
                if not det.get('plate') or len(det.get('plate', '')) < 6:
                    plates_to_detect.append(det)
            
            # Chỉ đọc tối đa 2 xe mỗi frame để không block
            plates_to_detect = plates_to_detect[:2]
            
            for detection in plates_to_detect:
                x1, y1, x2, y2 = detection['vehicle_bbox']
                track_id = detection['track_id']
                
                # TĂNG PADDING để bao hết biển số (đặc biệt với xe tải, bus)
                # Padding lớn hơn ở phía dưới (nơi thường có biển số)
                padding_top = 30
                padding_bottom = 60  # Tăng padding dưới để bao hết biển số
                padding_left = 40
                padding_right = 40
                
                crop_x1 = max(0, x1 - padding_left)
                crop_y1 = max(0, y1 - padding_top)
                crop_x2 = min(frame.shape[1], x2 + padding_right)
                crop_y2 = min(frame.shape[0], y2 + padding_bottom)
                
                # Đảm bảo kích thước tối thiểu
                if crop_x2 - crop_x1 < 100 or crop_y2 - crop_y1 < 80:
                    continue
                
                vehicle_crop = frame[crop_y1:crop_y2, crop_x1:crop_x2].copy()
                
                # ENHANCE ẢNH để detect tốt hơn (tăng contrast, sharpen)
                if vehicle_crop.size > 0:
                    try:
                        # Chuyển sang grayscale nếu cần
                        if len(vehicle_crop.shape) == 3:
                            gray = cv2.cvtColor(vehicle_crop, cv2.COLOR_BGR2GRAY)
                        else:
                            gray = vehicle_crop
                        
                        # Tăng contrast và brightness
                        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
                        enhanced = clahe.apply(gray)
                        
                        # Chuyển lại về BGR nếu cần
                        if len(vehicle_crop.shape) == 3:
                            enhanced_bgr = cv2.cvtColor(enhanced, cv2.COLOR_GRAY2BGR)
                        else:
                            enhanced_bgr = enhanced
                        
                        # Thử detect với ảnh gốc và ảnh đã enhance
                        best_result = None
                        best_score = 0
                        orig_h, orig_w = vehicle_crop.shape[:2]
                        
                        for test_img in [vehicle_crop, enhanced_bgr]:
                            # Resize nếu quá lớn hoặc quá nhỏ để tăng độ chính xác
                            h, w = test_img.shape[:2]
                            scale_factor = 1.0
                            
                            if w > 1200 or h > 800:
                                scale_factor = min(1200 / w, 800 / h)
                                new_w = int(w * scale_factor)
                                new_h = int(h * scale_factor)
                                test_img_resized = cv2.resize(test_img, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
                            elif w < 200 or h < 150:
                                scale_factor = max(200 / w, 150 / h)
                                new_w = int(w * scale_factor)
                                new_h = int(h * scale_factor)
                                test_img_resized = cv2.resize(test_img, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
                            else:
                                test_img_resized = test_img
                            
                            # Sử dụng PlateDetector từ detector.py (Fast-ALPR model)
                            # Khi đã chụp được xe vi phạm, nhờ Fast-ALPR nhận diện biển số chính xác
                            plate_results = self.plate_detector.detect(test_img_resized)
                            
                            # Log để debug - thấy rõ model đang hoạt động
                            if plate_results and len(plate_results) > 0:
                                print(f"[Fast-ALPR] Detected {len(plate_results)} plate(s) for track {track_id}")
                            
                            if plate_results and len(plate_results) > 0:
                                # Chọn biển số tốt nhất dựa trên confidence, bounding box và text
                                # Ưu tiên confidence từ Fast-ALPR để đảm bảo chính xác
                                for plate_result in plate_results:
                                    plate_text = plate_result['plate']
                                    plate_bbox_crop = plate_result['bbox']
                                    
                                    # Lấy confidence từ Fast-ALPR (nếu có)
                                    plate_confidence = plate_result.get('confidence', 0.5)
                                    detection_conf = plate_result.get('detection_conf', 0.5)
                                    ocr_conf = plate_result.get('ocr_conf', 0.5)
                                    
                                    # Scale lại bbox về kích thước crop gốc (CHÍNH XÁC HÓA)
                                    px1, py1, px2, py2 = plate_bbox_crop
                                    if scale_factor != 1.0:
                                        # Dùng float để tính chính xác trước, sau đó mới làm tròn
                                        px1 = int(round(px1 / scale_factor))
                                        py1 = int(round(py1 / scale_factor))
                                        px2 = int(round(px2 / scale_factor))
                                        py2 = int(round(py2 / scale_factor))
                                    
                                    # Đảm bảo nằm trong crop gốc
                                    px1 = max(0, min(px1, orig_w - 1))
                                    py1 = max(0, min(py1, orig_h - 1))
                                    px2 = max(px1 + 1, min(px2, orig_w))
                                    py2 = max(py1 + 1, min(py2, orig_h))
                                    
                                    # Validate bbox hợp lệ
                                    if px2 <= px1 or py2 <= py1:
                                        continue
                                    
                                    # Tính điểm dựa trên confidence, bounding box và text
                                    score = 0
                                    
                                    # 1. ĐIỂM CHO CONFIDENCE (ƯU TIÊN CAO NHẤT) - Đảm bảo chính xác
                                    # Confidence từ Fast-ALPR là chỉ số quan trọng nhất
                                    score += plate_confidence * 50  # Nhân với 50 để có trọng số lớn
                                    score += detection_conf * 20   # Detection confidence cũng quan trọng
                                    score += ocr_conf * 10          # OCR confidence
                                    
                                    # 2. Điểm cho độ dài text (biển số đầy đủ)
                                    if len(plate_text) >= 8:
                                        score += 25  # Bonus lớn cho biển số đầy đủ (8+ ký tự)
                                    elif len(plate_text) >= 6:
                                        score += 15  # Bonus cho biển số hợp lý (6-7 ký tự)
                                    else:
                                        continue  # Bỏ qua biển số không đầy đủ (< 6 ký tự)
                                    
                                    # 3. Điểm cho kích thước bbox (ưu tiên bbox hợp lý)
                                    bbox_w = px2 - px1
                                    bbox_h = py2 - py1
                                    bbox_area = bbox_w * bbox_h
                                    
                                    # Kích thước hợp lý cho biển số: 80-400px width, 30-100px height
                                    if 80 <= bbox_w <= 400 and 30 <= bbox_h <= 100:
                                        score += 20  # Bonus lớn cho kích thước hợp lý
                                    elif 50 <= bbox_w <= 500 and 20 <= bbox_h <= 120:
                                        score += 10  # Bonus cho kích thước chấp nhận được
                                    
                                    # 4. Điểm cho tỷ lệ khung hình (biển số thường rộng hơn cao)
                                    aspect_ratio = bbox_w / bbox_h if bbox_h > 0 else 0
                                    if 2.0 <= aspect_ratio <= 5.0:  # Tỷ lệ hợp lý cho biển số
                                        score += 15
                                    elif 1.5 <= aspect_ratio <= 6.0:
                                        score += 8
                                    
                                    # 5. Điểm cho vị trí (ưu tiên bbox ở phần dưới của crop - nơi thường có biển số)
                                    # Tính vị trí tương đối trong crop (0 = trên cùng, 1 = dưới cùng)
                                    relative_y = (py1 + py2) / 2.0 / orig_h if orig_h > 0 else 0.5
                                    if relative_y > 0.6:  # Ở phần dưới (60% trở xuống)
                                        score += 10
                                    elif relative_y > 0.5:  # Ở nửa dưới
                                        score += 5
                                    
                                    # 6. Điểm cho diện tích (ưu tiên bbox không quá nhỏ)
                                    if bbox_area >= 3000:  # Diện tích lớn hơn = rõ nét hơn
                                        score += 10
                                    elif bbox_area >= 2000:  # Diện tích tối thiểu hợp lý
                                        score += 5
                                    
                                    # Chỉ chọn biển số có điểm cao hơn (ưu tiên confidence cao)
                                    if score > best_score:
                                        best_result = {
                                            'plate': plate_text,
                                            'bbox': (px1, py1, px2, py2),
                                            'confidence': plate_confidence
                                        }
                                        best_score = score
                        
                        if best_result:
                            plate_text = best_result['plate']
                            plate_bbox_crop = best_result['bbox']
                            plate_conf = best_result.get('confidence', 0.5)
                            
                            # CHUYỂN BBOX VỀ HỆ TỌA ĐỘ GỐC (CHÍNH XÁC HÓA)
                            # Bbox đã được scale về crop gốc, giờ chuyển về frame gốc
                            px1, py1, px2, py2 = plate_bbox_crop
                            
                            # Chuyển bbox về hệ tọa độ gốc của frame (CHÍNH XÁC)
                            # Dùng float để tính chính xác trước, sau đó mới làm tròn
                            abs_px1 = int(round(crop_x1 + px1))
                            abs_py1 = int(round(crop_y1 + py1))
                            abs_px2 = int(round(crop_x1 + px2))
                            abs_py2 = int(round(crop_y1 + py2))
                            
                            # Validate bbox trước khi lưu - Đảm bảo không bị sai
                            h, w = frame.shape[:2]
                            abs_px1 = max(0, min(abs_px1, w - 1))
                            abs_py1 = max(0, min(abs_py1, h - 1))
                            abs_px2 = max(abs_px1 + 1, min(abs_px2, w))
                            abs_py2 = max(abs_py1 + 1, min(abs_py2, h))
                            
                            # Kiểm tra bbox hợp lệ trước khi lưu
                            if abs_px2 > abs_px1 and abs_py2 > abs_py1:
                                # Lưu kết quả chính xác từ Fast-ALPR
                                detection['plate'] = plate_text
                                detection['plate_bbox'] = (abs_px1, abs_py1, abs_px2, abs_py2)
                                
                                # Log kết quả từ Fast-ALPR với confidence
                                print(f"[Fast-ALPR] Track {track_id}: Plate={plate_text} (conf={plate_conf:.2f}), "
                                      f"BBox=({abs_px1},{abs_py1},{abs_px2},{abs_py2}) - CHÍNH XÁC")
                                
                                # Lưu vào cache để tái sử dụng
                                self.plate_cache[track_id] = {
                                    'plate': plate_text,
                                    'bbox': detection['plate_bbox'],
                                    'frame_count': 0,
                                    'confidence': plate_conf
                                }
                            else:
                                print(f"[Fast-ALPR] Track {track_id}: BBox không hợp lệ, bỏ qua")
                    except Exception as e:
                        # In lỗi để debug (không bỏ qua hoàn toàn)
                        print(f"[PLATE DETECT ERROR] {e}")
                        import traceback
                        traceback.print_exc()
        
        # Cập nhật cache age
        for track_id in list(self.plate_cache.keys()):
            self.plate_cache[track_id]['frame_count'] += 1
            if self.plate_cache[track_id]['frame_count'] >= self.plate_cache_max_age:
                del self.plate_cache[track_id]
        
        return detections
    
    def draw_detections(self, frame, detection, speed=None, speed_limit=40):
        """
        Vẽ thông tin xe, biển số và tốc độ lên frame
        Tối ưu cho web: Vẽ nhanh, không block
        """
        # Lấy thông tin
        x1, y1, x2, y2 = detection['vehicle_bbox']
        vehicle_class = detection['vehicle_class']
        confidence = detection['confidence']
        track_id = detection['track_id']
        plate = detection.get('plate')
        plate_bbox = detection.get('plate_bbox')
        
        # Màu sắc theo loại xe
        color_map = {
            'car': (0, 255, 0),        # Xanh lá
            'motorcycle': (255, 0, 0),  # Xanh dương
            'bus': (0, 165, 255),       # Cam
            'truck': (0, 255, 255)      # Vàng
        }
        color = color_map.get(vehicle_class, (255, 255, 255))
        
        # Nếu có tốc độ và vượt quá giới hạn → màu đỏ
        is_violation = False
        if speed is not None and speed > speed_limit:
            color = (0, 0, 255)  # Đỏ
            is_violation = True
        
        # Kiểm tra tọa độ hợp lệ
        h, w = frame.shape[:2]
        x1 = max(0, min(x1, w - 1))
        y1 = max(0, min(y1, h - 1))
        x2 = max(x1 + 1, min(x2, w))
        y2 = max(y1 + 1, min(y2, h))
        
        if x2 <= x1 or y2 <= y1:
            return frame
        
        # Vẽ bounding box xe - VIỀN MỎNG NHẤT (thickness = 1)
        thickness = 1  # Mỏng nhất nhưng vẫn đủ nhìn
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, thickness)
        
        # Tạo label - CHỈ HIỆN TỐC ĐỘ, KHÔNG HIỆN BIỂN SỐ VÀ "VI PHẠM"
        label_parts = []
        
        # Chỉ hiện tốc độ nếu có
        if speed is not None:
            label_parts.append(f"{speed:.1f} km/h")
        
        # Nếu không có tốc độ, không hiện gì
        if not label_parts:
            return frame
        
        label = " ".join(label_parts)
        
        # Vẽ background và text - FONT NHỎ HƠN
        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = 0.4  # Nhỏ hơn (từ 0.6 xuống 0.4)
        thickness_text = 1  # Text mỏng hơn
        (text_width, text_height), baseline = cv2.getTextSize(label, font, font_scale, thickness_text)
        
        text_x = max(0, min(x1 + 3, w - text_width - 3))
        text_y = max(text_height + 3, min(y1 - 5, h - 3))
        
        bg_x1 = max(0, min(x1, w - text_width - 6))
        bg_y1 = max(0, min(y1 - text_height - 8, h - text_height - 3))
        bg_x2 = min(w, bg_x1 + text_width + 6)
        bg_y2 = min(h, bg_y1 + text_height + 8)
        
        if bg_x2 > bg_x1 and bg_y2 > bg_y1:
            cv2.rectangle(frame, (bg_x1, bg_y1), (bg_x2, bg_y2), color, -1)
        
        cv2.putText(frame, label, (text_x, text_y), 
                   font, font_scale, (255, 255, 255), thickness_text)
        
        # KHÔNG VẼ BBOX BIỂN SỐ - Chỉ tối ưu phần chụp biển số
        # Biển số vẫn được detect và lưu trong detection['plate'] và detection['plate_bbox']
        # nhưng không hiển thị text box nhỏ trên frame để tối ưu hiệu suất
        
        return frame
