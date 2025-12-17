# combined_detector.py
"""
Combined Vehicle + Plate Detector using YOLOv11 Segmentation
Detects vehicles with SEGMENTATION for pixel-perfect bboxes, tracks them, and recognizes license plates
"""
import cv2
import numpy as np
from collections import defaultdict

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
    try:
        from byte_tracker import BYTETracker
        BYTETRACK_AVAILABLE = True
    except:
        BYTETRACK_AVAILABLE = False


class CombinedDetector:
    def __init__(self, yolo_model='yolo11n-seg.pt', device=None):
        """
        Khởi tạo detector với SEGMENTATION support
        - Vehicle detection: YOLO Segmentation (pixel-perfect bboxes)
        - Tracking: OC-SORT hoặc ByteTrack (mượt)
        - Plate reading: Fast-ALPR (chỉ chạy khi có xe)

        Args:
            yolo_model: Path to YOLO segmentation model (yolo11n-seg.pt)
            device: 'cuda', 'mps', or 'cpu'
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

        if device == 'cpu':
            print("⚠️  WARNING: Running on CPU (SLOW performance!)")

        if not YOLO_AVAILABLE:
            raise ImportError("YOLO is not available. Please install: pip install ultralytics")

        # ============================================
        # 1. VEHICLE DETECTION (YOLO SEGMENTATION)
        # ============================================
        print(f">>> Loading YOLO SEGMENTATION model: {yolo_model}")
        try:
            self.yolo = YOLO(yolo_model)
            self.device = device

            # Verify segmentation support
            self.is_segmentation = 'seg' in yolo_model.lower()
            if self.is_segmentation:
                print("✅ SEGMENTATION MODE: Pixel-perfect bboxes enabled!")
            else:
                print("⚠️  DETECTION MODE: Using standard bboxes (consider yolo11n-seg.pt)")

        except Exception as e:
            print(f"❌ YOLO model loading failed: {e}")
            raise

        # Các class ID của xe trong COCO dataset
        self.vehicle_classes = {
            2: 'car',
            3: 'motorcycle',
            5: 'bus',
            7: 'truck'
        }

        # ============================================
        # 2. TRACKING - OC-SORT hoặc ByteTrack
        # ============================================
        if OCSORT_AVAILABLE:
            print(">>> Loading OC-SORT (smooth tracking)...")
            try:
                self.tracker = OCSort(det_thresh=0.25, iou_threshold=0.3, use_byte=False)
                self.tracker_type = 'ocsort'
                print("✅ OC-SORT tracker initialized")
            except Exception as e:
                print(f"⚠️  OC-SORT init failed: {e}, trying ByteTrack...")
                self.tracker = None
                self.tracker_type = None
        else:
            self.tracker = None
            self.tracker_type = None

        # ============================================
        # 3. PLATE DETECTOR (Fast-ALPR)
        # ============================================
        if PLATE_DETECTOR_AVAILABLE:
            print(">>> Loading Plate Detector (Fast-ALPR)...")
            try:
                self.plate_detector = PlateDetector()
                print("✅ Plate detector initialized")
            except Exception as e:
                print(f"⚠️  Plate detector init failed: {e}")
                self.plate_detector = None
        else:
            self.plate_detector = None
            print("⚠️  Plate detector not available")

        print("=" * 60)
        print("🎯 CombinedDetector initialized successfully!")
        print(f"   - Model: {yolo_model}")
        print(f"   - Device: {device}")
        print(f"   - Segmentation: {self.is_segmentation}")
        print(f"   - Tracker: {self.tracker_type or 'YOLO built-in'}")
        print(f"   - Plate detector: {'✅' if self.plate_detector else '❌'}")
        print("=" * 60)

    def extract_bbox_from_mask(self, mask, original_bbox=None, min_area=100):
        """
        Extract tight bounding box from segmentation mask

        Args:
            mask: Binary mask array (H, W)
            original_bbox: Original YOLO bbox (x1, y1, x2, y2) as fallback
            min_area: Minimum contour area to consider

        Returns:
            bbox: (x1, y1, x2, y2) extracted from mask
            centroid: (cx, cy) center of mass from mask
        """
        try:
            # Find contours in mask
            contours, _ = cv2.findContours(
                mask.astype(np.uint8),
                cv2.RETR_EXTERNAL,
                cv2.CHAIN_APPROX_SIMPLE
            )

            if not contours:
                if original_bbox is not None:
                    x1, y1, x2, y2 = original_bbox
                    cx = (x1 + x2) / 2
                    cy = (y1 + y2) / 2
                    return original_bbox, (cx, cy)
                return None, None

            # Find largest contour by area
            largest_contour = max(contours, key=cv2.contourArea)
            area = cv2.contourArea(largest_contour)

            if area < min_area:
                if original_bbox is not None:
                    x1, y1, x2, y2 = original_bbox
                    cx = (x1 + x2) / 2
                    cy = (y1 + y2) / 2
                    return original_bbox, (cx, cy)
                return None, None

            # Get bounding rect from contour (tight fit)
            x, y, w, h = cv2.boundingRect(largest_contour)
            tight_bbox = (x, y, x + w, y + h)

            # Calculate centroid (center of mass)
            M = cv2.moments(largest_contour)
            if M['m00'] != 0:
                cx = int(M['m10'] / M['m00'])
                cy = int(M['m01'] / M['m00'])
            else:
                cx = x + w // 2
                cy = y + h // 2

            centroid = (cx, cy)

            return tight_bbox, centroid

        except Exception as e:
            if original_bbox is not None:
                x1, y1, x2, y2 = original_bbox
                cx = (x1 + x2) / 2
                cy = (y1 + y2) / 2
                return original_bbox, (cx, cy)
            return None, None

    def detect(self, frame, enable_plate_detection=False, enable_tracking=True):
        """
        Detect vehicles with SEGMENTATION and optionally plates

        Args:
            frame: Input frame (BGR)
            enable_plate_detection: Whether to detect plates
            enable_tracking: Whether to enable tracking

        Returns:
            List of detections:
            {
                'track_id': int,
                'vehicle_class': str,
                'vehicle_bbox': (x1, y1, x2, y2),  # TIGHT from mask
                'vehicle_centroid': (cx, cy),       # Center of mass
                'confidence': float,
                'mask': np.array or None,           # Segmentation mask
                'plate': str or None,
                'plate_bbox': (x1, y1, x2, y2) or None,
                'plate_confidence': float or None
            }
        """
        if frame is None or frame.size == 0:
            return []

        detections = []

        try:
            # Run vehicle detection
            results = self.yolo.track(
                frame,
                persist=True,
                conf=0.25,
                classes=list(self.vehicle_classes.keys()),
                verbose=False,
                device=self.device,
                retina_masks=True if self.is_segmentation else False
            )

            if not results or len(results) == 0:
                return []

            result = results[0]

            if result.boxes is None or len(result.boxes) == 0:
                return []

            # Check if we have masks (segmentation)
            has_masks = hasattr(result, 'masks') and result.masks is not None and self.is_segmentation

            # Process each detection
            for idx in range(len(result.boxes)):
                box = result.boxes[idx]

                # Get class
                cls_id = int(box.cls[0])
                if cls_id not in self.vehicle_classes:
                    continue

                vehicle_class = self.vehicle_classes[cls_id]
                confidence = float(box.conf[0])

                # Get original bbox from YOLO
                x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
                original_bbox = (int(x1), int(y1), int(x2), int(y2))

                # Get track ID
                if hasattr(box, 'id') and box.id is not None:
                    track_id = int(box.id[0])
                else:
                    track_id = idx

                # Extract mask and get tight bbox + centroid
                mask = None
                tight_bbox = original_bbox
                centroid = ((x1 + x2) / 2, (y1 + y2) / 2)

                if has_masks and idx < len(result.masks):
                    try:
                        # Get mask
                        mask_data = result.masks[idx]

                        if hasattr(mask_data, 'data'):
                            mask = mask_data.data[0].cpu().numpy()
                        else:
                            mask = mask_data.cpu().numpy()

                        # Resize mask to frame size
                        if mask.shape[0] != frame.shape[0] or mask.shape[1] != frame.shape[1]:
                            mask = cv2.resize(
                                mask,
                                (frame.shape[1], frame.shape[0]),
                                interpolation=cv2.INTER_LINEAR
                            )

                        # Threshold to binary
                        mask = (mask > 0.5).astype(np.uint8)

                        # Extract tight bbox from mask
                        extracted_bbox, extracted_centroid = self.extract_bbox_from_mask(
                            mask,
                            original_bbox
                        )

                        if extracted_bbox is not None:
                            tight_bbox = extracted_bbox
                            centroid = extracted_centroid

                    except Exception as e:
                        # Fallback to original bbox
                        mask = None
                        tight_bbox = original_bbox

                # Create detection dict
                detection = {
                    'track_id': track_id,
                    'vehicle_class': vehicle_class,
                    'vehicle_bbox': tight_bbox,
                    'vehicle_centroid': centroid,
                    'confidence': confidence,
                    'mask': mask,
                    'plate': None,
                    'plate_bbox': None,
                    'plate_confidence': None
                }

                # Detect plate if enabled
                if enable_plate_detection and self.plate_detector is not None:
                    vx1, vy1, vx2, vy2 = tight_bbox

                    h, w = frame.shape[:2]
                    vx1 = max(0, vx1)
                    vy1 = max(0, vy1)
                    vx2 = min(w, vx2)
                    vy2 = min(h, vy2)

                    if vx2 > vx1 and vy2 > vy1:
                        vehicle_crop = frame[vy1:vy2, vx1:vx2]

                        try:
                            plate_results = self.plate_detector.detect(vehicle_crop)

                            if plate_results and len(plate_results) > 0:
                                best_plate = max(plate_results, key=lambda p: p.get('confidence', 0))

                                plate_bbox_crop = best_plate.get('bbox')
                                if plate_bbox_crop:
                                    px1, py1, px2, py2 = plate_bbox_crop

                                    plate_bbox = (
                                        int(vx1 + px1),
                                        int(vy1 + py1),
                                        int(vx1 + px2),
                                        int(vy1 + py2)
                                    )

                                    detection['plate_bbox'] = plate_bbox
                                    detection['plate_confidence'] = best_plate.get('confidence', 0)
                                    detection['plate'] = best_plate.get('text', '')
                        except Exception as e:
                            pass

                detections.append(detection)

            return detections

        except Exception as e:
            print(f"[DETECTOR] ❌ Detection error: {e}")
            import traceback
            traceback.print_exc()
            return []

    def draw_detections(self, frame, detection, speed=None, speed_limit=40,
                       draw_mask=False, mask_alpha=0.3):
        """
        Draw detection on frame with optional mask overlay
        """
        try:
            vehicle_bbox = detection.get('vehicle_bbox')
            vehicle_class = detection.get('vehicle_class', 'vehicle')
            track_id = detection.get('track_id', 0)
            mask = detection.get('mask')
            centroid = detection.get('vehicle_centroid')

            if vehicle_bbox is None:
                return frame

            x1, y1, x2, y2 = vehicle_bbox

            # Color based on speed
            if speed is not None and speed > speed_limit:
                color = (0, 0, 255)  # Red
            else:
                color = (0, 255, 0)  # Green

            # Draw mask overlay if enabled
            if draw_mask and mask is not None:
                try:
                    mask_overlay = np.zeros_like(frame)
                    mask_overlay[mask > 0] = color
                    cv2.addWeighted(frame, 1.0, mask_overlay, mask_alpha, 0, frame)

                    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                    cv2.drawContours(frame, contours, -1, color, 2)
                except:
                    pass

            # Validate bbox
            h, w = frame.shape[:2]
            x1 = max(0, min(x1, w - 1))
            y1 = max(0, min(y1, h - 1))
            x2 = max(x1 + 1, min(x2, w))
            y2 = max(y1 + 1, min(y2, h))

            if x2 <= x1 or y2 <= y1:
                return frame

            # Draw bbox
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 1)

            # Draw centroid
            if centroid is not None:
                cx, cy = centroid
                cv2.circle(frame, (int(cx), int(cy)), 3, color, -1)

            # Draw speed label
            if speed is not None:
                label = f"{speed:.1f} km/h"

                font = cv2.FONT_HERSHEY_SIMPLEX
                font_scale = 0.4
                thickness_text = 1
                (text_width, text_height), baseline = cv2.getTextSize(
                    label, font, font_scale, thickness_text
                )

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

            return frame

        except Exception as e:
            return frame
