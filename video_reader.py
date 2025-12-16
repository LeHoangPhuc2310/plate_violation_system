"""
VIDEO READER FOR OFFLINE VIDEO PROCESSING
==========================================

Đọc video offline NHANH NHẤT có thể - KHÔNG giật, KHÔNG nhảy frame

NGUYÊN TẮC:
✅ Đọc frame nhanh nhất có thể (NO time.sleep())
✅ FPS chỉ để tính timestamp, KHÔNG để delay
✅ Mọi frame được đọc đúng thứ tự
✅ Timestamp = frame_number / fps (KHÔNG dùng time.time())
✅ Video reader CỰC NHẸ - chỉ đọc và push

❌ KHÔNG time.sleep()
❌ KHÔNG skip frame ở đây
❌ KHÔNG chạy AI
❌ KHÔNG resize/modify frame
❌ KHÔNG dùng time.time() cho timestamp
"""

import cv2
import threading
from collections import deque
import time
import queue


class OfflineVideoReader:
    """
    Video reader tối ưu cho OFFLINE VIDEO (không phải realtime camera)

    Đọc video nhanh nhất có thể, không delay theo FPS.
    Worker phía sau chậm thì queue sẽ đầy và tự điều chỉnh.
    """

    def __init__(self, video_path, detection_queue, original_frame_buffer,
                 detection_frequency=1, detection_scale=1.0, cap_lock=None):
        """
        Args:
            video_path: Đường dẫn file video
            detection_queue: Queue để push frame cho detection worker
            original_frame_buffer: Dict buffer lưu frame gốc
            detection_frequency: Mỗi N frame thì push vào detection_queue
            detection_scale: Scale để resize frame cho detection (0.5 = 50%)
            cap_lock: Lock để thread-safe (nếu có)
        """
        self.video_path = video_path
        self.detection_queue = detection_queue
        self.original_frame_buffer = original_frame_buffer
        self.detection_frequency = detection_frequency
        self.detection_scale = detection_scale
        self.cap_lock = cap_lock if cap_lock else threading.Lock()

        self.cap = None
        self.fps = 30.0
        self.frame_count_total = 0
        self.running = False
        self.thread = None
        self.loop = True  # Mặc định loop video

    def open_video(self):
        """Mở video và lấy thông tin"""
        self.cap = cv2.VideoCapture(self.video_path)

        if not self.cap.isOpened():
            raise ValueError(f"Cannot open video: {self.video_path}")

        # Lấy FPS từ video
        self.fps = self.cap.get(cv2.CAP_PROP_FPS)
        if self.fps <= 0 or self.fps > 1000:
            self.fps = 30.0
            print(f"[VIDEO READER] ⚠️  Invalid FPS, using default: {self.fps}")

        # Lấy tổng số frame
        self.frame_count_total = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))

        width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        print(f"[VIDEO READER] ✅ Video opened: {width}x{height} @ {self.fps:.2f} FPS")
        print(f"[VIDEO READER] Total frames: {self.frame_count_total}")
        print(f"[VIDEO READER] Duration: {self.frame_count_total / self.fps:.2f}s")

        return self.cap

    def calculate_timestamp(self, frame_number):
        """
        Tính timestamp CHÍNH XÁC từ frame number và FPS

        ✅ ĐÚNG: timestamp = frame_number / fps
        ❌ SAI: timestamp = time.time()
        """
        return frame_number / self.fps

    def reset(self):
        """Reset video về đầu để loop"""
        if self.cap and self.cap.isOpened():
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            print(f"[VIDEO READER] 🔄 Reset video to beginning")

    def read_frame(self):
        """
        Đọc 1 frame từ video

        Returns:
            (success, frame, frame_number)
        """
        if not self.cap or not self.cap.isOpened():
            return False, None, 0

        with self.cap_lock:
            ret, frame = self.cap.read()
            if ret:
                # Lấy frame number hiện tại
                frame_number = int(self.cap.get(cv2.CAP_PROP_POS_FRAMES))
                return True, frame, frame_number
            else:
                return False, None, 0

    def video_reader_thread(self, stream_queue_clean=None, alpr_proactive_queue=None, alpr_frequency=3, active_tracks=None, active_tracks_lock=None):
        """
        THREAD ĐỌC VIDEO OFFLINE - DUAL-STREAM ARCHITECTURE + DIRECT FRAME BUFFERING
        
        Push frame vào nhiều queue:
        - stream_queue_clean: Mọi frame (web stream mượt)
        - alpr_proactive_queue: Mỗi N frame (ALPR proactive)
        - detection_queue: Mỗi detection_frequency frame (detection)
        - original_frame_buffer[track_id]: MỌI frame cho TẤT CẢ active tracks (NEW)
        """
        print("[VIDEO READER] 🚀 Thread started - Reading at MAXIMUM speed")
        print(f"[VIDEO READER] Detection frequency: every {self.detection_frequency} frame(s)")
        print(f"[VIDEO READER] Detection scale: {self.detection_scale * 100}%")
        if stream_queue_clean:
            print("[VIDEO READER] ✅ Stream queue enabled (smooth web stream)")
        if alpr_proactive_queue:
            print(f"[VIDEO READER] ✅ ALPR proactive queue enabled (every {alpr_frequency} frames)")
        if active_tracks is not None:
            print("[VIDEO READER] ✅ Active tracks buffering enabled (direct frame buffer)")

        frame_count = 0
        frames_pushed_to_detection = 0

        if 'global' not in self.original_frame_buffer:
            self.original_frame_buffer['global'] = deque(maxlen=150)

        while self.running:
            ret, frame, frame_number = self.read_frame()

            if not ret or frame is None:
                print(f"[VIDEO READER] ✅ Video finished - Read {frame_count} frames")
                print(f"[VIDEO READER] Pushed {frames_pushed_to_detection} frames to detection")
                
                # FIX: Loop video nếu self.loop = True
                if self.loop:
                    print(f"[VIDEO READER] 🔄 Looping video...")
                    self.reset()  # Reset về đầu video
                    frame_count = 0
                    frames_pushed_to_detection = 0
                    continue
                else:
                    break

            frame_count += 1
            timestamp = self.calculate_timestamp(frame_number)
            original_frame = frame.copy()

            frame_data = {
                'frame': original_frame,
                'frame_id': frame_count,
                'timestamp': timestamp,
                'frame_number': frame_number  # NEW: Store frame_number for debugging
            }

            # Save to global (existing)
            self.original_frame_buffer['global'].append(frame_data)

            # NEW: Save to ALL active track buffers (đảm bảo frames liên tục, không skip)
            if active_tracks_lock:
                with active_tracks_lock:
                    for track_id in list(active_tracks.keys()):
                        if track_id not in self.original_frame_buffer:
                            self.original_frame_buffer[track_id] = deque(maxlen=150)
                        self.original_frame_buffer[track_id].append(frame_data.copy())

            # 1. Push vào stream_queue_clean (MỌI FRAME - web stream mượt)
            if stream_queue_clean is not None:
                try:
                    h, w = frame.shape[:2]
                    stream_width = 1280
                    stream_height = int(h * (stream_width / w))
                    stream_frame = cv2.resize(frame, (stream_width, stream_height), interpolation=cv2.INTER_LINEAR)
                    stream_queue_clean.put(stream_frame, block=False)
                except queue.Full:
                    pass

            # 2. Push vào alpr_proactive_queue (MỖI N FRAME - ALPR proactive)
            if alpr_proactive_queue is not None and frame_count % alpr_frequency == 0:
                try:
                    alpr_proactive_queue.put({
                        'frame': original_frame.copy(),
                        'frame_id': frame_count,
                        'timestamp': timestamp
                    }, block=False)
                except queue.Full:
                    pass

            # 3. Push vào detection_queue (MỖI DETECTION_FREQUENCY FRAME)
            if frame_count % self.detection_frequency == 0:
                if self.detection_scale < 1.0:
                    h, w = frame.shape[:2]
                    detect_w = int(w * self.detection_scale)
                    detect_h = int(h * self.detection_scale)
                    detect_frame = cv2.resize(frame, (detect_w, detect_h), interpolation=cv2.INTER_LINEAR)
                else:
                    detect_frame = frame

                try:
                    if len(self.detection_queue) < self.detection_queue.maxlen:
                        self.detection_queue.append({
                            'frame': detect_frame,
                            'original': original_frame,
                            'frame_id': frame_count,
                            'frame_number': frame_number,  # ACTUAL frame position in source video
                            'timestamp': timestamp
                        })
                        frames_pushed_to_detection += 1
                    else:
                        time.sleep(0.001)
                except Exception as e:
                    print(f"[VIDEO READER] ⚠️  Queue error: {e}")

        print(f"[VIDEO READER] 🏁 Thread stopped")
        print(f"[VIDEO READER] Total frames read: {frame_count}")
        print(f"[VIDEO READER] Total frames sent to detection: {frames_pushed_to_detection}")

    def start(self, stream_queue_clean=None, alpr_proactive_queue=None, alpr_frequency=3, active_tracks=None, active_tracks_lock=None):
        """Khởi động video reader thread với dual-stream support + direct frame buffering"""
        if self.running:
            print("[VIDEO READER] ⚠️  Already running")
            return

        self.open_video()
        self.running = True
        self.thread = threading.Thread(
            target=self.video_reader_thread,
            kwargs={
                'stream_queue_clean': stream_queue_clean,
                'alpr_proactive_queue': alpr_proactive_queue,
                'alpr_frequency': alpr_frequency,
                'active_tracks': active_tracks,
                'active_tracks_lock': active_tracks_lock
            },
            daemon=True
        )
        self.thread.start()
        print("[VIDEO READER] ✅ Started")

    def stop(self):
        """Dừng video reader thread"""
        if not self.running:
            return

        print("[VIDEO READER] 🛑 Stopping...")
        self.running = False

        if self.thread:
            self.thread.join(timeout=2.0)

        if self.cap:
            with self.cap_lock:
                self.cap.release()

        print("[VIDEO READER] ✅ Stopped")

    def get_info(self):
        """Lấy thông tin video"""
        return {
            'fps': self.fps,
            'total_frames': self.frame_count_total,
            'duration': self.frame_count_total / self.fps if self.fps > 0 else 0,
            'width': int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH)) if self.cap else 0,
            'height': int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) if self.cap else 0,
        }


# =============================================================================
# HELPER FUNCTION - Để thay thế video_thread() trong app.py
# =============================================================================

def video_reader_thread(video_path, detection_queue, original_frame_buffer,
                       detection_frequency=1, detection_scale=1.0,
                       camera_running_flag=None, cap_lock=None):
    """
    🎯 HÀM BẮT BUỘC THEO YÊU CẦU

    Video reader cho OFFLINE VIDEO - Không giật, không nhảy frame

    Args:
        video_path: Đường dẫn file video
        detection_queue: Queue để push frame cho detection worker (deque)
        original_frame_buffer: Dict buffer lưu frame gốc
        detection_frequency: Mỗi N frame thì push vào detection (default=1)
        detection_scale: Scale để resize frame cho detection (default=1.0)
        camera_running_flag: Dict/object có attribute 'value' để kiểm tra running state
        cap_lock: Threading lock để thread-safe

    Format dữ liệu frame:
        {
            "frame": numpy.ndarray,      # Frame đã resize cho detection
            "original": numpy.ndarray,   # Frame gốc full size
            "frame_id": int,             # Số thứ tự frame
            "timestamp": float           # Timestamp = frame_id / fps
        }

    ✅ NGUYÊN TẮC:
    - Đọc nhanh nhất có thể (NO delay)
    - FPS chỉ để tính timestamp
    - Không skip frame ở đây
    - Không resize trong reader (chỉ khi push vào detection)
    """
    reader = OfflineVideoReader(
        video_path=video_path,
        detection_queue=detection_queue,
        original_frame_buffer=original_frame_buffer,
        detection_frequency=detection_frequency,
        detection_scale=detection_scale,
        cap_lock=cap_lock
    )

    # Nếu có camera_running_flag, override running state
    if camera_running_flag is not None:
        # Giả sử camera_running_flag là dict với key 'value' hoặc object với attribute 'value'
        if hasattr(camera_running_flag, 'value'):
            while camera_running_flag.value:
                if not reader.running:
                    reader.start()
                time.sleep(0.1)
            reader.stop()
        else:
            # Chạy bình thường
            reader.start()
    else:
        reader.start()


# =============================================================================
# EXAMPLE USAGE
# =============================================================================

if __name__ == "__main__":
    """
    Test video reader với video mẫu
    """
    import time

    # Setup
    detection_queue = deque(maxlen=30)
    original_frame_buffer = {}

    video_path = "test_video.mp4"  # Thay bằng video của bạn

    # Tạo reader
    reader = OfflineVideoReader(
        video_path=video_path,
        detection_queue=detection_queue,
        original_frame_buffer=original_frame_buffer,
        detection_frequency=2,  # Push mỗi 2 frame
        detection_scale=0.5     # Resize 50% cho detection
    )

    # Start
    reader.start()

    # Monitor
    start_time = time.time()
    prev_queue_size = 0

    while reader.running:
        time.sleep(1.0)
        queue_size = len(detection_queue)
        buffer_size = len(original_frame_buffer.get('global', []))
        elapsed = time.time() - start_time

        print(f"[MONITOR] Time: {elapsed:.1f}s | Queue: {queue_size} | Buffer: {buffer_size}")

        # Giả lập detection worker đọc từ queue
        if queue_size > 0:
            frame_data = detection_queue.popleft()
            print(f"[WORKER] Processing frame {frame_data['frame_id']} @ {frame_data['timestamp']:.3f}s")

        if queue_size == prev_queue_size == 0 and elapsed > 5:
            # Video đã đọc xong và queue rỗng
            break

        prev_queue_size = queue_size

    reader.stop()
    print("\n✅ Test completed!")