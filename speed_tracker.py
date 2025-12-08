# speed_tracker.py
import time
import uuid

class SpeedTracker:
    def __init__(self, pixel_to_meter=0.04):
        self.data = {}   # track_id -> info
        self.pixel_to_meter = pixel_to_meter

    def update(self, track_id, bbox):
        x1, y1, x2, y2 = bbox
        cy = (y1 + y2) // 2
        now = time.time()

        # xe mới vào khung
        if track_id not in self.data:
            self.data[track_id] = {
                "first_time": now,
                "first_pos": cy,
                "speed": None,
                "uuid": str(uuid.uuid4())[:8]
            }
            return None

        item = self.data[track_id]

        pixel_dist = abs(cy - item["first_pos"])
        meter_dist = pixel_dist * self.pixel_to_meter
        time_passed = now - item["first_time"]

        if time_passed == 0:
            return None

        speed_kmh = (meter_dist / time_passed) * 3.6
        item["speed"] = round(speed_kmh, 2)

        return item["speed"]
