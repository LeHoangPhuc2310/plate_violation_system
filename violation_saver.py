"""
Production-ready module for saving traffic violation evidence.
Saves vehicle images, plate images, and violation videos in organized directory structure.
"""

import cv2
import numpy as np
import os
from datetime import datetime
from pathlib import Path
import threading
from typing import List, Tuple, Optional, Dict

# Thread lock for safe file operations
_file_lock = threading.Lock()


class ViolationSaver:
    """
    Handles saving of traffic violation evidence to disk.

    Directory structure:
        violations/
         └── YYYY-MM-DD/
             └── PLATE_NUMBER/
                 ├── vehicle.jpg
                 ├── plate.jpg
                 └── violation.mp4
    """

    def __init__(self, base_dir: str = "violations"):
        """
        Initialize the violation saver.

        Args:
            base_dir: Base directory for saving violations (default: "violations")
        """
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def save_violation(
        self,
        frames: List[np.ndarray],
        fps: int,
        full_frame: np.ndarray,
        vehicle_bbox: Tuple[int, int, int, int],
        plate_bbox: Tuple[int, int, int, int],
        plate_number: str,
        timestamp: float
    ) -> Dict[str, str]:
        """
        Save complete violation evidence (images + video).

        Args:
            frames: List of clean frames (no bounding boxes) for video
            fps: Target FPS for output video
            full_frame: Best clean frame for image extraction
            vehicle_bbox: (x1, y1, x2, y2) vehicle bounding box
            plate_bbox: (x1, y1, x2, y2) plate bounding box
            plate_number: Normalized plate number (uppercase, no spaces)
            timestamp: Unix timestamp of violation

        Returns:
            Dictionary with absolute paths:
            {
                'vehicle_image': '/path/to/vehicle.jpg',
                'plate_image': '/path/to/plate.jpg',
                'video': '/path/to/violation.mp4',
                'folder': '/path/to/violation/folder'
            }

        Raises:
            ValueError: If input validation fails
            IOError: If file saving fails
        """
        # Input validation
        self._validate_inputs(frames, fps, full_frame, vehicle_bbox, plate_bbox, plate_number)

        # Create violation directory
        violation_dir = self._create_violation_directory(plate_number, timestamp)

        # Define output paths
        vehicle_path = violation_dir / "vehicle.jpg"
        plate_path = violation_dir / "plate.jpg"
        video_path = violation_dir / "violation.mp4"

        try:
            # Save vehicle image
            self._save_vehicle_image(full_frame, vehicle_bbox, vehicle_path)

            # Save plate image
            self._save_plate_image(full_frame, plate_bbox, plate_path)

            # Save violation video
            self._save_violation_video(frames, fps, video_path)

            return {
                'vehicle_image': str(vehicle_path.absolute()),
                'plate_image': str(plate_path.absolute()),
                'video': str(video_path.absolute()),
                'folder': str(violation_dir.absolute())
            }

        except Exception as e:
            # Cleanup on failure
            self._cleanup_on_failure(violation_dir)
            raise IOError(f"Failed to save violation evidence: {e}") from e

    def _validate_inputs(
        self,
        frames: List[np.ndarray],
        fps: int,
        full_frame: np.ndarray,
        vehicle_bbox: Tuple[int, int, int, int],
        plate_bbox: Tuple[int, int, int, int],
        plate_number: str
    ) -> None:
        """Validate all input parameters."""
        if not frames or len(frames) == 0:
            raise ValueError("Frames list cannot be empty")

        if fps <= 0 or fps > 120:
            raise ValueError(f"FPS must be between 1 and 120, got {fps}")

        if full_frame is None or full_frame.size == 0:
            raise ValueError("Full frame cannot be empty")

        if not isinstance(full_frame, np.ndarray) or len(full_frame.shape) != 3:
            raise ValueError("Full frame must be a 3D numpy array (H, W, C)")

        if not all(isinstance(x, (int, float)) for x in vehicle_bbox):
            raise ValueError("Vehicle bbox must contain numeric values")

        if not all(isinstance(x, (int, float)) for x in plate_bbox):
            raise ValueError("Plate bbox must contain numeric values")

        if not plate_number or not plate_number.strip():
            raise ValueError("Plate number cannot be empty")

        # Validate bbox coordinates
        x1, y1, x2, y2 = vehicle_bbox
        if x2 <= x1 or y2 <= y1:
            raise ValueError(f"Invalid vehicle bbox: ({x1}, {y1}, {x2}, {y2})")

        x1, y1, x2, y2 = plate_bbox
        if x2 <= x1 or y2 <= y1:
            raise ValueError(f"Invalid plate bbox: ({x1}, {y1}, {x2}, {y2})")

    def _create_violation_directory(self, plate_number: str, timestamp: float) -> Path:
        """
        Create directory structure for violation evidence.

        Returns:
            Path to the violation directory
        """
        # Convert timestamp to date
        date_str = datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d")

        # Normalize plate number (uppercase, remove spaces)
        plate_folder = plate_number.upper().replace(" ", "").replace(".", "").replace("-", "")

        # Create directory path
        violation_dir = self.base_dir / date_str / plate_folder

        # Thread-safe directory creation
        with _file_lock:
            violation_dir.mkdir(parents=True, exist_ok=True)

        return violation_dir

    def _save_vehicle_image(
        self,
        frame: np.ndarray,
        bbox: Tuple[int, int, int, int],
        output_path: Path,
        padding: int = 50,
        quality: int = 70
    ) -> None:
        """
        Crop and save vehicle image with padding.

        Args:
            frame: Source frame (clean, no bounding boxes)
            bbox: (x1, y1, x2, y2) vehicle bounding box
            output_path: Output file path
            padding: Padding around bbox (default: 50px)
            quality: JPEG quality (default: 70)
        """
        h, w = frame.shape[:2]
        x1, y1, x2, y2 = bbox

        # Apply padding with safe bounds
        x1 = max(0, int(x1) - padding)
        y1 = max(0, int(y1) - padding)
        x2 = min(w, int(x2) + padding)
        y2 = min(h, int(y2) + padding)

        # Validate cropped region
        if x2 <= x1 or y2 <= y1:
            raise ValueError(f"Invalid crop region after padding: ({x1}, {y1}, {x2}, {y2})")

        # Crop image
        cropped = frame[y1:y2, x1:x2].copy()

        if cropped.size == 0:
            raise ValueError("Cropped vehicle image is empty")

        # Save with thread safety
        with _file_lock:
            success = cv2.imwrite(
                str(output_path),
                cropped,
                [cv2.IMWRITE_JPEG_QUALITY, quality]
            )

            if not success:
                raise IOError(f"Failed to write vehicle image to {output_path}")

    def _save_plate_image(
        self,
        frame: np.ndarray,
        bbox: Tuple[int, int, int, int],
        output_path: Path,
        padding: int = 20,
        quality: int = 70
    ) -> None:
        """
        Crop and save license plate image with padding.

        Args:
            frame: Source frame (clean, no bounding boxes)
            bbox: (x1, y1, x2, y2) plate bounding box
            output_path: Output file path
            padding: Padding around bbox (default: 20px)
            quality: JPEG quality (default: 70)
        """
        h, w = frame.shape[:2]
        x1, y1, x2, y2 = bbox

        # Apply padding with safe bounds
        x1 = max(0, int(x1) - padding)
        y1 = max(0, int(y1) - padding)
        x2 = min(w, int(x2) + padding)
        y2 = min(h, int(y2) + padding)

        # Validate cropped region
        if x2 <= x1 or y2 <= y1:
            raise ValueError(f"Invalid crop region after padding: ({x1}, {y1}, {x2}, {y2})")

        # Crop image
        cropped = frame[y1:y2, x1:x2].copy()

        if cropped.size == 0:
            raise ValueError("Cropped plate image is empty")

        # Save with thread safety
        with _file_lock:
            success = cv2.imwrite(
                str(output_path),
                cropped,
                [cv2.IMWRITE_JPEG_QUALITY, quality]
            )

            if not success:
                raise IOError(f"Failed to write plate image to {output_path}")

    def _save_violation_video(
        self,
        frames: List[np.ndarray],
        fps: int,
        output_path: Path,
        max_duration: float = 5.0
    ) -> None:
        """
        Create and save violation video from frames.

        Args:
            frames: List of clean frames (no bounding boxes)
            fps: Target FPS for output video
            output_path: Output file path
            max_duration: Maximum video duration in seconds (default: 5.0)
        """
        if not frames:
            raise ValueError("Cannot create video from empty frames list")

        # Calculate max frames based on duration
        max_frames = int(fps * max_duration)

        # Limit frames to max duration
        if len(frames) > max_frames:
            # Sample frames evenly
            indices = np.linspace(0, len(frames) - 1, max_frames, dtype=int)
            frames = [frames[i] for i in indices]

        # Get frame dimensions from first frame
        h, w = frames[0].shape[:2]

        # Try different codecs in order of preference
        codecs = [
            ('avc1', 'H.264/AVC'),
            ('H264', 'H.264'),
            ('X264', 'x264'),
            ('mp4v', 'MPEG-4'),
        ]

        video_writer = None

        for codec, name in codecs:
            try:
                fourcc = cv2.VideoWriter_fourcc(*codec)
                video_writer = cv2.VideoWriter(
                    str(output_path),
                    fourcc,
                    float(fps),
                    (w, h),
                    True
                )

                if video_writer.isOpened():
                    print(f"[VIDEO] Using codec: {name} ({codec}), FPS: {fps}, Size: {w}x{h}")
                    break
                else:
                    video_writer.release()
                    video_writer = None

            except Exception as e:
                if video_writer:
                    video_writer.release()
                video_writer = None
                continue

        if video_writer is None or not video_writer.isOpened():
            raise IOError(f"Failed to create video writer with any codec")

        try:
            # Write frames to video
            frames_written = 0

            for frame in frames:
                # Ensure frame has correct dimensions
                if frame.shape[:2] != (h, w):
                    frame = cv2.resize(frame, (w, h), interpolation=cv2.INTER_LINEAR)

                # Write frame
                video_writer.write(frame)
                frames_written += 1

            if frames_written == 0:
                raise ValueError("No frames were written to video")

            print(f"[VIDEO] Wrote {frames_written} frames, duration: {frames_written/fps:.2f}s")

        finally:
            video_writer.release()

        # Verify output file exists and has size > 0
        if not output_path.exists() or output_path.stat().st_size == 0:
            raise IOError(f"Video file was not created or is empty: {output_path}")

    def _cleanup_on_failure(self, violation_dir: Path) -> None:
        """
        Clean up partially created files on failure.

        Args:
            violation_dir: Directory to clean up
        """
        try:
            if violation_dir.exists():
                # Remove files
                for file_path in violation_dir.glob("*"):
                    if file_path.is_file():
                        file_path.unlink()

                # Remove directory if empty
                if not any(violation_dir.iterdir()):
                    violation_dir.rmdir()

        except Exception as e:
            print(f"[WARNING] Cleanup failed: {e}")


# Convenience function for simple usage
def save_violation_evidence(
    frames: List[np.ndarray],
    fps: int,
    full_frame: np.ndarray,
    vehicle_bbox: Tuple[int, int, int, int],
    plate_bbox: Tuple[int, int, int, int],
    plate_number: str,
    timestamp: float,
    base_dir: str = "violations"
) -> Dict[str, str]:
    """
    Convenience function to save violation evidence.

    Args:
        frames: List of clean frames for video
        fps: Target FPS for output video
        full_frame: Best clean frame for images
        vehicle_bbox: (x1, y1, x2, y2) vehicle bounding box
        plate_bbox: (x1, y1, x2, y2) plate bounding box
        plate_number: Normalized plate number
        timestamp: Unix timestamp of violation
        base_dir: Base directory for violations (default: "violations")

    Returns:
        Dictionary with paths to saved files

    Example:
        >>> import time
        >>> import numpy as np
        >>>
        >>> # Create sample data
        >>> frames = [np.zeros((720, 1280, 3), dtype=np.uint8) for _ in range(30)]
        >>> full_frame = frames[15]
        >>>
        >>> result = save_violation_evidence(
        ...     frames=frames,
        ...     fps=10,
        ...     full_frame=full_frame,
        ...     vehicle_bbox=(100, 100, 400, 300),
        ...     plate_bbox=(150, 200, 250, 250),
        ...     plate_number="30A12345",
        ...     timestamp=time.time()
        ... )
        >>>
        >>> print(result['vehicle_image'])
        >>> print(result['plate_image'])
        >>> print(result['video'])
    """
    saver = ViolationSaver(base_dir=base_dir)
    return saver.save_violation(
        frames=frames,
        fps=fps,
        full_frame=full_frame,
        vehicle_bbox=vehicle_bbox,
        plate_bbox=plate_bbox,
        plate_number=plate_number,
        timestamp=timestamp
    )


if __name__ == "__main__":
    # Example usage and testing
    import time

    print("Testing ViolationSaver...")

    # Create sample frames (720p resolution)
    print("\n1. Creating sample frames...")
    sample_frames = []
    for i in range(50):
        frame = np.random.randint(0, 255, (720, 1280, 3), dtype=np.uint8)
        # Add some visual content
        cv2.rectangle(frame, (100, 100), (400, 300), (0, 255, 0), 2)
        cv2.putText(frame, f"Frame {i}", (50, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
        sample_frames.append(frame)

    full_frame = sample_frames[25]  # Use middle frame as best frame

    # Define bounding boxes
    vehicle_bbox = (100, 100, 400, 300)
    plate_bbox = (150, 200, 250, 250)

    print("2. Saving violation evidence...")
    try:
        result = save_violation_evidence(
            frames=sample_frames,
            fps=10,
            full_frame=full_frame,
            vehicle_bbox=vehicle_bbox,
            plate_bbox=plate_bbox,
            plate_number="30A-12345",
            timestamp=time.time(),
            base_dir="test_violations"
        )

        print("\n[SUCCESS] Files saved:")
        print(f"  Vehicle image: {result['vehicle_image']}")
        print(f"  Plate image:   {result['plate_image']}")
        print(f"  Video:         {result['video']}")
        print(f"  Folder:        {result['folder']}")

        # Verify files exist
        for key in ['vehicle_image', 'plate_image', 'video']:
            path = Path(result[key])
            if path.exists():
                size = path.stat().st_size
                print(f"  [OK] {key}: {size:,} bytes")
            else:
                print(f"  [FAIL] {key}: NOT FOUND")

    except Exception as e:
        print(f"\n[ERROR] {e}")
        import traceback
        traceback.print_exc()
