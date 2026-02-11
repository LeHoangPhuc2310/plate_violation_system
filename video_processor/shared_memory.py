"""
Shared Memory Pool for Frame Management
Giảm frame copies từ 558MB/s → 150MB/s
"""
import numpy as np
import threading
from collections import deque
from typing import Optional, Dict, Tuple


class SharedFramePool:
    """
    Shared memory pool quản lý frames với reference counting
    Thay vì copy frame 4-6 lần, dùng reference + lock
    """

    def __init__(self, pool_size=100):
        """
        Args:
            pool_size: Số frames tối đa trong pool
        """
        self.pool_size = pool_size
        self.frames: Dict[int, np.ndarray] = {}  # {frame_id: frame_data}
        self.ref_counts: Dict[int, int] = {}     # {frame_id: ref_count}
        self.metadata: Dict[int, dict] = {}      # {frame_id: metadata}
        self.frame_ids = deque(maxlen=pool_size)  # LRU queue
        self.next_id = 0
        self.lock = threading.RLock()  # Reentrant lock

    def add_frame(self, frame: np.ndarray, metadata: dict = None) -> int:
        """
        Thêm frame vào pool, return frame_id

        Args:
            frame: Frame numpy array
            metadata: Dict chứa frame_number, timestamp, etc

        Returns:
            frame_id: ID để reference frame này
        """
        with self.lock:
            frame_id = self.next_id
            self.next_id += 1

            # Store frame và metadata
            self.frames[frame_id] = frame
            self.ref_counts[frame_id] = 1  # Initial reference
            self.metadata[frame_id] = metadata or {}
            self.frame_ids.append(frame_id)

            # Cleanup old frames nếu pool đầy
            if len(self.frames) > self.pool_size:
                self._cleanup_old_frames()

            return frame_id

    def get_frame(self, frame_id: int) -> Optional[Tuple[np.ndarray, dict]]:
        """
        Lấy frame từ pool, tăng ref count

        Args:
            frame_id: ID của frame

        Returns:
            (frame, metadata) hoặc None nếu không tìm thấy
        """
        with self.lock:
            if frame_id not in self.frames:
                return None

            self.ref_counts[frame_id] += 1
            return self.frames[frame_id], self.metadata[frame_id]

    def release_frame(self, frame_id: int):
        """
        Giảm ref count, delete frame nếu ref count = 0

        Args:
            frame_id: ID của frame cần release
        """
        with self.lock:
            if frame_id not in self.ref_counts:
                return

            self.ref_counts[frame_id] -= 1

            # Delete nếu không còn reference
            if self.ref_counts[frame_id] <= 0:
                del self.frames[frame_id]
                del self.ref_counts[frame_id]
                del self.metadata[frame_id]

    def _cleanup_old_frames(self):
        """
        Cleanup frames cũ nhất có ref_count = 1 (chỉ pool reference)
        """
        with self.lock:
            # Tìm frames cũ có thể xóa
            to_delete = []
            for frame_id in list(self.frame_ids):
                if frame_id in self.ref_counts and self.ref_counts[frame_id] == 1:
                    to_delete.append(frame_id)
                    if len(to_delete) >= 10:  # Xóa tối đa 10 frames
                        break

            # Xóa frames
            for frame_id in to_delete:
                if frame_id in self.frames:
                    del self.frames[frame_id]
                    del self.ref_counts[frame_id]
                    del self.metadata[frame_id]

    def clear(self):
        """Clear toàn bộ pool"""
        with self.lock:
            self.frames.clear()
            self.ref_counts.clear()
            self.metadata.clear()
            self.frame_ids.clear()
            self.next_id = 0

    def get_stats(self) -> dict:
        """Lấy thống kê pool"""
        with self.lock:
            total_refs = sum(self.ref_counts.values())
            return {
                'pool_size': len(self.frames),
                'total_references': total_refs,
                'avg_refs_per_frame': total_refs / len(self.frames) if self.frames else 0,
                'memory_mb': sum(f.nbytes for f in self.frames.values()) / 1024 / 1024
            }


class ROICropBuffer:
    """
    Buffer lưu ROI crops thay vì full frames
    Giảm memory từ 186MB/track → 5.4MB/track
    """

    def __init__(self, maxlen=15):
        """
        Args:
            maxlen: Số crops tối đa mỗi track (giảm từ 30 → 15)
        """
        self.maxlen = maxlen
        self.buffers: Dict[int, deque] = {}  # {track_id: deque of crops}
        self.lock = threading.Lock()

    def add_crop(self, track_id: int, vehicle_crop: np.ndarray,
                 plate_crop: Optional[np.ndarray], metadata: dict):
        """
        Thêm vehicle crop và plate crop vào buffer

        Args:
            track_id: ID của track
            vehicle_crop: Vehicle ROI (400×300 thay vì 1920×1080)
            plate_crop: Plate ROI (nếu có)
            metadata: frame_number, bbox, confidence, etc
        """
        with self.lock:
            if track_id not in self.buffers:
                self.buffers[track_id] = deque(maxlen=self.maxlen)

            self.buffers[track_id].append({
                'vehicle_crop': vehicle_crop,
                'plate_crop': plate_crop,
                'metadata': metadata
            })

    def get_crops(self, track_id: int) -> list:
        """
        Lấy tất cả crops của track

        Args:
            track_id: ID của track

        Returns:
            List of crop dicts
        """
        with self.lock:
            if track_id not in self.buffers:
                return []
            return list(self.buffers[track_id])

    def get_best_crops(self, track_id: int, n=5) -> list:
        """
        Lấy n crops tốt nhất (sharpest)

        Args:
            track_id: ID của track
            n: Số crops cần lấy

        Returns:
            List of best crop dicts
        """
        with self.lock:
            if track_id not in self.buffers:
                return []

            crops = list(self.buffers[track_id])

            # Sort by sharpness if available
            if crops and 'sharpness' in crops[0]['metadata']:
                crops_sorted = sorted(crops,
                                    key=lambda x: x['metadata'].get('sharpness', 0),
                                    reverse=True)
                return crops_sorted[:n]

            # Return last n crops
            return crops[-n:] if len(crops) >= n else crops

    def finalize_track(self, track_id: int):
        """
        Xóa buffer của track khi đã xử lý xong

        Args:
            track_id: ID của track
        """
        with self.lock:
            if track_id in self.buffers:
                del self.buffers[track_id]

    def get_memory_usage(self) -> dict:
        """Tính memory usage"""
        with self.lock:
            total_crops = sum(len(buf) for buf in self.buffers.values())
            total_bytes = 0
            for buf in self.buffers.values():
                for crop_data in buf:
                    if crop_data['vehicle_crop'] is not None:
                        total_bytes += crop_data['vehicle_crop'].nbytes
                    if crop_data.get('plate_crop') is not None:
                        total_bytes += crop_data['plate_crop'].nbytes

            return {
                'total_tracks': len(self.buffers),
                'total_crops': total_crops,
                'memory_mb': total_bytes / 1024 / 1024,
                'avg_crops_per_track': total_crops / len(self.buffers) if self.buffers else 0
            }
