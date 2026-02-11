"""
Track History Manager
Quản lý lịch sử frames cho mỗi track_id để tìm frame tốt nhất cho OCR
"""

import time
import threading
from collections import defaultdict


class TrackHistoryManager:
    """
    Quản lý lịch sử frames cho mỗi track để tìm frame tốt nhất cho OCR.
    Chọn frame có bbox area LỚN NHẤT (xe gần camera = biển rõ nhất).
    """

    def __init__(self, max_history_frames=30, max_age_seconds=10.0):
        """Khởi tạo với số frame tối đa và thời gian tối đa giữ history"""
        self.track_histories = defaultdict(list)
        self.max_history_frames = max_history_frames
        self.max_age_seconds = max_age_seconds
        self._lock = threading.Lock()

        print(f"[HISTORY] Initialized: max_frames={max_history_frames}, max_age={max_age_seconds}s")

    def add_frame(self, track_id, frame, bbox, frame_number, vehicle_class='unknown'):
        """Thêm frame vào history của track"""
        with self._lock:
            # Tính diện tích bbox
            x1, y1, x2, y2 = bbox
            area = (x2 - x1) * (y2 - y1)

            # Tạo entry mới
            entry = {
                'frame': frame.copy(),  # Deep copy để tránh reference issues
                'bbox': bbox,
                'area': area,
                'frame_number': frame_number,
                'timestamp': time.time(),
                'vehicle_class': vehicle_class
            }

            # Thêm vào history
            self.track_histories[track_id].append(entry)

            # Giữ chỉ N frames gần nhất
            if len(self.track_histories[track_id]) > self.max_history_frames:
                self.track_histories[track_id].pop(0)

            # Debug log (chỉ mỗi 10 frames)
            if len(self.track_histories[track_id]) % 10 == 0:
                print(f"[HISTORY] Track {track_id}: {len(self.track_histories[track_id])} frames, "
                      f"area={area:.0f}, frame#{frame_number}")

    def get_best_frame(self, track_id):
        """
        Lấy frame có bbox area LỚN NHẤT (xe gần camera nhất)

        Args:
            track_id: ID của track

        Returns:
            dict: Entry của frame tốt nhất, hoặc None nếu không có history
            {
                'frame': np.array,
                'bbox': (x1,y1,x2,y2),
                'area': float,
                'frame_number': int,
                'timestamp': float,
                'vehicle_class': str
            }
        """
        with self._lock:
            history = self.track_histories.get(track_id)

            if not history:
                print(f"[HISTORY] [ERR] Track {track_id}: No history available")
                return None

            # Tìm frame có area lớn nhất
            best_entry = max(history, key=lambda x: x['area'])

            # Stats
            areas = [h['area'] for h in history]
            min_area = min(areas)
            max_area = max(areas)
            avg_area = sum(areas) / len(areas)

            print(f"[HISTORY] [OK] Track {track_id}: Found best frame")
            print(f"  - Total frames in history: {len(history)}")
            print(f"  - Best frame number: {best_entry['frame_number']}")
            print(f"  - Best bbox area: {best_entry['area']:.1f} px²")
            print(f"  - Area range: {min_area:.1f} - {max_area:.1f} px² (avg: {avg_area:.1f})")
            print(f"  - Best frame is {(best_entry['area'] / avg_area - 1) * 100:.1f}% larger than average")

            return best_entry

    def has_history(self, track_id):
        """Kiểm tra track có history không"""
        with self._lock:
            return track_id in self.track_histories and len(self.track_histories[track_id]) > 0

    def get_history_count(self, track_id):
        """Lấy số lượng frames trong history"""
        with self._lock:
            return len(self.track_histories.get(track_id, []))

    def clear_track(self, track_id):
        """
        Xóa history sau khi xử lý xong
        QUAN TRỌNG: Phải gọi sau khi lưu violation để tránh memory leak
        """
        with self._lock:
            if track_id in self.track_histories:
                count = len(self.track_histories[track_id])
                del self.track_histories[track_id]
                print(f"[HISTORY] 🗑️  Cleared track {track_id}: {count} frames removed")

    def cleanup_old_tracks(self):
        """
        Xóa các tracks quá cũ (không còn active)
        Gọi định kỳ để tránh memory leak
        """
        with self._lock:
            current_time = time.time()
            tracks_to_remove = []

            for track_id, history in self.track_histories.items():
                if not history:
                    tracks_to_remove.append(track_id)
                    continue

                # Kiểm tra frame mới nhất
                latest_frame = history[-1]
                age = current_time - latest_frame['timestamp']

                if age > self.max_age_seconds:
                    tracks_to_remove.append(track_id)

            # Xóa tracks cũ
            for track_id in tracks_to_remove:
                count = len(self.track_histories[track_id])
                del self.track_histories[track_id]
                print(f"[HISTORY] 🗑️  Auto-removed old track {track_id}: {count} frames")

            if tracks_to_remove:
                print(f"[HISTORY] Cleanup: Removed {len(tracks_to_remove)} old tracks")

    def get_stats(self):
        """Lấy thống kê về history"""
        with self._lock:
            total_tracks = len(self.track_histories)
            total_frames = sum(len(h) for h in self.track_histories.values())

            return {
                'total_tracks': total_tracks,
                'total_frames': total_frames,
                'avg_frames_per_track': total_frames / total_tracks if total_tracks > 0 else 0
            }

    def reset(self):
        """Reset toàn bộ history (dùng khi kết thúc video)"""
        with self._lock:
            stats = self.get_stats()
            self.track_histories.clear()
            print(f"[HISTORY] 🔄 Reset: Cleared {stats['total_tracks']} tracks, "
                  f"{stats['total_frames']} frames")
