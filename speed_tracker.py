# speed_tracker.py
"""
Speed Tracker tối ưu cho web streaming
- Tính tốc độ chính xác và mượt
- Nhẹ, không block thread chính
"""
import time
import uuid
from collections import deque

class SpeedTracker:
    def __init__(self, pixel_to_meter=0.04):
        self.data = {}   # track_id -> info
        self.pixel_to_meter = pixel_to_meter
        # Lịch sử vị trí để tính tốc độ chính xác hơn
        self.position_history = {}  # track_id -> deque of (time, position)
        # Tối ưu: Giảm maxlen để nhẹ hơn cho web
        self.max_history = 8  # Giảm từ 10 xuống 8

    def update(self, track_id, bbox):
        x1, y1, x2, y2 = bbox
        # Dùng center point để tính tốc độ
        cx = (x1 + x2) / 2.0
        cy = (y1 + y2) / 2.0
        now = time.time()

        # Xe mới vào khung
        if track_id not in self.data:
            self.data[track_id] = {
                "first_time": now,
                "first_pos": (cx, cy),
                "speed": None,
                "uuid": str(uuid.uuid4())[:8]
            }
            # Khởi tạo lịch sử vị trí
            self.position_history[track_id] = deque(maxlen=self.max_history)  # Giữ 8 điểm gần nhất
            self.position_history[track_id].append((now, (cx, cy)))
            return None

        item = self.data[track_id]
        
        # Thêm vị trí hiện tại vào lịch sử
        self.position_history[track_id].append((now, (cx, cy)))
        
        # Tính tốc độ dựa trên 2 điểm gần nhất (chính xác hơn)
        history = self.position_history[track_id]
        if len(history) < 2:
            return None
        
        # Lấy 2 điểm cuối cùng
        (t1, (x1_pos, y1_pos)) = history[-2]
        (t2, (x2_pos, y2_pos)) = history[-1]
        
        # Tính khoảng cách pixel
        pixel_dist = ((x2_pos - x1_pos) ** 2 + (y2_pos - y1_pos) ** 2) ** 0.5
        time_passed = t2 - t1
        
        if time_passed <= 0:
            # Nếu không có thời gian, dùng phương pháp cũ
            pixel_dist = ((cx - item["first_pos"][0]) ** 2 + (cy - item["first_pos"][1]) ** 2) ** 0.5
            time_passed = now - item["first_time"]
            if time_passed <= 0:
                return item.get("speed")
        else:
            # Cập nhật first_pos để tính tốc độ trung bình
            item["first_pos"] = (cx, cy)
            item["first_time"] = now
        
        # Chuyển đổi sang mét và tính tốc độ
        meter_dist = pixel_dist * self.pixel_to_meter
        speed_ms = meter_dist / time_passed  # m/s
        speed_kmh = speed_ms * 3.6
        
        # Smooth speed với moving average (tối ưu cho web)
        if item["speed"] is not None:
            # Exponential moving average: 75% mới, 25% cũ (ổn định hơn cho web)
            speed_kmh = 0.75 * speed_kmh + 0.25 * item["speed"]
        
        item["speed"] = round(speed_kmh, 2)
        
        # Cleanup: Xóa dữ liệu cũ để tiết kiệm memory (tối ưu cho web)
        # Giữ lại track nếu còn trong frame (có trong position_history)
        return item["speed"]
    
    def cleanup_old_tracks(self, active_track_ids):
        """
        Xóa dữ liệu của các track không còn active (tối ưu memory cho web)
        """
        tracks_to_remove = []
        for track_id in self.data.keys():
            if track_id not in active_track_ids:
                tracks_to_remove.append(track_id)
        
        for track_id in tracks_to_remove:
            if track_id in self.data:
                del self.data[track_id]
            if track_id in self.position_history:
                del self.position_history[track_id]
