import os
import cv2
import time
import threading
from queue import Queue
from collections import deque
from datetime import datetime
from .shared_memory import SharedFramePool, ROICropBuffer
from .track_buffer import get_buffer_manager

# History-based OCR system
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tracker.track_history_manager import TrackHistoryManager
from utils.logger import get_logger

logger = get_logger(__name__)


class VideoProcessor:

    def __init__(self, detector, tracker, speed_calc, alpr, violation_handler,
                 db_handler=None, telegram=None):
        self.detector = detector
        self.tracker = tracker
        self.speed_calc = speed_calc
        self.alpr = alpr
        self.violation_handler = violation_handler
        self.db = db_handler
        self.telegram = telegram

        from alpr import PlateVoter, VehicleCollector
        from speed import SpeedCalculator

        self.vehicle_collector = VehicleCollector(max_frames=30)
        self.plate_voter = PlateVoter(min_consensus=1)

        self.processing_speed_calc = SpeedCalculator(
            line1_y=speed_calc.line1_y,
            line2_y=speed_calc.line2_y,
            real_distance_meters=speed_calc.real_distance,
            fps=speed_calc.fps
        )

        self.is_running = False
        self.is_paused = False
        self.current_video = None
        self.cap = None
        self.frame_count = 0
        self.fps = 30.0
        self.width = 0
        self.height = 0
        self.total_frames = 0
        self.loop_video = True  # Mặc định loop video

        # Display state
        self.annotated_frame = None
        self.display_detections = []
        self.display_lock = threading.Lock()

        # ========== OPTIMIZED MEMORY MANAGEMENT ==========
        # Shared frame pool (replaces frame copies)
        self.frame_pool = SharedFramePool(pool_size=100)
        # ROI crop buffer (replaces full frame buffer)
        self.roi_buffer = ROICropBuffer(maxlen=15)
        # Track buffer manager (stores plate crops + best frame per track)
        self.track_buffer_manager = get_buffer_manager(max_crops_per_track=10)

        # ========== QUEUES (INCREASED SIZES) ==========
        # Thread 1 → Thread 2
        self.detection_queue = deque(maxlen=200)  # Increased: 100 → 200

        # Thread 1 → Web Stream
        self.stream_queue_clean = Queue(maxsize=100)  # Increased: 30 → 100

        # Thread 1 → Thread 3 (Proactive ALPR)
        self.alpr_proactive_queue = Queue(maxsize=100)  # Increased: 50 → 100

        # Thread 2 → Thread 4 (Realtime ALPR when violation)
        self.alpr_realtime_queue = Queue(maxsize=200)  # Tăng lên 200 để tránh queue full khi có nhiều vi phạm

        # Thread 4 → Thread 5 (Best frame selector)
        self.best_frame_queue = Queue(maxsize=200)  # Tăng lên 200 để tránh queue full

        # Thread 5 → Thread 6 (Violation worker)
        self.violation_queue = Queue(maxsize=200)  # Tăng lên 200 để tránh queue full

        # Thread 6 → Thread 7 (Telegram worker)
        self.telegram_queue = Queue(maxsize=200)  # Increased: 100 → 200

        # Legacy buffers (deprecated, will migrate gradually)
        self.original_frame_buffer = {}  # {track_id: [frames]} - DEPRECATED
        self.violation_frame_buffer = {}  # {track_id: [frames with violation]} - DEPRECATED
        self.buffer_lock = threading.Lock()

        # ALPR proactive cache
        self.alpr_proactive_cache = {}  # {track_id: plate_text}
        self.cache_lock = threading.Lock()

        # ========== THREADS ==========
        self.video_thread = None
        self.detection_thread = None
        self.display_thread = None  # Thread riêng cho display update
        self.alpr_proactive_thread = None
        self.alpr_realtime_thread = None
        self.best_frame_thread = None
        self.violation_thread = None
        self.telegram_thread = None

        logger.info("VideoProcessor initialized (8-thread architecture: 7 workers + 1 display)")

    def start(self, video_path):
        if self.is_running:
            self.stop()

        self.cap = cv2.VideoCapture(video_path)
        if not self.cap.isOpened():
            raise ValueError(f"Cannot open video: {video_path}")

        self.current_video = video_path
        self.frame_count = 0
        self.is_running = True
        self.is_paused = False

        # Reset tracker TRƯỚC để track_ids mới
        logger.info("Resetting tracker and speed calculator...")
        if hasattr(self.tracker, 'reset'):
            self.tracker.reset()
        if hasattr(self.processing_speed_calc, 'reset'):
            self.processing_speed_calc.reset()
        
        # Reset violation handler SAU khi tracker reset
        logger.info("Resetting violation handler...")
        self.violation_handler.reset()
        self.vehicle_collector.reset()
        self.plate_voter.reset()

        # Clear buffers and cache
        with self.buffer_lock:
            self.original_frame_buffer.clear()
            self.violation_frame_buffer.clear()
        with self.cache_lock:
            self.alpr_proactive_cache.clear()
        
        logger.info("All modules reset successfully")

        raw_fps = self.cap.get(cv2.CAP_PROP_FPS)
        self.total_frames = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        # OPTIMIZED: Use metadata FPS directly (no 3-second delay)
        logger.debug(f"FPS from metadata: {raw_fps}")

        if raw_fps and 5 <= raw_fps <= 120:
            self.fps = float(raw_fps)
            logger.info(f"Using metadata FPS: {self.fps:.2f}")
        else:
            self.fps = 30.0
            logger.warning(f"Invalid metadata FPS, using default: 30.0")

        # Round to 30fps if close (25-35 range)
        if 25 <= self.fps <= 35:
            self.fps = 30.0
            logger.debug("Rounded to 30fps for accurate playback")

        self.speed_calc.fps = self.fps
        self.processing_speed_calc.fps = self.fps
        self.processing_speed_calc.track_states.clear()

        logger.info(f"Started: {video_path}")
        logger.info(f"Resolution: {self.width}x{self.height}, FPS: {self.fps:.2f}")

        # Start all threads
        self.video_thread = threading.Thread(target=self._video_thread, daemon=True, name="VideoThread")
        self.video_thread.start()

        self.detection_thread = threading.Thread(target=self._detection_worker, daemon=True, name="DetectionWorker")
        self.detection_thread.start()

        # Display thread riêng để update mượt
        self.display_thread = threading.Thread(target=self._display_worker, daemon=True, name="DisplayWorker")
        self.display_thread.start()

        self.alpr_proactive_thread = threading.Thread(target=self._alpr_proactive_worker, daemon=True, name="ALPRProactive")
        self.alpr_proactive_thread.start()

        self.alpr_realtime_thread = threading.Thread(target=self._alpr_realtime_worker, daemon=True, name="ALPRRealtime")
        self.alpr_realtime_thread.start()

        self.best_frame_thread = threading.Thread(target=self._best_frame_selector_worker, daemon=True, name="BestFrameSelector")
        self.best_frame_thread.start()

        self.violation_thread = threading.Thread(target=self._violation_worker, daemon=True, name="ViolationWorker")
        self.violation_thread.start()

        self.telegram_thread = threading.Thread(target=self._telegram_worker, daemon=True, name="TelegramWorker")
        self.telegram_thread.start()

        logger.info("All threads started")

    def stop(self):
        self.is_running = False
        self.is_paused = False

        # Wait for all threads
        threads = [
            self.video_thread,
            self.detection_thread,
            self.display_thread,
            self.alpr_proactive_thread,
            self.alpr_realtime_thread,
            self.best_frame_thread,
            self.violation_thread,
            self.telegram_thread
        ]

        for thread in threads:
            if thread and thread.is_alive():
                thread.join(timeout=2.0)

        # Clear all queues
        self._clear_all_queues()
        
        # Reset violation handler khi stop để clear violated_tracks
        logger.info("Resetting violation handler on stop...")
        self.violation_handler.reset()

        # Cleanup track buffers
        logger.debug("Cleaning up track buffers...")
        self.track_buffer_manager.cleanup_all()

        if self.cap:
            self.cap.release()
            self.cap = None
        self.current_video = None
        logger.info("Stopped")

    def _clear_all_queues(self):
        queues = [
            self.detection_queue,
            self.stream_queue_clean,
            self.alpr_proactive_queue,
            self.alpr_realtime_queue,
            self.best_frame_queue,
            self.violation_queue,
            self.telegram_queue
        ]
        for q in queues:
            if isinstance(q, Queue):
                while not q.empty():
                    try:
                        q.get_nowait()
                    except:
                        break
            elif isinstance(q, deque):
                q.clear()

    def pause(self):
        self.is_paused = True

    def resume(self):
        self.is_paused = False

    def toggle_pause(self):
        self.is_paused = not self.is_paused
        return self.is_paused

    # ========== THREAD 1: VIDEO THREAD ==========
    def _video_thread(self):
        """Thread 1: Đọc frame từ video, push vào các queues - ĐỒNG BỘ ĐÚNG TỐC ĐỘ"""
        if self.fps <= 0:
            self.fps = 30.0
        
        frame_time = 1.0 / self.fps  # Thời gian mỗi frame (giây)
        frame_skip = max(1, int(self.fps / 30))  # Process every N frames for detection
        
        logger.debug(f"VIDEO-THREAD Starting: FPS={self.fps:.2f}, frame_time={frame_time:.4f}s, frame_skip={frame_skip}")
        logger.debug(f"Video duration: {self.total_frames / self.fps:.2f}s (if FPS correct)")

        # Đồng hồ để sync timing - QUAN TRỌNG: Phải sync chính xác
        frame_start_time = None  # Sẽ set sau khi đọc frame đầu tiên
        last_frame_time = None

        while self.is_running and self.cap and self.cap.isOpened():
            if self.is_paused:
                time.sleep(0.1)
                if frame_start_time is not None:
                    # Adjust start time khi resume để không bị nhảy
                    frame_start_time = time.time() - (self.frame_count * frame_time)
                continue

            # ĐỒNG BỘ: Tính thời gian frame hiện tại nên được đọc
            current_time = time.time()
            
            # Nếu đã đọc frame trước đó, đợi đúng thời gian
            if frame_start_time is not None and last_frame_time is not None:
                elapsed_since_last = current_time - last_frame_time
                if elapsed_since_last < frame_time:
                    sleep_needed = frame_time - elapsed_since_last
                    time.sleep(sleep_needed)
                    current_time = time.time()
            
            # Đọc frame
            ret, frame = self.cap.read()
            if not ret:
                # Nếu loop_video = True, reset video về đầu
                if self.loop_video:
                    logger.info("Video finished, looping back to start...")
                    self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    self.frame_count = 0
                    frame_start_time = None  # Reset timing
                    last_frame_time = None
                    # Reset tracker và violation handler khi loop
                    if hasattr(self.tracker, 'reset'):
                        self.tracker.reset()
                    if hasattr(self.processing_speed_calc, 'reset'):
                        self.processing_speed_calc.reset()
                    self.violation_handler.reset()
                    self.vehicle_collector.reset()
                    self.plate_voter.reset()
                    # Clear buffers
                    with self.buffer_lock:
                        self.original_frame_buffer.clear()
                        self.violation_frame_buffer.clear()
                    with self.cache_lock:
                        self.alpr_proactive_cache.clear()
                    # Clear track buffers
                    self.track_buffer_manager.cleanup_all()
                    logger.info("Video reset to start, continuing loop...")
                    continue  # Tiếp tục đọc frame từ đầu
                else:
                    logger.info("Video finished")
                    break

            # Get video timestamp (milliseconds from start)
            video_timestamp_ms = self.cap.get(cv2.CAP_PROP_POS_MSEC)

            # Set frame_start_time cho frame đầu tiên
            if frame_start_time is None:
                frame_start_time = current_time
                last_frame_time = current_time
                logger.debug(f"First frame read at: {frame_start_time:.4f}")

            self.frame_count += 1
            last_frame_time = current_time
            raw_frame = frame.copy()

            # Ưu tiên: Push to clean stream queue (for web display) - MỌI FRAME
            # Đảm bảo stream luôn có frames mới nhưng không quá đầy
            if self.stream_queue_clean.qsize() < 15:  # Tăng buffer lên 15 frames
                _, jpeg = cv2.imencode('.jpg', raw_frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
                try:
                    self.stream_queue_clean.put_nowait(jpeg.tobytes())
                except:
                    # Nếu queue đầy, xóa frame cũ nhất
                    try:
                        self.stream_queue_clean.get_nowait()
                        self.stream_queue_clean.put_nowait(jpeg.tobytes())
                    except:
                        pass

            # Push to detection queue (every N frames)
            if self.frame_count % frame_skip == 0:
                # Clear old frames nếu queue quá đầy
                while len(self.detection_queue) > 50:
                    try:
                        self.detection_queue.popleft()
                    except:
                        break
                
                try:
                    self.detection_queue.append({
                        'frame': raw_frame.copy(),
                        'frame_number': self.frame_count,
                        'timestamp': time.time(),
                        'video_timestamp_ms': video_timestamp_ms  # Video timestamp
                    })
                except:
                    pass

            # Push to proactive ALPR queue (every few frames, lower priority)
            if self.frame_count % (frame_skip * 2) == 0:
                if not self.alpr_proactive_queue.full():
                    try:
                        self.alpr_proactive_queue.put_nowait({
                        'frame': raw_frame.copy(),
                        'frame_number': self.frame_count
                    })
                    except:
                        pass

        self.is_running = False

    # ========== THREAD 2: DETECTION WORKER ==========
    def _detection_worker(self):
        """Thread 2: YOLO detection, tracking, speed calculation, violation detection"""
        while self.is_running:
            if self.is_paused:
                time.sleep(0.1)
                continue

            # Get frame from detection queue
            if not self.detection_queue:
                time.sleep(0.01)
                continue

            try:
                frame_data = self.detection_queue.popleft()
            except:
                continue

            if frame_data is None:
                continue

            raw_frame = frame_data['frame']
            frame_number = frame_data['frame_number']
            video_timestamp_ms = frame_data.get('video_timestamp_ms', frame_number * (1000.0 / self.fps))

            # YOLO Detection
            detections = self.detector.detect(raw_frame)

            # Tracking
            tracked = self.tracker.update(detections)

            # Process each tracked object
            violations_detected = []
            for det in tracked:
                track_id = det.get('track_id')
                if track_id is None:
                    continue

                bbox = det['bbox']

                # Speed calculation - REFACTORED: Use video timestamp
                speed, is_newly_calculated = self.processing_speed_calc.update(track_id, bbox, video_timestamp_ms)
                det['speed'] = speed
                
                # Khi tốc độ vừa được tính (xe vừa đi qua LINE2) → check violation NGAY
                if is_newly_calculated and speed is not None and speed > 0:
                    logger.debug(f"Track {track_id}: Speed JUST calculated = {speed:.1f} km/h → Triggering violation check")

                # Collect vehicle crops AND continuously detect plates for buffer
                if not self.vehicle_collector.is_finalized(track_id):
                    cy = (bbox[1] + bbox[3]) / 2

                    # Continue collecting crops in the middle zone
                    if self.speed_calc.line2_y <= cy <= self.speed_calc.line1_y:
                        # Collect for legacy system
                        self.vehicle_collector.add_vehicle_crop(track_id, raw_frame, bbox)

                        # OPTIMIZATION: Only run ASYNC ALPR in LOWER HALF of zone (near LINE1)
                        # Avoid processing when vehicle is far (near LINE2) where plate is small and blurry
                        zone_midpoint = (self.speed_calc.line1_y + self.speed_calc.line2_y) / 2

                        # Only queue ALPR if vehicle is in lower half (closer to LINE1)
                        if cy >= zone_midpoint:
                            # Vehicle is close to LINE1 → plate is larger and sharper
                            if not self.alpr_proactive_queue.full():
                                try:
                                    self.alpr_proactive_queue.put_nowait({
                                        'frame': raw_frame.copy(),
                                        'frame_number': frame_number,
                                        'track_id': track_id,
                                        'bbox': bbox,
                                        'for_buffer': True  # Flag to store in track buffer
                                    })
                                except:
                                    pass  # Skip if queue full

                    # Chụp ảnh biển số khi xe vừa xuất hiện từ dưới lên (ở LINE1)
                    # LINE1 là đường gần camera nhất → biển số lớn và rõ hơn → dễ nhận diện hơn
                    # Đây là thời điểm tốt nhất để chụp ảnh biển số
                    line1_threshold = 30  # pixels tolerance
                    if abs(cy - self.speed_calc.line1_y) < line1_threshold:
                        # Vehicle is AT or NEAR LINE1 → trigger ALPR (xe vừa xuất hiện từ dưới lên)
                        if track_id not in self.alpr_proactive_cache:
                            logger.debug(f"EARLY-ALPR: Track {track_id} at LINE1 (y={cy:.0f}) → Chụp ảnh biển số")
                            # Push to realtime ALPR queue for immediate processing
                            if not self.alpr_realtime_queue.full():
                                try:
                                    self.alpr_realtime_queue.put_nowait({
                                        'track_id': track_id,
                                        'speed': 0,  # No speed yet, just for plate detection
                                        'bbox': bbox,
                                        'frame_number': frame_number,
                                        'violation_frame_number': frame_number,
                                        'raw_frame': raw_frame.copy(),
                                        'detection': det.copy(),
                                        'early_detection': True  # Flag to indicate this is early detection
                                    })
                                    logger.debug(f"Queued Track {track_id} for early plate detection")
                                except:
                                    pass

                # Buffer frames for this track
                # Tăng buffer size từ 30 lên 150 frames để đủ cho video 3-5 giây (150 frames @ 30fps = 5 giây)
                with self.buffer_lock:
                    if track_id not in self.original_frame_buffer:
                        self.original_frame_buffer[track_id] = deque(maxlen=150)
                    self.original_frame_buffer[track_id].append({
                        'frame': raw_frame.copy(),
                        'frame_number': frame_number,
                        'bbox': bbox,
                        'detection': det.copy()
                    })

                # Check violation - FOR ALL VEHICLES (CARS, BUSES, TRUCKS, MOTORCYCLES)
                vehicle_class = det.get('class', 'unknown')

                # Xử lý tất cả loại xe (bao gồm cả xe máy)
                if vehicle_class in ['car', 'bus', 'truck', 'motorcycle']:
                    # Check violation NGAY khi tốc độ vừa được tính (xe vừa đi qua LINE2)
                    # Hoặc check lại nếu có tốc độ hợp lệ (cho trường hợp miss lần đầu)
                    if speed is not None and speed > 0:
                        # Ưu tiên: Nếu tốc độ vừa được tính → check ngay (logic thực tế)
                        # Fallback: Nếu có tốc độ nhưng chưa check → check lại (đảm bảo không miss)
                        should_check = is_newly_calculated or (speed > self.violation_handler.speed_limit and not det.get('violation_checked', False))
                        
                        if should_check:
                            # Truyền bbox vào check_violation để tránh duplicate
                            if self.violation_handler.check_violation(track_id, speed, bbox=bbox):
                                det['violation'] = True
                                det['violation_checked'] = True  # Đánh dấu đã check
                                
                                # Kiểm tra xem đã có kết quả ALPR từ EARLY-ALPR chưa
                                # EARLY-ALPR chụp ở LINE1 (xe gần camera, biển số rõ hơn)
                                # Nếu chưa có → vẫn lưu vi phạm (plate=NULL, manual review)
                                with self.cache_lock:
                                    has_cached_alpr = track_id in self.alpr_proactive_cache
                                
                                if has_cached_alpr:
                                    logger.info(f"Track {track_id}: Violation detected at {speed:.1f} km/h - ALPR result available from EARLY-ALPR")
                                else:
                                    logger.info(f"Track {track_id}: Violation detected at {speed:.1f} km/h - ALPR will run now")
                                
                                violations_detected.append({
                                    'track_id': track_id,
                                    'speed': speed,
                                    'bbox': bbox,
                                    'frame_number': frame_number,
                                    'violation_frame_number': frame_number,
                                    'raw_frame': raw_frame.copy(),
                                    'detection': det.copy()
                                })
                                logger.info(f"Track {track_id}: Violation queued (limit={self.violation_handler.speed_limit} km/h) - {'NEWLY CALCULATED' if is_newly_calculated else 'RE-CHECK'}")
                            elif speed > self.violation_handler.speed_limit:
                                # Log khi có vi phạm nhưng bị reject
                                det['violation_checked'] = True  # Đánh dấu đã check để không check lại
                                logger.debug(f"Track {track_id}: Speed {speed:.1f} km/h > {self.violation_handler.speed_limit} km/h but rejected (duplicate or already violated)")
                            else:
                                det['violation_checked'] = True  # Đánh dấu đã check (không vi phạm)
                # Không còn skip xe máy nữa

            # Push violations to ALPR realtime queue
            for violation in violations_detected:
                track_id = violation['track_id']
                speed = violation['speed']
                if not self.alpr_realtime_queue.full():
                    try:
                        self.alpr_realtime_queue.put_nowait(violation)
                        logger.info(f"Pushed Track {track_id} (speed={speed:.1f} km/h) to alpr_realtime_queue")
                    except Exception as e:
                        logger.error(f"Failed to push Track {track_id} to alpr_realtime_queue: {e}", exc_info=True)
                else:
                    logger.error(f"alpr_realtime_queue is FULL! Track {track_id} (speed={speed:.1f} km/h) NOT queued - VIOLATION LOST!")

            # Cleanup old tracks from buffer manager
            # Get active track IDs from current detections
            active_track_ids = [det.get('track_id') for det in tracked if det.get('track_id') is not None]
            self.track_buffer_manager.cleanup_old_tracks(active_track_ids)

            # Update display với bbox và detections
            # QUAN TRỌNG: Luôn update display, kể cả khi chưa có detections
            try:
                if tracked:
                    annotated = self._annotate_frame(raw_frame.copy(), tracked)
                else:
                    # Nếu chưa có detections, vẫn vẽ frame với lines
                    annotated = raw_frame.copy()
                    self.speed_calc.draw_lines(annotated)
                    # Thêm timestamp
                    timestamp = datetime.now().strftime("%H:%M:%S")
                    cv2.putText(annotated, timestamp, (10, 30),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
                    if self.is_paused:
                        cv2.putText(annotated, "PAUSED", (100, 30),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
                    else:
                        cv2.putText(annotated, "LIVE", (100, 30),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
                
                with self.display_lock:
                    self.annotated_frame = annotated
                    self.display_detections = tracked.copy() if tracked else []
            except Exception as e:
                logger.error(f"Error updating display: {e}", exc_info=True)

    # ========== DISPLAY WORKER ==========
    def _display_worker(self):
        """Thread riêng: Update display với detections từ detection worker"""
        # Thread này có thể dùng để xử lý display riêng nếu cần
        # Hiện tại display được update trực tiếp trong detection worker
        while self.is_running:
            if self.is_paused:
                time.sleep(0.1)
                continue
            time.sleep(0.1)

    # ========== THREAD 3: ALPR PROACTIVE WORKER ==========
    def _alpr_proactive_worker(self):
        """Thread 3: Background ALPR detection, cache results"""
        while self.is_running:
            if self.is_paused:
                time.sleep(0.1)
                continue

            try:
                frame_data = self.alpr_proactive_queue.get(timeout=0.5)
            except:
                continue

            if frame_data is None:
                continue

            frame = frame_data['frame']
            frame_number = frame_data['frame_number']
            for_buffer = frame_data.get('for_buffer', False)
            track_id = frame_data.get('track_id')
            bbox = frame_data.get('bbox')

            # Crop vehicle region if bbox provided
            if bbox and for_buffer:
                x1, y1, x2, y2 = map(int, bbox)
                fh, fw = frame.shape[:2]
                pad = 30
                x1 = max(0, x1 - pad)
                y1 = max(0, y1 - pad)
                x2 = min(fw, x2 + pad)
                y2 = min(fh, y2 + pad)
                vehicle_crop = frame[y1:y2, x1:x2]
            else:
                vehicle_crop = frame

            # Try to detect plates in background
            try:
                result = self.alpr.read_plate(vehicle_crop, None)
                if result and result.get('plate_text'):
                    plate_text = result['plate_text']
                    confidence = result.get('confidence', 0.0)

                    # If this is for track buffer, store it
                    if for_buffer and track_id and bbox is not None:
                        # Calculate sharpness
                        gray = cv2.cvtColor(vehicle_crop, cv2.COLOR_BGR2GRAY)
                        sharpness = cv2.Laplacian(gray, cv2.CV_64F).var()

                        plate_result = {
                            'text': plate_text,
                            'confidence': confidence,
                            'sharpness': sharpness
                        }

                        # Get plate crop if available
                        plate_crop = result.get('plate_crop', vehicle_crop)

                        # Store in buffer (NON-BLOCKING!)
                        try:
                            # Pass frame_number to track_buffer
                            self.track_buffer_manager.add_frame(
                                track_id=track_id,
                                full_frame=frame,
                                bbox=bbox,
                                plate_crop=plate_crop,
                                plate_result=plate_result,
                                frame_number=frame_number  # Add frame_number for tracking
                            )
                            logger.debug(f"Track {track_id}: Added '{plate_text}' (conf={confidence:.2f}, sharp={sharpness:.0f})")
                        except Exception as e:
                            logger.error(f"Track {track_id}: Failed to add - {e}", exc_info=True)

                    # ONLY cache for the specific track_id that the plate was detected from
                    # DO NOT cache for multiple tracks - this causes plate/vehicle mismatch!
                    # The old code cached same plate for "last 3 tracks" which was WRONG.
                    if confidence >= 0.3 and track_id is not None:
                        with self.cache_lock:
                            # Only cache if we have a specific track_id AND this track doesn't have cache yet
                            if track_id not in self.alpr_proactive_cache:
                                self.alpr_proactive_cache[track_id] = {
                                    'plate_text': plate_text,
                                    'confidence': confidence,
                                    'frame_number': frame_number
                                }
                                logger.debug(f"Cached plate '{plate_text}' for Track {track_id} (conf={confidence:.2f})")
            except Exception as e:
                pass

    # ========== THREAD 4: ALPR REALTIME WORKER ==========
    def _alpr_realtime_worker(self):
        """Thread 4: ALPR when violation detected"""
        while self.is_running:
            if self.is_paused:
                time.sleep(0.1)
                continue

            try:
                violation_data = self.alpr_realtime_queue.get(timeout=0.5)
            except:
                continue

            if violation_data is None:
                continue

            track_id = violation_data['track_id']
            raw_frame = violation_data['raw_frame']
            bbox = violation_data['bbox']
            frame_number = violation_data['frame_number']
            is_early_detection = violation_data.get('early_detection', False)

            if is_early_detection:
                logger.debug(f"EARLY-ALPR: Track {track_id}: Early plate detection at LINE2")
            else:
                logger.info(f"ALPR-REALTIME: Track {track_id}: Violation detected")

            # Check cache first - if we have cached data from early detection, USE IT!
            cached_data = None
            cached_plate = None  # Initialize cached_plate to avoid UnboundLocalError
            with self.cache_lock:
                cached_data = self.alpr_proactive_cache.get(track_id)

            # If we have cached plate data from early detection AND this is a violation, USE IT DIRECTLY
            if cached_data and not is_early_detection:
                cached_plate = cached_data.get('plate_text')
                cached_plate_img = cached_data.get('plate_image')
                cached_vehicle_img = cached_data.get('vehicle_image')

                # If cache has complete data (text + image), use it directly
                if cached_plate and cached_plate_img is not None:
                    logger.debug(f"Using COMPLETE CACHED data from early detection: '{cached_plate}' (Cached at LINE2, using for violation at LINE1)")

                    # Push directly to best_frame_queue with cached data
                    try:
                        if not self.best_frame_queue.full():
                            self.best_frame_queue.put_nowait({
                                'track_id': track_id,
                                'plate_text': cached_plate,
                                'plate_image': cached_plate_img,
                                'vehicle_image': cached_vehicle_img,
                                'confidence': cached_data.get('confidence', 0.5),
                                'validation_state': cached_data.get('validation_state'),
                                'sharpness': cached_data.get('sharpness', 0.0),
                                'violation_data': violation_data
                            })
                            logger.info(f"Pushed CACHED data to best_frame_queue for Track {track_id}")
                            continue  # Skip OCR processing, we already have the result
                        else:
                            logger.error(f"best_frame_queue is FULL! Track {track_id} CACHED data NOT queued!")
                    except Exception as e:
                        logger.error(f"Failed to push cached data for Track {track_id}: {e}", exc_info=True)
                        import traceback
                        traceback.print_exc()
                        # Fall through to normal OCR processing
                else:
                    logger.debug("Cache incomplete (text only), will re-run OCR")

            ocr_results = []
            plate_images = []

            # PRIORITY 1: Try to get from track buffer first (NEW SYSTEM!)
            track_buffer = self.track_buffer_manager.get_buffer(track_id)
            if track_buffer:
                # Get all ALPR results from buffer
                buffer_results = track_buffer.get_all_plate_results()
                best_plate_info = track_buffer.get_best_plate_info()
                best_plate_crop = track_buffer.get_best_plate_crop()
                best_full_frame, _ = track_buffer.get_best_full_frame()

                if buffer_results and best_plate_crop is not None:
                    logger.debug(f"Using {len(buffer_results)} results from track buffer")

                    # Use buffer results
                    for result in buffer_results:
                        if result.get('text'):
                            # Create OCR result format with frame tracking
                            ocr_results.append({
                                'plate_text': result['text'],
                                'confidence': result.get('confidence', 0.0),
                                'frame_id': result.get('frame_number'),                                 'frame_type': result.get('frame_type', 'buffer')                             })

                    # Add best plate image with frame tracking
                    if best_plate_info['text']:
                        # Find the frame_id from buffer_results that matches best_plate_info
                        best_frame_id = None
                        best_frame_type = 'buffer'
                        for result in buffer_results:
                            if result.get('text') == best_plate_info['text']:
                                best_frame_id = result.get('frame_number')
                                best_frame_type = result.get('frame_type', 'buffer')
                                break
                        
                        plate_images.append({
                            'plate_text': best_plate_info['text'],
                            'plate_image': best_plate_crop,  # Use stored plate crop!
                            'vehicle_image': best_full_frame if best_full_frame is not None else raw_frame,
                            'quality': best_plate_info['sharpness'],
                            'frame_id': best_frame_id,                             'frame_type': best_frame_type                         })
                        logger.debug(f"Buffer best: '{best_plate_info['text']}' (sharp={best_plate_info['sharpness']:.0f}, conf={best_plate_info['confidence']:.2f}, plate_img=YES, frame_id={best_frame_id})")
                else:
                    logger.warning("Track buffer exists but no valid results")

            # FALLBACK: Use legacy vehicle_collector if track buffer empty
            if not ocr_results:
                logger.debug("Fallback to vehicle_collector")
                best_crops = self.vehicle_collector.get_best_crops(track_id, top_n=5)
                logger.debug(f"Collected {len(best_crops)} vehicle crops")

                if not best_crops:
                    self.vehicle_collector.add_vehicle_crop(track_id, raw_frame, bbox)
                    best_crops = self.vehicle_collector.get_best_crops(track_id, top_n=5)

                # OCR on best crops - CHỈ thêm nếu có plate_image (không đoán biển số)
                for i, crop_data in enumerate(best_crops):
                    vehicle_crop = crop_data['vehicle_crop']
                    sharpness = crop_data.get('sharpness', crop_data.get('metadata', {}).get('sharpness', 0))
                    # Get frame_number from metadata
                    frame_id = crop_data.get('metadata', {}).get('frame_number')
                    frame_type = 'buffer' if frame_id is not None else 'legacy'

                    result = self.alpr.read_plate(vehicle_crop, None)

                    # QUAN TRỌNG: Chỉ thêm vào OCR results nếu có CẢ plate_text VÀ plate_image
                    # Không có ảnh biển số = không có bằng chứng → không đoán biển số
                    if result and result.get('plate_text') and result.get('plate_image') is not None:
                        # Add frame_id to result
                        result_with_frame = result.copy()
                        if frame_id is not None:
                            result_with_frame['frame_id'] = frame_id
                            result_with_frame['frame_type'] = frame_type
                        ocr_results.append(result_with_frame)
                        plate_images.append({
                            'plate_text': result.get('plate_text'),
                            'plate_image': result.get('plate_image'),
                            'vehicle_image': vehicle_crop.copy(),
                            'quality': sharpness,
                            'frame_id': frame_id,                             'frame_type': frame_type                         })
                        logger.debug(f"Crop {i+1}: '{result['plate_text']}' (sharp={sharpness:.0f}, conf={result.get('confidence', 0):.2f}, plate_img=YES, frame_id={frame_id})")
                    elif result and result.get('plate_text'):
                        # Log nhưng không thêm vào kết quả nếu không có plate_image
                        logger.debug(f"Crop {i+1}: '{result['plate_text']}' - SKIP: No plate_image (no evidence to determine plate)")

            # Try direct OCR if no results - CHỈ thêm nếu có plate_image
            if not ocr_results:
                # Get frame_number from violation_data
                frame_number = violation_data.get('frame_number')
                direct_result = self.alpr.read_plate(raw_frame, bbox)
                # QUAN TRỌNG: Chỉ thêm nếu có CẢ plate_text VÀ plate_image
                if direct_result and direct_result.get('plate_text') and direct_result.get('plate_image') is not None:
                    # Add frame_id to result
                    direct_result_with_frame = direct_result.copy()
                    if frame_number is not None:
                        direct_result_with_frame['frame_id'] = frame_number
                        direct_result_with_frame['frame_type'] = 'direct'
                    ocr_results.append(direct_result_with_frame)
                    # Crop vehicle từ bbox
                    vehicle_crop_direct = None
                    if bbox is not None:
                        x1, y1, x2, y2 = map(int, bbox)
                        h, w = raw_frame.shape[:2]
                        pad = 20
                        x1, y1 = max(0, x1 - pad), max(0, y1 - pad)
                        x2, y2 = min(w, x2 + pad), min(h, y2 + pad)
                        vehicle_crop_direct = raw_frame[y1:y2, x1:x2].copy()
                    else:
                        vehicle_crop_direct = raw_frame.copy()
                    
                    plate_images.append({
                        'plate_text': direct_result.get('plate_text'),
                        'plate_image': direct_result.get('plate_image'),
                        'vehicle_image': vehicle_crop_direct,
                        'quality': 100,
                        'frame_id': frame_number,                         'frame_type': 'direct' if frame_number is not None else 'unknown'                     })
                    logger.debug(f"Direct: '{direct_result['plate_text']}' (plate_img=YES, frame_id={frame_number})")
                elif direct_result and direct_result.get('plate_text'):
                    logger.debug(f"Direct: '{direct_result['plate_text']}' - SKIP: No plate_image (no evidence)")

            # KHÔNG sử dụng cached plate nếu không có plate_image
            # Cached plate chỉ là text, không có ảnh biển số → không có bằng chứng → không thể xác định biển số
            if not ocr_results and cached_plate:
                logger.warning(f"Cached plate '{cached_plate}' available but NO plate_image → Cannot use cached plate without evidence")

            # Vote on OCR results
            vote_result = self.plate_voter.vote(track_id, ocr_results, plate_images)

            # DO NOT skip violations when plate recognition fails!
            # Violations must ALWAYS be saved, even without plate.
            # A violation with NULL plate can be manually reviewed later.

            if vote_result is None:
                # No valid plate found - STILL save violation with plate_text=None
                logger.warning(f"{'EARLY-ALPR' if is_early_detection else 'ALPR-REALTIME'}: No valid VN plate → Trying to detect plate region...")
                final_plate = None
                plate_img = None
                vehicle_img = None
                confidence = 0.0
                sharpness = 0.0
                validation_state = None
                
                # DÙNG PLATE DETECTOR ĐỂ TÌM VÙNG BIỂN SỐ CHÍNH XÁC
                if bbox is not None and raw_frame is not None:
                    try:
                        # Thử detect plate region bằng FastALPR (không cần OCR thành công)
                        detect_result = self.alpr.detect_plate_only(raw_frame, bbox)
                        
                        if detect_result is not None:
                            plate_img = detect_result.get('plate_image')
                            # Nếu detect được OCR text hợp lệ, dùng luôn
                            if detect_result.get('ocr_text'):
                                final_plate = detect_result['ocr_text']
                                confidence = detect_result.get('ocr_confidence', 0.0)
                            logger.debug(f"{'EARLY-ALPR' if is_early_detection else 'ALPR-REALTIME'}: Plate region detected by detector (text='{final_plate or 'N/A'}')")
                        
                        # FALLBACK - crop theo loại xe nếu detector fail
                        if plate_img is None:
                            vx1, vy1, vx2, vy2 = map(int, bbox)
                            vh = vy2 - vy1
                            vw = vx2 - vx1
                            fh, fw = raw_frame.shape[:2]
                            
                            # Crop theo loại xe
                            if vehicle_class == 'motorcycle':
                                # Xe máy: biển số nhỏ, ở phần dưới-giữa
                                plate_y1 = vy1 + int(vh * 0.70)
                                plate_y2 = min(vy2, fh)
                                plate_x1 = max(0, vx1 + int(vw * 0.20))
                                plate_x2 = min(fw, vx2 - int(vw * 0.20))
                            elif vehicle_class == 'bus':
                                # Xe bus: biển số ở phần dưới-giữa
                                plate_y1 = vy1 + int(vh * 0.75)
                                plate_y2 = min(vy2 + 5, fh)
                                plate_x1 = max(0, vx1 + int(vw * 0.25))
                                plate_x2 = min(fw, vx2 - int(vw * 0.25))
                            else:
                                # Ô tô thường
                                plate_y1 = vy1 + int(vh * 0.60)
                                plate_y2 = min(vy2 + 10, fh)
                                plate_x1 = max(0, vx1 + int(vw * 0.15))
                                plate_x2 = min(fw, vx2 - int(vw * 0.15))
                            
                            if plate_x2 > plate_x1 + 30 and plate_y2 > plate_y1 + 15:
                                plate_img = raw_frame[plate_y1:plate_y2, plate_x1:plate_x2].copy()
                                logger.warning(f"{'EARLY-ALPR' if is_early_detection else 'ALPR-REALTIME'}: Using fallback crop for {vehicle_class}: {plate_x2-plate_x1}x{plate_y2-plate_y1}")
                        
                        # Crop vehicle image
                        vx1, vy1, vx2, vy2 = map(int, bbox)
                        fh, fw = raw_frame.shape[:2]
                        vehicle_img = raw_frame[max(0,vy1):min(fh,vy2), max(0,vx1):min(fw,vx2)].copy()
                    except Exception as e:
                        logger.error(f"{'EARLY-ALPR' if is_early_detection else 'ALPR-REALTIME'}: Error detecting/cropping plate: {e}", exc_info=True)
            else:
                final_plate = vote_result['plate_text']
                plate_img = vote_result.get('plate_image')
                vehicle_img = vote_result.get('vehicle_image')
                confidence = vote_result.get('confidence', 0.0)
                sharpness = vote_result.get('sharpness', 0.0)
                validation_state = vote_result.get('validation_state')
                # Get frame_id from vote_result
                plate_frame_id = vote_result.get('frame_id')
                plate_frame_type = vote_result.get('frame_type', 'unknown')

            # Log the result (plate found or not)
            # Check plate_img properly (numpy array)
            plate_img_status = 'NO'
            if plate_img is not None:
                if hasattr(plate_img, 'size') and plate_img.size > 0:
                    plate_img_status = 'YES'
                elif not hasattr(plate_img, 'size'):
                    plate_img_status = 'YES'  # Not numpy array but exists
            
            vehicle_img_status = 'YES' if vehicle_img is not None else 'NO'
            
            if final_plate:
                logger.debug(f"{'EARLY-ALPR' if is_early_detection else 'ALPR-REALTIME'}: FINAL: {final_plate} (plate_img={plate_img_status}, vehicle_img={vehicle_img_status})")
            else:
                logger.info(f"{'EARLY-ALPR' if is_early_detection else 'ALPR-REALTIME'}: FINAL: plate=NULL → Manual review required")

            # If this is early detection, CACHE the result and DON'T push to violation queue
            if is_early_detection:
                with self.cache_lock:
                    self.alpr_proactive_cache[track_id] = {
                        'plate_text': final_plate,
                        'plate_image': plate_img,
                        'vehicle_image': vehicle_img,
                        'confidence': confidence,
                        'validation_state': validation_state,
                        'sharpness': sharpness,
                        'frame_number': frame_number
                    }
                logger.debug(f"CACHED plate '{final_plate}' for Track {track_id} (will use when violation detected)")
                continue  # Don't push to best_frame_queue yet

            # Push to best frame queue - ALWAYS push, even without plate
            # Violations must ALWAYS be saved, plate recognition is secondary
            try:
                if not self.best_frame_queue.full():
                    self.best_frame_queue.put_nowait({
                        'track_id': track_id,
                        'plate_text': final_plate,  # Can be None - that's OK!
                        'plate_image': plate_img,   # Can be None - manual review will handle
                        'vehicle_image': vehicle_img,
                        'confidence': confidence,
                        'validation_state': validation_state,
                        'sharpness': sharpness,
                        'violation_data': violation_data,
                        'manual_review_required': final_plate is None,  # Flag for manual review
                        # Pass frame_id from vote_result
                        'frame_id': plate_frame_id,
                        'frame_type': plate_frame_type
                    })
                    logger.info(f"Pushed to best_frame_queue for Track {track_id} (plate={'NULL' if final_plate is None else final_plate})")
                else:
                    logger.error(f"best_frame_queue is FULL! Track {track_id} NOT queued - VIOLATION LOST!")
            except Exception as e:
                logger.error(f"Failed to push Track {track_id} to best_frame_queue: {e}", exc_info=True)
                import traceback
                traceback.print_exc()

    # ========== THREAD 5: BEST FRAME SELECTOR WORKER ==========
    def _best_frame_selector_worker(self):
        """Thread 5: Select best frame from violation buffer"""
        while self.is_running:
            if self.is_paused:
                time.sleep(0.1)
                continue

            try:
                frame_data = self.best_frame_queue.get(timeout=0.5)
            except:
                continue

            if frame_data is None:
                continue

            track_id = frame_data['track_id']
            violation_data = frame_data['violation_data']
            plate_text = frame_data['plate_text']
            plate_image = frame_data.get('plate_image')
            vehicle_image_from_alpr = frame_data.get('vehicle_image')
            # Get frame_id from frame_data
            vehicle_frame_id = frame_data.get('frame_id')
            vehicle_frame_type = frame_data.get('frame_type', 'unknown')

            logger.debug(f"BEST-FRAME: Processing Track {track_id}: {plate_text}")

            # Get best frame from track buffer (NEW SYSTEM)
            best_frame = None
            best_detection = None
            plate_image_from_buffer = None
            best_frame_bbox = None  # Store bbox from best frame

            track_buffer = self.track_buffer_manager.get_buffer(track_id)
            if track_buffer:
                # Get best full frame from buffer
                best_frame, best_frame_bbox = track_buffer.get_best_full_frame()
                if best_frame is not None:
                    logger.debug(f"Using best frame from track buffer (score: {track_buffer.best_score:.4f})")
                    # Get best plate crop
                    plate_image_from_buffer = track_buffer.get_best_plate_crop()
                    # Create detection dict
                    best_detection = violation_data.get('detection')

            # Fallback: Get from legacy buffer
            if best_frame is None:
                with self.buffer_lock:
                    if track_id in self.original_frame_buffer:
                        frames = list(self.original_frame_buffer[track_id])
                        if frames:
                            # Select frame closest to violation time
                            violation_frame_num = violation_data['frame_number']
                            best_frame_data = min(frames, key=lambda x: abs(x['frame_number'] - violation_frame_num))
                            best_frame = best_frame_data['frame']
                            best_detection = best_frame_data['detection']

            # If still no frame, use violation frame
            if best_frame is None:
                best_frame = violation_data.get('raw_frame')
                best_detection = violation_data.get('detection')

            # plate_image từ vote_result đã được chọn từ best frame
            # KHÔNG được override nếu đã có plate_image hợp lệ từ vote_result!
            # Strategy 0 chỉ re-detect nếu plate_image từ vote_result là None hoặc không hợp lệ
            
            # Use plate image from vote_result first (đã được vote từ best frame)
            plate_image_from_vote = plate_image  # From frame_data (vote_result)
            plate_image_has_frame_id = frame_data.get('frame_id') is not None
            
            # Use plate image from buffer if vote_result doesn't have one
            if plate_image_from_vote is None and plate_image_from_buffer is not None:
                logger.debug(f"Using high-quality plate crop from buffer (vote_result has no plate_image)")
                plate_image = plate_image_from_buffer
            elif plate_image_from_vote is not None:
                # KEEP plate_image from vote_result - it's from the best frame with highest confidence
                plate_image = plate_image_from_vote
                logger.debug(f"KEEPING plate_image from vote_result (frame_id={frame_data.get('frame_id')}, confidence={frame_data.get('confidence', 0):.2f})")
                logger.debug(f"This plate_image matches plate_text='{plate_text}' from the SAME frame")

            # Add violation timestamp
            violation_timestamp = datetime.now()

            # Ensure plate_image and vehicle_image are from the SAME frame
            # Strategy 0: ONLY re-detect if plate_image is None or invalid
            violation_frame = violation_data.get('raw_frame')
            violation_bbox = violation_data.get('bbox')
            
            final_vehicle_image = None
            
            # Strategy 0.5: If plate_image from vote_result exists, use vehicle_image from same source
            if plate_image_from_vote is not None and vehicle_image_from_alpr is not None:
                # Use vehicle_image from vote_result (same frame as plate_image)
                final_vehicle_image = vehicle_image_from_alpr
                logger.debug(f"MATCHED: plate_image and vehicle_image from vote_result (SAME FRAME, confidence={frame_data.get('confidence', 0):.2f})")
            
            # Strategy 0: ONLY re-detect nếu plate_image từ vote_result là None hoặc không hợp lệ
            # KHÔNG override plate_image từ vote_result nếu nó đã có và hợp lệ!
            elif plate_image is None and violation_frame is not None and violation_bbox is not None:
                try:
                    # Re-detect plate_image từ violation_frame CHỈ KHI vote_result không có
                    detect_result = self.alpr.detect_plate_only(violation_frame, violation_bbox)
                    if detect_result and detect_result.get('plate_image') is not None:
                        # Sử dụng plate_image từ violation_frame (fallback only)
                        plate_image = detect_result.get('plate_image')
                        logger.debug(f"FALLBACK: Re-detected plate_image from violation_frame (vote_result had no plate_image)")
                        
                        # Crop vehicle_image từ CÙNG violation_frame
                        x1, y1, x2, y2 = map(int, violation_bbox)
                        h, w = violation_frame.shape[:2]
                        pad = 20
                        x1, y1 = max(0, x1 - pad), max(0, y1 - pad)
                        x2, y2 = min(w, x2 + pad), min(h, y2 + pad)
                        final_vehicle_image = violation_frame[y1:y2, x1:x2].copy()
                        logger.debug(f"MATCHED: Both plate_image and vehicle_image from violation_frame (PRIORITY)")
                    else:
                        # Nếu không detect được, vẫn crop vehicle_image từ violation_frame
                        x1, y1, x2, y2 = map(int, violation_bbox)
                        h, w = violation_frame.shape[:2]
                        pad = 20
                        x1, y1 = max(0, x1 - pad), max(0, y1 - pad)
                        x2, y2 = min(w, x2 + pad), min(h, y2 + pad)
                        final_vehicle_image = violation_frame[y1:y2, x1:x2].copy()
                        logger.debug(f"MATCHED: vehicle_image from violation_frame (plate_image from other source)")
                except Exception as e:
                    logger.error(f"Error re-detecting from violation_frame: {e}", exc_info=True)
                    # Fall through to other strategies
            
            # Strategy 1: If we have plate_image from buffer, use best_frame for vehicle_image
            if final_vehicle_image is None and plate_image_from_buffer is not None and best_frame is not None:
                # Plate and vehicle MUST be from the same best_frame
                bbox_to_use = best_frame_bbox if best_frame_bbox is not None else violation_data.get('bbox')
                if bbox_to_use is not None:
                    x1, y1, x2, y2 = map(int, bbox_to_use)
                    h, w = best_frame.shape[:2]
                    pad = 20
                    x1 = max(0, x1 - pad)
                    y1 = max(0, y1 - pad)
                    x2 = min(w, x2 + pad)
                    y2 = min(h, y2 + pad)
                    final_vehicle_image = best_frame[y1:y2, x1:x2].copy()
                    logger.debug(f"MATCHED: plate_image from buffer + vehicle_image from same best_frame (bbox from buffer)")
                else:
                    final_vehicle_image = best_frame
                    logger.debug(f"MATCHED: plate_image from buffer + vehicle_image = full best_frame")
            
            # Strategy 2: Already handled in Strategy 0.5 above
            # (plate_image from vote_result + vehicle_image_from_alpr)
            
            # Strategy 3: Fallback - use best_frame for both if available
            if final_vehicle_image is None and best_frame is not None:
                bbox_to_use = best_frame_bbox if best_frame_bbox is not None else violation_data.get('bbox')
                if bbox_to_use is not None:
                    x1, y1, x2, y2 = map(int, bbox_to_use)
                    h, w = best_frame.shape[:2]
                    pad = 20
                    x1 = max(0, x1 - pad)
                    y1 = max(0, y1 - pad)
                    x2 = min(w, x2 + pad)
                    y2 = min(h, y2 + pad)
                    final_vehicle_image = best_frame[y1:y2, x1:x2].copy()
                    logger.debug(f"MATCHED: Both images from best_frame (fallback)")
                else:
                    final_vehicle_image = best_frame
                    logger.debug(f"MATCHED: Both images from best_frame (full frame fallback)")
            
            # Strategy 4: Last resort - use violation frame (should not reach here if Strategy 0 worked)
            if final_vehicle_image is None:
                violation_frame_fallback = violation_data.get('raw_frame')
                if violation_frame_fallback is not None:
                    bbox_to_use = violation_data.get('bbox')
                    bbox_fallback = violation_data.get('bbox')
                    if bbox_fallback is not None:
                        x1, y1, x2, y2 = map(int, bbox_fallback)
                        h, w = violation_frame_fallback.shape[:2]
                        pad = 20
                        x1 = max(0, x1 - pad)
                        y1 = max(0, y1 - pad)
                        x2 = min(w, x2 + pad)
                        y2 = min(h, y2 + pad)
                        final_vehicle_image = violation_frame_fallback[y1:y2, x1:x2].copy()
                        logger.debug(f"FALLBACK: Using violation_frame for vehicle_image")
                    else:
                        final_vehicle_image = violation_frame_fallback
                        logger.debug(f"FALLBACK: Using full violation_frame for vehicle_image")

            # Push to violation queue (include validation state)
            try:
                speed = violation_data['speed']
                if not self.violation_queue.full():
                    self.violation_queue.put_nowait({
                        'track_id': track_id,
                        'speed': speed,
                        'bbox': violation_data.get('bbox'),
                        'vehicle_class': best_detection.get('class', 'unknown') if best_detection else 'unknown',
                        'plate_text': plate_text,
                        'plate_image': plate_image,
                        'vehicle_image': final_vehicle_image,
                        'confidence': frame_data.get('confidence', 0.5),
                        'validation_state': frame_data.get('validation_state'),
                        'sharpness': frame_data.get('sharpness', 0.0),
                        'violation_timestamp': violation_timestamp,
                        'violation_frame': best_frame,
                        # Pass violation_frame_number để tạo video
                        'violation_frame_number': violation_data.get('violation_frame_number'),
                        # Pass frame_id for validation
                        'plate_frame_id': frame_data.get('frame_id'),
                        'vehicle_frame_id': vehicle_frame_id,
                        'plate_frame_type': frame_data.get('frame_type', 'unknown'),
                        'vehicle_frame_type': vehicle_frame_type
                    })
                    logger.info(f"Pushed Track {track_id} to violation_queue (speed={speed:.1f} km/h, plate_img={'YES' if plate_image is not None else 'NO'})")
                else:
                    logger.error(f"violation_queue is FULL! Track {track_id} NOT queued - VIOLATION LOST!")
            except Exception as e:
                logger.error(f"Failed to push Track {track_id} to violation_queue: {e}", exc_info=True)
                import traceback
                traceback.print_exc()

    # ========== THREAD 6: VIOLATION WORKER ==========
    def _violation_worker(self):
        """Thread 6: Save to DB, save images, create videos"""
        while self.is_running:
            if self.is_paused:
                time.sleep(0.1)
                continue

            try:
                violation_data = self.violation_queue.get(timeout=0.5)
            except:
                continue

            if violation_data is None:
                continue

            track_id = violation_data.get('track_id')
            speed = violation_data.get('speed')
            bbox = violation_data.get('bbox')
            vehicle_class = violation_data.get('vehicle_class', 'unknown')
            plate_text = violation_data.get('plate_text')  # Can be None - that's OK!
            plate_image = violation_data.get('plate_image')  # Can be None - manual review
            vehicle_image = violation_data.get('vehicle_image')
            confidence = violation_data.get('confidence', 0.0)
            violation_frame = violation_data.get('violation_frame')
            violation_frame_number = violation_data.get('violation_frame_number')

            # Only require track_id and speed
            # plate_text can be None - violation still needs to be saved!
            if not track_id or not speed:
                logger.warning("Missing track_id or speed, skipping...")
                continue

            # Lưu vi phạm cho tất cả loại xe (bao gồm cả xe máy)
            if vehicle_class not in ['car', 'bus', 'truck', 'motorcycle']:
                logger.warning(f"SKIP: Track {track_id} is '{vehicle_class}' (unknown vehicle type)")
                continue

            # DO NOT skip when plate_image is None!
            # Violations must ALWAYS be saved, even without plate evidence.
            # "Biển số mờ" = manual review required
            # If we detect plate_image from violation_frame, 
            # we MUST also update vehicle_image from the SAME frame to ensure they match!
            plate_image_was_detected = False
            if plate_image is None:
                logger.warning(f"Track {track_id}: NO plate_image → Trying to detect plate region...")
                
                # DÙNG PLATE DETECTOR ĐỂ TÌM VÙNG BIỂN SỐ CHÍNH XÁC
                if violation_frame is not None and bbox is not None:
                    try:
                        # Thử detect plate region bằng FastALPR
                        detect_result = self.alpr.detect_plate_only(violation_frame, bbox)
                        
                        if detect_result is not None:
                            plate_image = detect_result.get('plate_image')
                            plate_image_was_detected = True
                            # Nếu detect được OCR text hợp lệ, dùng luôn
                            if detect_result.get('ocr_text') and not plate_text:
                                plate_text = detect_result['ocr_text']
                                confidence = detect_result.get('ocr_confidence', 0.0)
                            logger.debug(f"Plate region detected from violation_frame (text='{plate_text or 'N/A'}')")
                        
                        # FALLBACK - crop theo loại xe nếu detector fail
                        if plate_image is None:
                            vx1, vy1, vx2, vy2 = map(int, bbox)
                            vh = vy2 - vy1
                            vw = vx2 - vx1
                            fh, fw = violation_frame.shape[:2]
                            
                            # Crop theo loại xe
                            if vehicle_class == 'motorcycle':
                                plate_y1 = vy1 + int(vh * 0.70)
                                plate_y2 = min(vy2, fh)
                                plate_x1 = max(0, vx1 + int(vw * 0.20))
                                plate_x2 = min(fw, vx2 - int(vw * 0.20))
                            elif vehicle_class == 'bus':
                                plate_y1 = vy1 + int(vh * 0.75)
                                plate_y2 = min(vy2 + 5, fh)
                                plate_x1 = max(0, vx1 + int(vw * 0.25))
                                plate_x2 = min(fw, vx2 - int(vw * 0.25))
                            else:
                                plate_y1 = vy1 + int(vh * 0.60)
                                plate_y2 = min(vy2 + 10, fh)
                                plate_x1 = max(0, vx1 + int(vw * 0.15))
                                plate_x2 = min(fw, vx2 - int(vw * 0.15))
                            
                            if plate_x2 > plate_x1 + 30 and plate_y2 > plate_y1 + 15:
                                plate_image = violation_frame[plate_y1:plate_y2, plate_x1:plate_x2].copy()
                                plate_image_was_detected = True
                                logger.warning(f"Using fallback crop for {vehicle_class}: {plate_x2-plate_x1}x{plate_y2-plate_y1}")
                    except Exception as e:
                        logger.error(f"Error detecting/cropping plate: {e}", exc_info=True)
                
                if plate_image is None:
                    logger.warning(f"Track {track_id}: Still NO plate_image → Saving with plate='Biển số mờ'")
                
                # Plate text = "Biển số mờ" khi không đọc được
                if not plate_text:
                    plate_text = None  # ViolationHandler sẽ xử lý thành "Biển số mờ"
            
            # If plate_image was just detected from violation_frame,
            # we MUST ensure vehicle_image is also from the SAME violation_frame!
            if plate_image_was_detected and violation_frame is not None:
                # Re-crop vehicle_image from the SAME violation_frame to ensure they match
                if bbox is not None:
                    x1, y1, x2, y2 = map(int, bbox)
                    h, w = violation_frame.shape[:2]
                    pad = 20
                    x1 = max(0, x1 - pad)
                    y1 = max(0, y1 - pad)
                    x2 = min(w, x2 + pad)
                    y2 = min(h, y2 + pad)
                    vehicle_image = violation_frame[y1:y2, x1:x2].copy()
                    logger.debug(f"MATCHED: Re-cropped vehicle_image from SAME violation_frame as plate_image")
                else:
                    vehicle_image = violation_frame
                    logger.debug(f"MATCHED: Using full violation_frame for vehicle_image (same as plate_image)")

            logger.info(f"VIOLATION-WORKER: Track {track_id}: {speed:.1f} km/h, Plate: {plate_text if plate_text else 'NULL (manual review)'}")

            # Validate frame_id match before saving
            plate_frame_id = violation_data.get('plate_frame_id')
            vehicle_frame_id = violation_data.get('vehicle_frame_id')
            plate_frame_type = violation_data.get('plate_frame_type', 'unknown')
            vehicle_frame_type = violation_data.get('vehicle_frame_type', 'unknown')
            
            # Critical validation: plate_image and vehicle_image MUST be from the same frame
            if plate_frame_id is not None and vehicle_frame_id is not None:
                if plate_frame_id != vehicle_frame_id:
                    logger.error(f"FRAME MISMATCH: plate_frame_id={plate_frame_id} != vehicle_frame_id={vehicle_frame_id}")
                    logger.error("Discarding OCR result to prevent inconsistent evidence")
                    logger.error("Setting plate_text=None, plate_status=MANUAL_REQUIRED")
                    # Discard OCR result - set plate_text to None to trigger MANUAL_REQUIRED
                    plate_text = None
                    plate_image = None  # Also discard plate_image to force manual review
                    confidence = 0.0
                else:
                    logger.debug(f"FRAME MATCH: plate_frame_id={plate_frame_id} == vehicle_frame_id={vehicle_frame_id} (type={plate_frame_type})")
            elif plate_frame_id is not None or vehicle_frame_id is not None:
                # One has frame_id but the other doesn't - log warning but allow (backward compatibility)
                logger.warning(f"Partial frame tracking: plate_frame_id={plate_frame_id}, vehicle_frame_id={vehicle_frame_id}")

            # Prepare plate info (include validation state)
            plate_info = {
                'plate_text': plate_text,
                'plate_image': plate_image,
                'confidence': confidence,
                'validation_state': violation_data.get('validation_state'),
                'sharpness': violation_data.get('sharpness', 0.0)
            }

            # Save violation (images and video)
            try:
                # Use vehicle_image if available, otherwise use violation_frame with bbox
                frame_to_save = vehicle_image if vehicle_image is not None else violation_frame
                bbox_to_use = None if vehicle_image is not None else bbox
                
                # Get frame buffer for video creation
                frame_buffer = None
                violation_frame_number = violation_data.get('violation_frame_number')
                if violation_frame_number is not None:
                    with self.buffer_lock:
                        if track_id in self.original_frame_buffer:
                            # Deep copy frame buffer để tránh race condition
                            # Đảm bảo frame buffer có đủ frames và format đúng
                            buffer_deque = self.original_frame_buffer[track_id]
                            if len(buffer_deque) > 0:
                                frame_buffer = []
                                for frame_data in buffer_deque:
                                    # Validate frame_data structure
                                    if isinstance(frame_data, dict) and 'frame' in frame_data:
                                        # Deep copy frame để tránh reference issues
                                        frame_copy = frame_data['frame'].copy() if frame_data['frame'] is not None else None
                                        if frame_copy is not None:
                                            frame_buffer.append({
                                                'frame': frame_copy,
                                                'frame_number': frame_data.get('frame_number'),
                                                'bbox': frame_data.get('bbox'),
                                                'detection': frame_data.get('detection')
                                            })
                                
                                if len(frame_buffer) > 0:
                                    logger.debug(f"Frame buffer prepared: {len(frame_buffer)} frames for video creation")
                                else:
                                    logger.warning("Frame buffer is empty after validation")
                            else:
                                logger.warning(f"Frame buffer is empty for track {track_id}")
                        else:
                            logger.warning(f"Track {track_id} not found in original_frame_buffer")
                else:
                    logger.warning("violation_frame_number is None, cannot create video")
                
                result = self.violation_handler.save_violation(
                    frame_to_save,
                    track_id,
                    speed,
                    plate_info,
                    bbox_to_use,
                    frame_buffer=frame_buffer,
                    violation_frame_number=violation_frame_number,
                    fps=self.fps
                )
                
                # Kiểm tra result từ save_violation
                if result is None:
                    logger.error(f"ERROR: save_violation returned None for Track {track_id} → SKIP saving to DB")
                    logger.warning("This should NOT happen - violation should always be saved!")
                    # Vẫn finalize track để tránh xử lý lại
                    self.vehicle_collector.finalize_track(track_id)
                    continue
                else:
                    logger.debug(f"save_violation returned result for Track {track_id} - Proceeding to DB save")
                
                result['vehicle_class'] = vehicle_class

                # Save to database
                violation_id = None
                if self.db:
                    try:
                        violation_id = self.db.save_violation(result)
                        result['id'] = violation_id
                        logger.info(f"Saved to DB: ID={violation_id}")
                    except Exception as e:
                        logger.error(f"Error saving to DB: {e}", exc_info=True)
                        import traceback
                        traceback.print_exc()

                # Finalize track
                self.vehicle_collector.finalize_track(track_id)

                # Push to Telegram queue
                if not self.telegram_queue.full():
                    try:
                        self.telegram_queue.put_nowait({
                            'violation_id': violation_id,
                            'result': result
                        })
                    except:
                        pass

                logger.debug("VIOLATION-WORKER: Done")
            except Exception as e:
                logger.error(f"Error processing violation: {e}", exc_info=True)
                import traceback
                traceback.print_exc()

    # ========== THREAD 7: TELEGRAM WORKER ==========
    def _telegram_worker(self):
        """Thread 7: Send Telegram notifications"""
        while self.is_running:
            if self.is_paused:
                time.sleep(0.1)
                continue

            try:
                telegram_data = self.telegram_queue.get(timeout=0.5)
            except:
                continue

            if telegram_data is None:
                continue

            violation_id = telegram_data['violation_id']
            result = telegram_data['result']

            if not self.telegram:
                continue

            # Prepare image and video paths
            vehicle_path = None
            plate_path = None
            video_path = None

            vehicle_image = result.get('vehicle_image')
            if vehicle_image:
                vehicle_path = f"uploads/violations/{vehicle_image}"
                if not os.path.exists(vehicle_path):
                    vehicle_path = None

            plate_image = result.get('plate_image')
            if plate_image:
                plate_path = f"uploads/violations/{plate_image}"
                if not os.path.exists(plate_path):
                    plate_path = None

            video = result.get('video')
            if video:
                video_path = f"uploads/violations/{video}"
                if not os.path.exists(video_path):
                    video_path = None

            # KIỂM TRA ĐIỀU KIỆN TRƯỚC KHI GỬI TELEGRAM
            # Chỉ gửi khi có đủ chứng cứ: ảnh biển số + độ tin cậy cao + không phải "Biển số mờ"
            plate_text = result.get('plate_text')
            confidence = result.get('confidence', 0.0)
            ocr_confidence = result.get('ocr_confidence', 0.0)
            max_confidence = max(confidence, ocr_confidence)
            
            # Kiểm tra 1: Có ảnh biển số không?
            has_plate_image = plate_path is not None and os.path.exists(plate_path)
            
            # Kiểm tra 2: Độ tin cậy cao (>= 0.75 = 75%)
            has_high_confidence = max_confidence >= 0.75
            
            # Kiểm tra 3: Không phải "Biển số mờ" hoặc các giá trị invalid
            is_valid_plate = False
            if plate_text:
                plate_text_str = str(plate_text).strip().upper()
                invalid_values = ['UNKNOWN', 'NONE', 'N/A', 'NULL', 'NAN', 'BIỂN SỐ MỜ', 'BIỂN QUÁ MỜ', '']
                is_valid_plate = plate_text_str not in invalid_values and len(plate_text_str) > 0
            else:
                is_valid_plate = False
            
            # Quyết định có gửi Telegram không
            should_send_telegram = has_plate_image and has_high_confidence and is_valid_plate
            
            if not should_send_telegram:
                reason = []
                if not has_plate_image:
                    reason.append("không có ảnh biển số")
                if not has_high_confidence:
                    reason.append(f"độ tin cậy thấp ({max_confidence*100:.1f}% < 75%)")
                if not is_valid_plate:
                    reason.append("biển số không hợp lệ hoặc 'Biển số mờ'")
                
                logger.debug(f"SKIP violation ID={violation_id}: {', '.join(reason)}, Plate: {plate_text or 'None'}, Confidence: {max_confidence*100:.1f}%")
                logger.debug(f"Has plate image: {has_plate_image}")
                
                # Đánh dấu là không gửi (không phải lỗi, mà là skip)
                if self.db and violation_id:
                    # Không update telegram_sent vì không gửi (giữ nguyên 0 hoặc NULL)
                    pass
                continue
            
            # Đủ điều kiện → Gửi Telegram
            logger.info(f"Đủ điều kiện gửi Telegram cho violation ID={violation_id}")
            logger.debug(f"Plate: {plate_text}, Confidence: {max_confidence*100:.1f}%")
            logger.debug(f"Has plate image: {has_plate_image}")
            
            try:
                self.telegram.send_violation(result, vehicle_path, plate_path, video_path)
                logger.info(f"Sent notification for violation ID={violation_id}")

                # Update status
                if self.db and violation_id:
                    self.db.update_violation_status(violation_id, 'sent')
            except Exception as e:
                logger.error(f"Error sending notification: {e}", exc_info=True)
                if self.db and violation_id:
                    self.db.update_violation_status(violation_id, 'failed')

    # ========== HELPER METHODS ==========
    def _annotate_frame(self, frame, detections):
        self.speed_calc.draw_lines(frame)
        frame = self.detector.draw_detections(frame, detections)

        timestamp = datetime.now().strftime("%H:%M:%S")
        cv2.putText(frame, timestamp, (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

        if self.is_paused:
            cv2.putText(frame, "PAUSED", (100, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
        else:
            cv2.putText(frame, "LIVE", (100, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)

        return frame

    def get_frame(self):
        with self.display_lock:
            if self.annotated_frame is not None:
                _, jpeg = cv2.imencode('.jpg', self.annotated_frame,
                                       [cv2.IMWRITE_JPEG_QUALITY, 80])
                return jpeg.tobytes()
        return None

    def get_detections(self):
        with self.display_lock:
            return self.display_detections.copy()

    def get_memory_stats(self):
        """Get memory usage statistics from track buffer"""
        try:
            stats = self.track_buffer_manager.get_total_memory_usage()
            return stats
        except Exception as e:
            return {'error': str(e), 'num_tracks': 0, 'total_mb': 0}

    def generate_stream(self):
        """Generate stream - ưu tiên annotated frame có bbox, đồng bộ với FPS"""
        if self.fps <= 0:
            self.fps = 30.0
        
        frame_interval = 1.0 / self.fps  # Match video FPS chính xác
        last_frame_time = time.time()
        
        while self.is_running:
            frame_bytes = None
            
            # Ưu tiên: Lấy annotated frame (có bbox và detections)
            frame_bytes = self.get_frame()
            
            # Fallback: Nếu không có annotated frame, lấy từ clean queue
            if not frame_bytes:
                try:
                    latest_frame = None
                    # Lấy frame mới nhất, bỏ qua frames cũ
                    while not self.stream_queue_clean.empty():
                        latest_frame = self.stream_queue_clean.get_nowait()
                    if latest_frame:
                        frame_bytes = latest_frame
                except:
                    pass
            
            if frame_bytes:
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
                
                # ĐỒNG BỘ: Sleep đúng thời gian để match FPS
                current_time = time.time()
                elapsed = current_time - last_frame_time
                sleep_time = frame_interval - elapsed
                if sleep_time > 0:
                    time.sleep(sleep_time)
                last_frame_time = time.time()
            else:
                # Nếu không có frame, sleep ngắn để tránh CPU spin
                # Nhưng không sleep quá lâu để đảm bảo hiển thị ngay khi có frame
                time.sleep(0.033)  # ~30fps fallback
                continue
