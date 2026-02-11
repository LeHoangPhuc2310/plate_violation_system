import cv2
import numpy as np
from collections import defaultdict


class VehicleCollector:

    def __init__(self, max_frames=30):
        self.max_frames = max_frames
        self.vehicle_buffer = defaultdict(list)
        self.finalized_tracks = set()

    def add_vehicle_crop(self, track_id, raw_frame, vehicle_bbox):
        if track_id in self.finalized_tracks:
            return False

        if len(self.vehicle_buffer[track_id]) >= self.max_frames:
            oldest = self.vehicle_buffer[track_id].pop(0)

        x1, y1, x2, y2 = map(int, vehicle_bbox)
        fh, fw = raw_frame.shape[:2]
        pad = 30
        x1 = max(0, x1 - pad)
        y1 = max(0, y1 - pad)
        x2 = min(fw, x2 + pad)
        y2 = min(fh, y2 + pad)

        vehicle_crop = raw_frame[y1:y2, x1:x2].copy()

        h, w = vehicle_crop.shape[:2]
        if h < 50 or w < 50:
            return False

        gray = cv2.cvtColor(vehicle_crop, cv2.COLOR_BGR2GRAY)
        sharpness = cv2.Laplacian(gray, cv2.CV_64F).var()

        self.vehicle_buffer[track_id].append({
            'vehicle_crop': vehicle_crop,
            'bbox': vehicle_bbox,
            'sharpness': sharpness
        })

        return True

    def get_best_crops(self, track_id, top_n=5):
        crops = self.vehicle_buffer.get(track_id, [])
        if not crops:
            return []

        sorted_crops = sorted(crops, key=lambda x: x['sharpness'], reverse=True)
        return sorted_crops[:top_n]

    def get_frame_count(self, track_id):
        return len(self.vehicle_buffer[track_id])

    def finalize_track(self, track_id):
        self.finalized_tracks.add(track_id)
        if track_id in self.vehicle_buffer:
            del self.vehicle_buffer[track_id]

    def is_finalized(self, track_id):
        return track_id in self.finalized_tracks

    def reset(self):
        self.vehicle_buffer.clear()
        self.finalized_tracks.clear()
