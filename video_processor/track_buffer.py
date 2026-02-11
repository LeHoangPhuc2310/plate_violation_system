"""
Track Buffer - Smart Plate Crops Storage
Stores only plate crops + 1 best full frame per track
Memory: 6.5 MB/track (vs 89 MB with full frames)
"""
import cv2
import numpy as np
import time
from typing import Dict, List, Optional, Tuple
from collections import deque


class TrackBuffer:
    """Buffer for storing plate crops and best frame for a single track"""

    def __init__(self, track_id: int, max_crops: int = 10, min_sharpness: float = 150.0):
        """
        Args:
            track_id: Vehicle track ID
            max_crops: Maximum number of plate crops to store
            min_sharpness: Minimum sharpness threshold (default: 150.0)
        """
        self.track_id = track_id
        self.max_crops = max_crops
        self.min_sharpness = min_sharpness  # Reject blurry images

        # Plate crops storage
        self.plate_crops = deque(maxlen=max_crops)  # [(crop_img, sharpness, confidence, timestamp)]
        self.plate_results = deque(maxlen=max_crops)  # [{'text': ..., 'conf': ..., 'sharpness': ...}]

        # Best full frame
        self.best_full_frame = None
        self.best_full_frame_bbox = None
        self.best_score = 0.0  # Combined score: sharpness * confidence

        # Metadata
        self.first_seen = time.time()
        self.last_seen = time.time()
        self.frame_count = 0

        # Best plate info
        self.best_plate_text = None
        self.best_plate_confidence = 0.0
        self.best_plate_sharpness = 0.0
        self.best_plate_crop = None

    def add_frame(self, full_frame: np.ndarray, bbox: List[int],
                  plate_crop: np.ndarray, plate_result: Dict, frame_number: Optional[int] = None):
        """
        Add a new frame with plate detection

        Args:
            full_frame: Full video frame
            bbox: Vehicle bounding box [x1, y1, x2, y2]
            plate_crop: Cropped plate image
            plate_result: ALPR result dict with 'text', 'confidence', 'sharpness'
            frame_number: Frame number for tracking (optional)
        """
        self.last_seen = time.time()
        self.frame_count += 1

        # Extract metrics
        confidence = plate_result.get('confidence', 0.0)
        sharpness = plate_result.get('sharpness', 0.0)
        plate_text = plate_result.get('text', '')

        # Add frame_number to plate_result if provided
        if frame_number is not None:
            plate_result = plate_result.copy()  # Don't modify original
            plate_result['frame_number'] = frame_number
            plate_result['frame_type'] = 'buffer'  # Mark as buffer frame

        # QUALITY FILTER: Reject if sharpness too low (blurry image)
        if sharpness < self.min_sharpness:
            print(f"[TRACK-BUFFER] [WARN] Track {self.track_id}: Sharpness {sharpness:.0f} < {self.min_sharpness:.0f} → SKIP (too blurry)")
            return  # Don't add blurry frames to buffer

        # Calculate combined score
        score = sharpness * confidence

        # Store plate crop and result
        timestamp = time.time()
        self.plate_crops.append((plate_crop.copy(), sharpness, confidence, timestamp))
        self.plate_results.append(plate_result)

        # Update best plate crop
        if score > (self.best_plate_sharpness * self.best_plate_confidence):
            self.best_plate_text = plate_text
            self.best_plate_confidence = confidence
            self.best_plate_sharpness = sharpness
            self.best_plate_crop = plate_crop.copy()
            print(f"[TRACK-BUFFER] [OK] Track {self.track_id}: NEW BEST plate '{plate_text}' (sharp={sharpness:.0f}, conf={confidence:.2f})")

        # Update best full frame
        if score > self.best_score and plate_text:  # Only if plate detected
            self.best_score = score
            self.best_full_frame = full_frame.copy()
            self.best_full_frame_bbox = bbox.copy()
            print(f"[TRACK-BUFFER] [OK] Track {self.track_id}: NEW BEST frame (score={score:.0f})")

    def get_best_plate_crop(self) -> Optional[np.ndarray]:
        """Get the best plate crop image"""
        return self.best_plate_crop

    def get_best_full_frame(self) -> Optional[Tuple[np.ndarray, List[int]]]:
        """Get the best full frame and bbox"""
        if self.best_full_frame is not None:
            return self.best_full_frame, self.best_full_frame_bbox
        return None, None

    def get_best_plate_info(self) -> Dict:
        """Get best plate detection info"""
        return {
            'text': self.best_plate_text,
            'confidence': self.best_plate_confidence,
            'sharpness': self.best_plate_sharpness,
            'score': self.best_plate_sharpness * self.best_plate_confidence
        }

    def get_all_plate_results(self) -> List[Dict]:
        """Get all plate detection results for voting"""
        return list(self.plate_results)

    def get_memory_usage(self) -> Dict:
        """Calculate memory usage in MB"""
        crop_mem = 0
        for crop, _, _, _ in self.plate_crops:
            crop_mem += crop.nbytes

        frame_mem = self.best_full_frame.nbytes if self.best_full_frame is not None else 0
        best_crop_mem = self.best_plate_crop.nbytes if self.best_plate_crop is not None else 0

        total_mb = (crop_mem + frame_mem + best_crop_mem) / (1024 * 1024)

        return {
            'plate_crops_mb': crop_mem / (1024 * 1024),
            'best_frame_mb': frame_mem / (1024 * 1024),
            'best_crop_mb': best_crop_mem / (1024 * 1024),
            'total_mb': total_mb,
            'num_crops': len(self.plate_crops)
        }

    def cleanup(self):
        """Release all memory"""
        self.plate_crops.clear()
        self.plate_results.clear()
        self.best_full_frame = None
        self.best_full_frame_bbox = None
        self.best_plate_crop = None


class TrackBufferManager:
    """Manage buffers for all active tracks"""

    def __init__(self, max_crops_per_track: int = 10):
        """
        Args:
            max_crops_per_track: Max plate crops to store per track
        """
        self.max_crops = max_crops_per_track
        self.buffers: Dict[int, TrackBuffer] = {}
        self.cleanup_threshold = 3.0  # Cleanup tracks not seen for 3 seconds

    def get_or_create_buffer(self, track_id: int) -> TrackBuffer:
        """Get existing buffer or create new one"""
        if track_id not in self.buffers:
            self.buffers[track_id] = TrackBuffer(track_id, self.max_crops)
        return self.buffers[track_id]

    def add_frame(self, track_id: int, full_frame: np.ndarray, bbox: List[int],
                  plate_crop: np.ndarray, plate_result: Dict):
        """Add frame to track buffer"""
        buffer = self.get_or_create_buffer(track_id)
        buffer.add_frame(full_frame, bbox, plate_crop, plate_result)

    def get_buffer(self, track_id: int) -> Optional[TrackBuffer]:
        """Get buffer for track"""
        return self.buffers.get(track_id)

    def remove_buffer(self, track_id: int):
        """Remove and cleanup buffer"""
        if track_id in self.buffers:
            self.buffers[track_id].cleanup()
            del self.buffers[track_id]

    def cleanup_old_tracks(self, active_track_ids: List[int]):
        """
        Cleanup tracks that are no longer active

        Args:
            active_track_ids: List of currently active track IDs
        """
        current_time = time.time()
        to_remove = []

        for track_id, buffer in self.buffers.items():
            # Remove if not in active list and not seen recently
            if track_id not in active_track_ids:
                time_since_last = current_time - buffer.last_seen
                if time_since_last > self.cleanup_threshold:
                    to_remove.append(track_id)

        for track_id in to_remove:
            print(f"[TRACK_BUFFER] Cleanup track {track_id} (inactive)")
            self.remove_buffer(track_id)

    def get_total_memory_usage(self) -> Dict:
        """Get total memory usage across all tracks"""
        total_mb = 0
        num_tracks = len(self.buffers)

        details = {}
        for track_id, buffer in self.buffers.items():
            usage = buffer.get_memory_usage()
            total_mb += usage['total_mb']
            details[track_id] = usage

        return {
            'num_tracks': num_tracks,
            'total_mb': total_mb,
            'avg_mb_per_track': total_mb / num_tracks if num_tracks > 0 else 0,
            'details': details
        }

    def cleanup_all(self):
        """Cleanup all buffers"""
        for buffer in self.buffers.values():
            buffer.cleanup()
        self.buffers.clear()


# Singleton instance
_buffer_manager = None


def get_buffer_manager(max_crops_per_track: int = 10) -> TrackBufferManager:
    """Get or create global buffer manager"""
    global _buffer_manager
    if _buffer_manager is None:
        _buffer_manager = TrackBufferManager(max_crops_per_track)
    return _buffer_manager
