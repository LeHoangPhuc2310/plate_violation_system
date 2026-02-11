import os
import cv2
import shutil
import threading
from datetime import datetime
import json
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from alpr.plate_validation_state import (
    PlateValidationState,
    PlateValidator as StateValidator,
    PlateResolutionStatus,
    PlateResolutionDecider,
    PlateImageValidator
)
from alpr.plate_format_validator import PlateFormatValidator
from utils.logger import get_logger

logger = get_logger(__name__)


class ViolationHandler:

    def __init__(self, speed_limit, save_dir='uploads/violations', 
                 cooldown_seconds=5.0, video_duration_seconds=4.0,
                 video_before_seconds=1.5, video_after_seconds=2.5):
        self.speed_limit = speed_limit
        self.save_dir = save_dir
        self.cooldown_seconds = cooldown_seconds
        self.video_duration_seconds = video_duration_seconds
        self.video_before_seconds = video_before_seconds
        self.video_after_seconds = video_after_seconds

        self.violated_tracks = set()
        self._lock = threading.Lock()

        self.recent_violations = []  # [(track_id, bbox, timestamp, speed)]
        self.recent_violations_by_plate = {}  # {plate_text: [(timestamp, track_id)]}
        self._iou_threshold = 0.5
        self._time_window = cooldown_seconds
        self._plate_cooldown_seconds = 30.0  # Cooldown dài hơn cho cùng một biển số

        os.makedirs(save_dir, exist_ok=True)
        logger.info(f"Handler initialized, limit={speed_limit} km/h, cooldown={cooldown_seconds}s, plate_cooldown={self._plate_cooldown_seconds}s")
        logger.info(f"Vehicles with speed > {speed_limit} km/h will be flagged as violations")

    def check_violation(self, track_id, speed, bbox=None):
        """
        Kiểm tra vi phạm tốc độ với strict validation.
        - Reject nếu track_id đã vi phạm
        - Reject nếu speed invalid
        - Reject nếu bbox duplicate (IoU)
        """
        # Validate speed first
        if speed is None or speed <= 0:
            logger.warning(f"Track {track_id}: Invalid speed ({speed}), skipping")
            return False

        if speed <= self.speed_limit:
            # Log để debug - chỉ log khi gần ngưỡng
            if speed > self.speed_limit * 0.9:  # Chỉ log khi > 90% speed limit
                logger.debug(f"Track {track_id}: Speed {speed:.1f} km/h <= limit {self.speed_limit} km/h, no violation")
            return False
            
        # Reject unrealistic speeds
        if speed > 200.0:
            logger.warning(f"Track {track_id}: Unrealistic speed {speed:.1f} km/h, skipping")
            return False

        import time
        current_time = time.time()

        with self._lock:
            # Check 1 - Track ID đã vi phạm chưa (STRICT - 1 track = 1 violation MAX)
            if track_id in self.violated_tracks:
                logger.debug(f"Track {track_id}: Already violated, skipping")
                return False

            # Check 2 - Duplicate theo bbox (IoU) trong time_window
            if bbox is not None:
                # Clean old violations
                self.recent_violations = [
                    (tid, vbbox, vtime, vspeed) for tid, vbbox, vtime, vspeed in self.recent_violations
                    if current_time - vtime < self._time_window
                ]

                # Check IoU with recent violations
                for _, recent_bbox, _, _ in self.recent_violations:
                    iou = self._calculate_iou(bbox, recent_bbox)
                    if iou > self._iou_threshold:
                        logger.debug(f"Track {track_id}: DUPLICATE detected by bbox (IoU={iou:.2f}), skipping")
                        # Mark as violated to prevent future checks
                        self.violated_tracks.add(track_id)
                        return False

                # Add to recent violations
                self.recent_violations.append((track_id, bbox, current_time, speed))

            # Mark as violated IMMEDIATELY to prevent race conditions
            self.violated_tracks.add(track_id)
            logger.info(f"Track {track_id}: VALID violation at {speed:.1f} km/h")

        return True

    def _calculate_iou(self, bbox1, bbox2):
        x1 = max(bbox1[0], bbox2[0])
        y1 = max(bbox1[1], bbox2[1])
        x2 = min(bbox1[2], bbox2[2])
        y2 = min(bbox1[3], bbox2[3])

        intersection = max(0, x2 - x1) * max(0, y2 - y1)

        area1 = (bbox1[2] - bbox1[0]) * (bbox1[3] - bbox1[1])
        area2 = (bbox2[2] - bbox2[0]) * (bbox2[3] - bbox2[1])

        union = area1 + area2 - intersection

        if union <= 0:
            return 0.0

        return intersection / union

    def save_violation(self, raw_frame, track_id, speed, plate_info, vehicle_bbox=None,
                      frame_buffer=None, violation_frame_number=None, fps=30.0):
        """
        Save a speed violation to disk and prepare for database.

        Nguyên tắc:
        1. ALWAYS save the violation (speed detection is independent of plate reading)
        2. Plate resolution uses PlateResolutionDecider for consistent decisions
        3. Never force OCR text when confidence/quality is insufficient
        4. Saving incorrect plate is WORSE than saving NULL
        """
        now = datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        timestamp_str = now.strftime("%Y%m%d_%H%M%S_%f")[:-3]

        # Extract plate info from input
        raw_plate_text = plate_info.get('plate_text', '') if plate_info else ''
        plate_image = plate_info.get('plate_image') if plate_info else None
        confidence = plate_info.get('confidence', 0.0) if plate_info else 0.0
        input_sharpness = plate_info.get('sharpness', 0.0) if plate_info else 0.0

        # Calculate sharpness from plate_image if not provided
        if input_sharpness <= 0.0 and plate_image is not None:
            input_sharpness = PlateImageValidator.calculate_sharpness(plate_image)

        # Store original OCR text before any processing
        original_ocr_text = raw_plate_text if raw_plate_text and raw_plate_text.upper() not in ['UNKNOWN', 'N/A', ''] else None

        # Step 1: Validate plate format (if we have text)
        format_is_valid = False
        normalized_plate = None
        format_validation_reason = None
        ocr_corrections = []

        if raw_plate_text and raw_plate_text.upper() not in ['UNKNOWN', 'N/A', '']:
            is_valid, normalized_plate, reason = PlateFormatValidator.validate(raw_plate_text)
            format_is_valid = is_valid
            format_validation_reason = reason

            if is_valid and normalized_plate:
                # Check if OCR was corrected (e.g., O→0, I→1)
                if raw_plate_text != normalized_plate and 'Corrected' in reason:
                    ocr_corrections.append({
                        'original': raw_plate_text,
                        'corrected': normalized_plate,
                        'reason': reason
                    })
                    logger.debug(f"OCR corrected: '{raw_plate_text}' → '{normalized_plate}'")
            else:
                # Invalid format - get analysis for suggestions
                analysis = PlateFormatValidator.analyze_invalid_plate(raw_plate_text)
                if analysis.get('suggestions'):
                    ocr_corrections = analysis['suggestions']
                logger.warning(f"Invalid format: '{raw_plate_text}' | {reason}")

        # Step 2: Use PlateResolutionDecider for decision
        plate_to_validate = normalized_plate if format_is_valid else raw_plate_text
        resolution = PlateResolutionDecider.decide(
            plate_text=plate_to_validate,
            plate_image=plate_image,
            confidence=confidence,
            sharpness=input_sharpness,
            format_is_valid=format_is_valid
        )

        # Step 3: Extract decision results
        resolution_status = resolution['status']
        plate_text_to_save = resolution['plate_text_to_save']
        manual_review_required = resolution['manual_review_required']
        ocr_suggestions = resolution['ocr_suggestions']
        resolution_reason = resolution['reason']
        
        # Log resolution decision
        logger.debug(f"Resolution: status={resolution_status.value}, plate_to_save={plate_text_to_save}, reason={resolution_reason}")

        # Add any OCR corrections to suggestions
        if ocr_corrections:
            for correction in ocr_corrections:
                if isinstance(correction, dict) and 'corrected' in correction:
                    if correction['corrected'] not in ocr_suggestions:
                        ocr_suggestions.append(correction['corrected'])
                elif isinstance(correction, str) and correction not in ocr_suggestions:
                    ocr_suggestions.append(correction)

        # Step 4: Map resolution status to database fields
        # =====================================================
        # Quy tắc:
        # - AUTO_CONFIRMED: Save plate_text normally (high confidence)
        # - AUTO_SUGGESTED/MANUAL_REQUIRED: Save plate_text = NULL
        # - NEVER save guessed/low-confidence plates
        # - Saving incorrect plate is WORSE than saving NULL
        # =====================================================
        if resolution_status == PlateResolutionStatus.AUTO_CONFIRMED:
            plate_recognition_method = 'ocr_auto'
            plate_text = plate_text_to_save  # Save plate only when AUTO_CONFIRMED
            plate_status = 'AUTO_CONFIRMED'  # Set plate_status for filtering
            logger.info(f"AUTO_CONFIRMED: '{plate_text}' (conf={confidence:.2f}, sharp={input_sharpness:.1f})")
        elif resolution_status == PlateResolutionStatus.AUTO_SUGGESTED:
            plate_recognition_method = 'ocr_low_conf'
            plate_text = 'Biển số mờ'  # HIỂN THỊ "Biển số mờ" thay vì NULL
            plate_status = 'MANUAL_REQUIRED'  # AUTO_SUGGESTED requires manual review
            logger.warning(f"AUTO_SUGGESTED: plate='Biển số mờ' (conf={confidence:.2f} too low, sharp={input_sharpness:.1f})")
            logger.debug(f"Original OCR '{original_ocr_text}' saved to ocr_suggestions for manual review")
        else:  # MANUAL_REQUIRED
            plate_recognition_method = 'no_plate' if not raw_plate_text else 'ocr_low_conf'
            plate_text = 'Biển số mờ'  # HIỂN THỊ "Biển số mờ" thay vì NULL
            plate_status = 'MANUAL_REQUIRED'  # Set plate_status for filtering
            logger.warning(f"MANUAL_REQUIRED: plate='Biển số mờ' - {resolution_reason}")
            logger.debug(f"Original OCR '{original_ocr_text}' saved to ocr_suggestions for manual review")

        # Step 5: Build manual_review_notes JSON
        manual_review_notes = None
        if manual_review_required:
            notes_data = {
                'resolution_status': resolution_status.value,
                'resolution_reason': resolution_reason,
                'original_ocr': original_ocr_text,
                'ocr_suggestions': ocr_suggestions,
                'confidence': confidence,
                'sharpness': input_sharpness,
                'format_valid': format_is_valid
            }
            if ocr_corrections:
                notes_data['ocr_corrections'] = ocr_corrections
            manual_review_notes = json.dumps(notes_data, ensure_ascii=False)

        # Step 6: Determine validation_state for audit trail
        if plate_info:
            validation_state = plate_info.get('validation_state')
            if validation_state is None or not isinstance(validation_state, PlateValidationState):
                validation_state = StateValidator.determine_state(plate_text, plate_image)
            logger.debug(f"validation_state: {validation_state.value if validation_state else 'None'}")
        else:
            validation_state = PlateValidationState.NO_PLATE
            logger.warning("No plate_info → validation_state: NO_PLATE")

        # Tạo prefix cho tên file (bao gồm biển số hoặc TRACKXX_BIỂN SỐ MỜ)
        file_prefix = None
        if plate_text and plate_text not in [None, 'UNKNOWN', 'N/A', 'none', 'NONE', 'Biển quá mờ', 'Biển số mờ']:
            # Có biển số hợp lệ
            # Loại bỏ dấu gạch, khoảng trắng và ký tự đặc biệt để tên file hợp lệ
            file_prefix = plate_text.upper().replace('-', '').replace(' ', '').replace('.', '')
            # Loại bỏ ký tự không hợp lệ cho tên file
            import re
            file_prefix = re.sub(r'[<>:"/\\|?*]', '', file_prefix)
            folder_name = plate_text.upper()
            # Check duplicate theo biển số - nhưng CHỈ reject nếu cùng track_id
            # Nếu khác track_id (xe khác) → vẫn lưu (có thể có nhiều xe cùng biển số vi phạm)
            import time
            current_time = time.time()
            with self._lock:
                plate_text_upper = plate_text.upper()
                # Clean old violations by plate
                if plate_text_upper in self.recent_violations_by_plate:
                    self.recent_violations_by_plate[plate_text_upper] = [
                        (vtime, vid) for vtime, vid in self.recent_violations_by_plate[plate_text_upper]
                        if current_time - vtime < self._plate_cooldown_seconds
                    ]
                    # Chỉ reject nếu CÙNG track_id (cùng một xe vi phạm nhiều lần)
                    # Nếu khác track_id → cho phép (có thể là xe khác cùng biển số)
                    for vtime, vid in self.recent_violations_by_plate[plate_text_upper]:
                        if vid == track_id:  # Cùng track_id = cùng một xe
                            time_since_last = current_time - vtime
                            logger.debug(f"DUPLICATE: Track {track_id}, Plate '{plate_text_upper}' already violated {time_since_last:.1f}s ago (same vehicle) → SKIP saving")
                            return None

                # Mark plate as violated (chỉ cho track_id này)
                if plate_text_upper not in self.recent_violations_by_plate:
                    self.recent_violations_by_plate[plate_text_upper] = []
                self.recent_violations_by_plate[plate_text_upper].append((current_time, track_id))
                logger.debug(f"Track {track_id}, Plate '{plate_text_upper}': No duplicate (will save)")
        else:
            # Save with track_id as folder name for NULL/UNKNOWN/"Biển số mờ" plates
            # Tạo prefix: TRACKXX_BIỂN SỐ MỜ (chuyển dấu tiếng Việt thành không dấu cho tên file)
            # Giữ nguyên "BIỂN SỐ MỜ" vì hệ thống file Windows/Linux hiện đại hỗ trợ Unicode
            file_prefix = f"TRACK{track_id}_BIỂN SỐ MỜ"
            folder_name = f"TRACK_{track_id}_{timestamp_str}"
            # plate_text = "Biển số mờ" here (biển số quá mờ, không đoán bừa)

        violation_dir = os.path.join(self.save_dir, date_str, folder_name)
        
        # Kiểm tra và tạo thư mục
        try:
            os.makedirs(violation_dir, exist_ok=True)
            logger.debug(f"Directory created/verified: {violation_dir}")
            if not os.path.exists(violation_dir):
                logger.error(f"ERROR: Directory does not exist after creation: {violation_dir}")
        except Exception as e:
            logger.error(f"ERROR: Failed to create directory {violation_dir}: {e}", exc_info=True)
            import traceback
            traceback.print_exc()
        
        logger.debug(f"Preparing to save: Track {track_id}, Speed {speed:.1f} km/h, Plate '{plate_text}', Folder: {folder_name}")
        
        # Kiểm tra plate_image trước khi lưu
        if plate_image is None:
            logger.warning(f"WARNING: plate_image is None for Track {track_id}")
        else:
            if hasattr(plate_image, 'shape'):
                logger.debug(f"plate_image is valid numpy array: shape={plate_image.shape}, size={plate_image.size}, dtype={plate_image.dtype}")
            else:
                logger.warning(f"WARNING: plate_image is not numpy array: type={type(plate_image)}")
        
        # Kiểm tra raw_frame
        if raw_frame is None:
            logger.error(f"ERROR: raw_frame is None for Track {track_id}")
        else:
            if hasattr(raw_frame, 'shape'):
                logger.debug(f"raw_frame is valid: shape={raw_frame.shape}, size={raw_frame.size}")
            else:
                logger.warning(f"WARNING: raw_frame is not numpy array: type={type(raw_frame)}")

        result = {
            'track_id': track_id,
            'speed': speed,
            'speed_limit': self.speed_limit,
            'timestamp': now,
            'plate_text': plate_text,  # Can be NULL for AUTO_SUGGESTED and MANUAL_REQUIRED
            'vehicle_image': None,
            'plate_image': None,
            'video': None,
            'validation_state': validation_state.value if isinstance(validation_state, PlateValidationState) else 'no_plate',
            'sharpness': input_sharpness,
            'confidence': confidence,
            # Plate resolution fields (new design)
            'resolution_status': resolution_status.value,  # auto_confirmed, auto_suggested, manual_required
            'plate_status': plate_status,  # AUTO_CONFIRMED or MANUAL_REQUIRED (for filtering)
            'manual_review_required': manual_review_required,
            'manual_review_flag': manual_review_required,  # Alias for manual_review_required
            'manual_review_status': 'pending' if manual_review_required else None,
            'original_ocr_text': original_ocr_text,
            'ocr_confidence': confidence,
            'ocr_suggestions': json.dumps(ocr_suggestions) if ocr_suggestions else None,  # JSON array
            'plate_recognition_method': plate_recognition_method,
            'manual_review_notes': manual_review_notes,  # JSON with full analysis
            'violation_confirmed': True  # Default to TRUE, can be changed by human reviewer
        }

        # Crop vehicle image
        if vehicle_bbox is not None:
            x1, y1, x2, y2 = map(int, vehicle_bbox)
            h, w = raw_frame.shape[:2]
            pad = 15
            x1 = max(0, x1 - pad)
            y1 = max(0, y1 - pad)
            x2 = min(w, x2 + pad)
            y2 = min(h, y2 + pad)
            vehicle_crop = raw_frame[y1:y2, x1:x2].copy()
            logger.debug(f"Cropped vehicle from bbox: [{x1}, {y1}, {x2}, {y2}], crop_shape={vehicle_crop.shape}")
        else:
            vehicle_crop = raw_frame.copy()
            logger.debug(f"Using full frame as vehicle image: shape={vehicle_crop.shape}")

        # Tên file bao gồm biển số hoặc TRACKXX_BIỂN SỐ MỜ
        vehicle_filename = f"vehicle_{file_prefix}_{timestamp_str}.jpg"
        vehicle_path = os.path.join(violation_dir, vehicle_filename)
        
        # Kiểm tra vehicle_crop trước khi lưu
        if vehicle_crop is None:
            logger.error(f"ERROR: vehicle_crop is None for Track {track_id}")
        elif not hasattr(vehicle_crop, 'shape') or vehicle_crop.size == 0:
            logger.error(f"ERROR: vehicle_crop is invalid: type={type(vehicle_crop)}, size={getattr(vehicle_crop, 'size', 'N/A')}")
        else:
            logger.debug(f" Attempting to save vehicle image: {vehicle_path}, shape={vehicle_crop.shape}")

        success = cv2.imwrite(vehicle_path, vehicle_crop)
        if success:
            # QUAN TRỌNG: Normalize đường dẫn để dùng forward slash (cho web URL)
            # os.path.join() trên Windows sẽ dùng backslash, nhưng URL cần forward slash
            vehicle_image_path = os.path.join(date_str, folder_name, vehicle_filename)
            result['vehicle_image'] = vehicle_image_path.replace('\\', '/')  # Normalize path separator
            logger.debug(f"[OK] SAVED: Track {track_id} @ {speed:.1f}km/h -> {folder_name}/")
            logger.debug(f" Vehicle image saved: {vehicle_filename}")
            logger.debug(f" Vehicle image path (DB): {result['vehicle_image']}")
        else:
            logger.error(f"ERROR: Failed to save vehicle image to {vehicle_path}", exc_info=True)

        if plate_image is not None:
            # Tên file bao gồm biển số hoặc TRACKXX_BIỂN SỐ MỜ
            plate_filename = f"plate_{file_prefix}_{timestamp_str}.jpg"
            plate_path = os.path.join(violation_dir, plate_filename)
            
            # Kiểm tra plate_image chi tiết
            logger.debug("Checking plate_image before save:")
            logger.debug(f"Plate image details: Type={type(plate_image)}, Has shape={hasattr(plate_image, 'shape')}, Shape={plate_image.shape if hasattr(plate_image, 'shape') else 'N/A'}, Size={plate_image.size if hasattr(plate_image, 'size') else 'N/A'}, Dtype={plate_image.dtype if hasattr(plate_image, 'dtype') else 'N/A'}, Path={plate_path}")

            # Kiểm tra plate_image có valid không
            if hasattr(plate_image, 'shape') and plate_image.size > 0:
                logger.debug(f" plate_image is valid, attempting to save...")
                success = cv2.imwrite(plate_path, plate_image)
                if success:
                    # QUAN TRỌNG: Normalize đường dẫn để dùng forward slash (cho web URL)
                    plate_image_path = os.path.join(date_str, folder_name, plate_filename)
                    result['plate_image'] = plate_image_path.replace('\\', '/')  # Normalize path separator
                    logger.debug(f"[OK] Plate image saved successfully: {plate_filename}")
                    logger.debug(f" Plate image path (DB): {result['plate_image']}")
                    logger.debug(f" MATCHED PAIR - Vehicle: {vehicle_filename}, Plate: {plate_filename}")
                    
                    # Verify file exists
                    if os.path.exists(plate_path):
                        file_size = os.path.getsize(plate_path)
                        logger.debug(f" Verified: File exists, size={file_size} bytes")
                    else:
                        logger.error(f"ERROR: File does not exist after save: {plate_path}")
                else:
                    logger.error(f"ERROR: cv2.imwrite() returned False for plate image")
                    logger.debug(f"Path: {plate_path}, Directory exists: {os.path.exists(violation_dir)}")
                    logger.debug(f"Directory writable: {os.access(violation_dir, os.W_OK)}")
            else:
                logger.error(f"ERROR: Plate image is invalid (not numpy array or empty)")
                print(f"[VIOLATION]   - Has shape: {hasattr(plate_image, 'shape')}")
                if hasattr(plate_image, 'shape'):
                    print(f"[VIOLATION]   - Shape: {plate_image.shape}")
                    print(f"[VIOLATION]   - Size: {plate_image.size}")
        else:
            print(f"[VIOLATION] [WARN] No plate image to save (plate_image is None)")

        # Create violation video if frame buffer is available
        # Validate frame_buffer trước khi tạo video
        if frame_buffer and len(frame_buffer) > 0 and violation_frame_number is not None and fps > 0:
            try:
                # Tên file bao gồm biển số hoặc TRACKXX_BIỂN SỐ MỜ
                video_filename = f"video_{file_prefix}_{timestamp_str}.mp4"
                video_path = os.path.join(violation_dir, video_filename)
                
                print(f"[VIOLATION] 🎬 Creating violation video: {video_filename}")
                print(f"[VIOLATION] 📊 Frame buffer: {len(frame_buffer)} frames, violation_frame_number: {violation_frame_number}, fps: {fps:.1f}")
                
                # Validate frame_buffer structure
                valid_frames = 0
                for frame_data in frame_buffer:
                    if isinstance(frame_data, dict) and 'frame' in frame_data and frame_data['frame'] is not None:
                        valid_frames += 1
                
                if valid_frames == 0:
                    logger.error(f" Frame buffer contains no valid frames, skipping video creation")
                else:
                    logger.debug(f" Frame buffer validated: {valid_frames}/{len(frame_buffer)} valid frames")
                    
                    video_created_path = self.create_violation_video(
                        frame_buffer,
                        violation_frame_number,
                        fps,
                        video_path
                    )
                    
                    # create_violation_video trả về video_path nếu thành công, None nếu thất bại
                    if video_created_path and os.path.exists(video_created_path):
                        # Verify file size > 0
                        file_size = os.path.getsize(video_created_path)
                        if file_size > 0:
                            # QUAN TRỌNG: Normalize đường dẫn để dùng forward slash (cho web URL)
                            video_path_db = os.path.join(date_str, folder_name, video_filename)
                            result['video'] = video_path_db.replace('\\', '/')  # Normalize path separator
                            logger.debug(f"[OK] Video saved successfully: {video_filename} ({file_size/1024/1024:.2f} MB)")
                            logger.debug(f" Video path (DB): {result['video']}")
                        else:
                            logger.error(f" Video file created but empty (0 bytes)")
                    else:
                        logger.warning(f" Failed to create video (returned: {video_created_path})")
                        if video_created_path:
                            logger.warning(f" Video path exists: {os.path.exists(video_created_path)}")
            except Exception as e:
                logger.error(f" Error creating video: {e}")
                import traceback
                traceback.print_exc()
        else:
            if not frame_buffer:
                logger.warning(f" Frame buffer is None or empty, skipping video creation")
            elif violation_frame_number is None:
                logger.warning(f" violation_frame_number is None, skipping video creation")
            elif fps <= 0:
                logger.warning(f" Invalid fps ({fps}), skipping video creation")

        # Log kết quả cuối cùng
        print(f"[VIOLATION] [OK][OK] COMPLETED: Track {track_id}, Speed {speed:.1f} km/h, Plate '{plate_text}', Returning result (NOT None)")
        print(f"[VIOLATION] 📦 Result keys: {list(result.keys())}")
        return result

    def create_violation_video(self, frame_buffer, violation_frame_number, fps, output_path):
        """
        Tạo video vi phạm từ buffer frames
        Dùng frame_number để xử lý timeline, duplicate frames để fill gaps, encode theo source_fps thật
        
        Logic mới:
        1. Tìm violation frame dựa trên frame_number
        2. Tính timeline dựa trên frame_number (frame_number / source_fps = thời gian)
        3. Lấy frames trong khoảng thời gian (violation_time - before_seconds) đến (violation_time + after_seconds)
        4. Detect gaps trong frame_number và duplicate frames để fill
        5. Tính source_fps thật từ frame_number gaps
        6. Encode với source_fps thật (không speed-up)
        """
        if not frame_buffer or len(frame_buffer) == 0:
            print(f"[VIOLATION-VIDEO] [ERR] No frames in buffer to create video")
            return None

        try:
            # Bước 1: Validate FPS và extract frame data với frame_number
            if fps is None or fps <= 0:
                print(f"[VIOLATION-VIDEO] [WARN] Invalid FPS ({fps}), using default 30.0")
                fps = 30.0
            elif fps > 120:
                fps = 60.0
            elif fps < 5:
                fps = 15.0
            
            fps = round(fps, 2)
            source_fps = fps  # FPS từ video nguồn (giả định ban đầu)
            
            print(f"[VIOLATION-VIDEO] 📊 Initial source FPS (from video): {source_fps:.2f}")
            print(f"[VIOLATION-VIDEO] 📹 Creating video: {self.video_before_seconds}s before + {self.video_after_seconds}s after = {self.video_before_seconds + self.video_after_seconds:.1f}s total")
            
            # Bước 2: Extract và validate frames với frame_number
            valid_frames = []  # [(frame_number, frame, frame_data), ...]
            for i, frame_data in enumerate(frame_buffer):
                if not isinstance(frame_data, dict):
                    continue
                
                frame = frame_data.get('frame')
                if frame is None or not hasattr(frame, 'shape') or frame.size == 0:
                    continue
                
                frame_num = frame_data.get('frame_number')
                if frame_num is None:
                    # Nếu không có frame_number, skip (không thể xử lý timeline)
                    continue
                
                try:
                    frame_copy = frame.copy()
                    valid_frames.append((frame_num, frame_copy, frame_data))
                except Exception as e:
                    print(f"[VIOLATION-VIDEO] [WARN] Failed to copy frame {frame_num}: {e}")
                    continue
            
            if len(valid_frames) == 0:
                print(f"[VIOLATION-VIDEO] [ERR] No valid frames with frame_number in buffer")
                return None
            
            # Sort by frame_number
            valid_frames.sort(key=lambda x: x[0])
            frame_numbers = [f[0] for f in valid_frames]
            
            print(f"[VIOLATION-VIDEO] [OK] Valid frames: {len(valid_frames)} frames, frame_number range: {min(frame_numbers)} - {max(frame_numbers)}")
            
            # Bước 3: Tính source_fps thật từ frame_number gaps
            if len(frame_numbers) > 1:
                gaps = []
                for i in range(len(frame_numbers) - 1):
                    gap = frame_numbers[i + 1] - frame_numbers[i]
                    if gap > 0:  # Chỉ tính gaps hợp lệ
                        gaps.append(gap)
                
                if gaps:
                    avg_gap = sum(gaps) / len(gaps)
                    # Nếu avg_gap > 1, có nghĩa là frames bị skip
                    # Tính source_fps thật: nếu gap = 2, nghĩa là skip 1 frame → FPS thật = FPS giả định / 2
                    if avg_gap > 1.1:  # Có skip frames
                        # Tính FPS thật: nếu detection skip frames, FPS thật = FPS giả định / avg_gap
                        # Nhưng thực tế, nếu gap = 2, nghĩa là 2 frame_number = 1 frame thực tế
                        # → FPS thật = FPS giả định / avg_gap
                        calculated_fps = source_fps / avg_gap
                        print(f"[VIOLATION-VIDEO] [WARN] Frame gaps detected: avg_gap={avg_gap:.2f}")
                        print(f"[VIOLATION-VIDEO] 📊 Calculated source FPS: {calculated_fps:.2f} (from gaps)")
                        # Không dùng calculated_fps vì nó sẽ làm video chạy chậm
                        # Thay vào đó, giữ source_fps và duplicate frames để fill gaps
                    else:
                        print(f"[VIOLATION-VIDEO] [OK] No significant frame gaps (avg_gap={avg_gap:.2f})")
            
            # Bước 4: Tìm violation frame dựa trên frame_number
            violation_frame_data = None
            violation_idx = None
            for i, (frame_num, frame, frame_data) in enumerate(valid_frames):
                if frame_num == violation_frame_number:
                    violation_frame_data = (frame_num, frame, frame_data)
                    violation_idx = i
                    break
            
            if violation_frame_data is None:
                # Tìm frame gần nhất
                min_diff = float('inf')
                for i, (frame_num, frame, frame_data) in enumerate(valid_frames):
                    diff = abs(frame_num - violation_frame_number)
                    if diff < min_diff:
                        min_diff = diff
                        violation_frame_data = (frame_num, frame, frame_data)
                        violation_idx = i
                print(f"[VIOLATION-VIDEO] [WARN] Violation frame {violation_frame_number} not found, using closest: {violation_frame_data[0]} (diff={min_diff})")
            else:
                print(f"[VIOLATION-VIDEO] [OK] Found violation frame: {violation_frame_number}")
            
            violation_frame_num = violation_frame_data[0]
            
            # Bước 5: Tính timeline dựa trên frame_number
            # Timeline = frame_number / source_fps
            violation_time = violation_frame_num / source_fps
            start_time = violation_time - self.video_before_seconds
            end_time = violation_time + self.video_after_seconds
            
            print(f"[VIOLATION-VIDEO] ⏱️ Timeline: violation at {violation_time:.2f}s, range: {start_time:.2f}s - {end_time:.2f}s")
            
            # Bước 6: Lấy frames trong khoảng thời gian và duplicate để fill gaps
            selected_frames_timeline = []  # [(frame_number, frame, target_frame_number), ...]
            
            # Tính frame_number range
            start_frame_num = int(start_time * source_fps)
            end_frame_num = int(end_time * source_fps)
            
            print(f"[VIOLATION-VIDEO] 📊 Frame number range: {start_frame_num} - {end_frame_num} (need {end_frame_num - start_frame_num + 1} frames)")
            
            # Tạo timeline với tất cả frame_number cần thiết
            current_frame_num = start_frame_num
            frame_idx = 0  # Index trong valid_frames
            
            while current_frame_num <= end_frame_num:
                # Tìm frame gần nhất với current_frame_num
                best_frame = None
                best_frame_num = None
                best_diff = float('inf')
                
                # Tìm trong valid_frames từ frame_idx trở đi (optimize: frames đã sort)
                for i in range(frame_idx, len(valid_frames)):
                    frame_num, frame, frame_data = valid_frames[i]
                    diff = abs(frame_num - current_frame_num)
                    
                    if diff < best_diff:
                        best_diff = diff
                        best_frame = frame
                        best_frame_num = frame_num
                        frame_idx = i  # Update để tối ưu lần tìm sau
                    
                    # Nếu frame_num đã vượt quá current_frame_num nhiều, dừng
                    if frame_num > current_frame_num + 10:
                        break
                
                if best_frame is not None:
                    # Duplicate frame nếu cần (nếu gap > 1)
                    if best_frame_num != current_frame_num:
                        # Frame bị skip, duplicate frame gần nhất
                        selected_frames_timeline.append((current_frame_num, best_frame.copy(), best_frame_num))
                    else:
                        # Frame chính xác
                        selected_frames_timeline.append((current_frame_num, best_frame.copy(), best_frame_num))
                else:
                    # Không tìm thấy frame, duplicate frame cuối cùng
                    if len(selected_frames_timeline) > 0:
                        last_frame = selected_frames_timeline[-1][1]
                        selected_frames_timeline.append((current_frame_num, last_frame.copy(), None))
                    else:
                        # Không có frame nào, skip
                        print(f"[VIOLATION-VIDEO] [WARN] No frame found for frame_number {current_frame_num}, skipping")
                
                current_frame_num += 1
            
            if len(selected_frames_timeline) == 0:
                print(f"[VIOLATION-VIDEO] [ERR] No frames in timeline range")
                return None
            
            # Extract frames (chỉ lấy frame, bỏ frame_number)
            selected_frames = [f[1] for f in selected_frames_timeline]
            
            print(f"[VIOLATION-VIDEO] [OK] Selected {len(selected_frames)} frames (with duplicates to fill gaps)")
            print(f"[VIOLATION-VIDEO] 📊 Timeline: {len(selected_frames)} frames @ {source_fps:.2f} fps = {len(selected_frames) / source_fps:.2f}s")
            
            # Bước 7: Validate frame dimensions
            if len(selected_frames) == 0:
                print(f"[VIOLATION-VIDEO] [ERR] No frames to create video")
                return None
            
            first_frame = selected_frames[0]
            if not hasattr(first_frame, 'shape') or len(first_frame.shape) < 2:
                print(f"[VIOLATION-VIDEO] [ERR] Invalid first frame shape: {getattr(first_frame, 'shape', 'N/A')}")
                return None
            
            h, w = first_frame.shape[:2]
            if w <= 0 or h <= 0:
                print(f"[VIOLATION-VIDEO] [ERR] Invalid frame dimensions: {w}x{h}")
                return None
            
            print(f"[VIOLATION-VIDEO] 📐 Video resolution: {w}x{h}")
            
            # Resize frames nếu cần
            for i, frame in enumerate(selected_frames):
                if frame.shape[:2] != (h, w):
                    selected_frames[i] = cv2.resize(frame, (w, h))
            
            # Bước 8: Encode với source_fps thật (không speed-up)
            print(f"[VIOLATION-VIDEO] 🎬 Creating video with source FPS: {source_fps:.2f} (NO speed-up)")
            video_path = self._create_video_ffmpeg(selected_frames, source_fps, w, h, output_path)
            if video_path:
                file_size = os.path.getsize(video_path) if os.path.exists(video_path) else 0
                print(f"[VIOLATION-VIDEO] [OK][OK] Video created successfully: {output_path} ({file_size/1024/1024:.2f} MB)")
                print(f"[VIOLATION-VIDEO] [OK] Video duration: {len(selected_frames) / source_fps:.2f}s @ {source_fps:.2f} fps")
                return video_path
            
            # Fallback: OpenCV
            print(f"[VIOLATION-VIDEO] [WARN] FFmpeg failed, trying OpenCV fallback...")
            video_path = self._create_video_opencv(selected_frames, source_fps, w, h, output_path)
            if video_path:
                file_size = os.path.getsize(video_path) if os.path.exists(video_path) else 0
                print(f"[VIOLATION-VIDEO] [OK] Video created with OpenCV: {output_path} ({file_size/1024/1024:.2f} MB)")
            else:
                print(f"[VIOLATION-VIDEO] [ERR] Failed to create video with both FFmpeg and OpenCV")
            return video_path
            
        except Exception as e:
            print(f"[VIOLATION-VIDEO] [ERR] Error creating video: {e}")
            import traceback
            traceback.print_exc()
            return None

    def _create_video_ffmpeg(self, frames, fps, width, height, output_path):
        """Tạo video bằng FFmpeg (nhanh hơn, chất lượng tốt hơn)"""
        try:
            import subprocess
            import tempfile
            
            # Kiểm tra FFmpeg có sẵn không
            result = subprocess.run(['ffmpeg', '-version'], 
                                  capture_output=True, timeout=2)
            if result.returncode != 0:
                print(f"[VIOLATION-VIDEO] [WARN] FFmpeg not found or not accessible")
                return None
            
            # Tạo temp directory cho frames
            with tempfile.TemporaryDirectory() as temp_dir:
                # Lưu frames thành images
                frame_files = []
                for i, frame in enumerate(frames):
                    frame_path = os.path.join(temp_dir, f'frame_{i:06d}.jpg')
                    # Sử dụng JPEG quality 85 để cân bằng chất lượng và kích thước
                    success = cv2.imwrite(frame_path, frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
                    if success:
                        frame_files.append(frame_path)
                    else:
                        print(f"[VIOLATION-VIDEO] [WARN] Failed to save frame {i}")
                
                if not frame_files:
                    print(f"[VIOLATION-VIDEO] [ERR] No frames saved to temp directory")
                    return None
                
                print(f"[VIOLATION-VIDEO] 💾 Saved {len(frame_files)} frames to temp directory")
                
                # Tạo video bằng FFmpeg với FPS đúng - dùng filter để force FPS
                # Khi tạo video từ images, cách tốt nhất là:
                # 1. -framerate cho input: chỉ định tốc độ đọc frames từ images
                # 2. -filter:v "fps=fps" để FORCE output frame rate (quan trọng!)
                # 3. Dùng -vsync 0 để passthrough (không duplicate/skip frames)
                # 4. Dùng -pix_fmt yuv420p để tương thích với mọi player
                cmd = [
                    'ffmpeg', '-y',  # Overwrite output file
                    '-framerate', str(fps),  # Input frame rate (tốc độ đọc frames từ images)
                    '-i', os.path.join(temp_dir, 'frame_%06d.jpg'),
                    '-vf', f'fps={fps}',  # Force output frame rate bằng filter
                    '-c:v', 'libx264',  # H.264 codec
                    '-pix_fmt', 'yuv420p',  # Pixel format (compatible with most players)
                    '-crf', '23',  # Quality (18-28, lower = better quality)
                    '-preset', 'medium',  # Encoding speed (faster = larger file)
                    '-vsync', '0',  # Passthrough - không duplicate/skip frames
                    output_path
                ]
                
                print(f"[VIOLATION-VIDEO] 🎬 FFmpeg command: framerate={fps} (input), fps filter={fps} (output)")
                print(f"[VIOLATION-VIDEO] 📊 Expected video duration: {len(frame_files) / fps:.2f} seconds")
                print(f"[VIOLATION-VIDEO] 📊 Total frames: {len(frame_files)}, FPS: {fps:.2f}")
                
                # Tăng timeout và cải thiện error handling
                result = subprocess.run(cmd, capture_output=True, timeout=120, text=True)
                if result.returncode == 0:
                    # Wait a bit for file to be written
                    import time
                    time.sleep(0.5)
                    
                    if os.path.exists(output_path):
                        file_size = os.path.getsize(output_path)
                        if file_size > 0:
                            print(f"[VIOLATION-VIDEO] [OK] FFmpeg created video: {file_size/1024/1024:.2f} MB")
                            return output_path
                        else:
                            print(f"[VIOLATION-VIDEO] [ERR] Video file created but empty (0 bytes)")
                    else:
                        print(f"[VIOLATION-VIDEO] [ERR] Video file does not exist after FFmpeg execution")
                else:
                    error_msg = result.stderr if result.stderr else result.stdout if result.stdout else "Unknown error"
                    print(f"[VIOLATION-VIDEO] [ERR] FFmpeg failed (returncode={result.returncode})")
                    print(f"[VIOLATION-VIDEO] [ERR] Error: {error_msg[:500]}")
            
        except subprocess.TimeoutExpired:
            print(f"[VIOLATION-VIDEO] [ERR] FFmpeg timeout (>120s)")
        except FileNotFoundError:
            print(f"[VIOLATION-VIDEO] [ERR] FFmpeg not found in PATH")
        except Exception as e:
            print(f"[VIOLATION-VIDEO] [ERR] FFmpeg error: {e}")
            import traceback
            traceback.print_exc()
        
        return None

    def _create_video_opencv(self, frames, fps, width, height, output_path):
        """Tạo video bằng OpenCV (fallback khi FFmpeg không khả dụng)"""
        try:
            # Sử dụng codec 'mp4v' hoặc 'XVID' (tương thích tốt hơn)
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            out = cv2.VideoWriter(output_path, fourcc, fps, (width, height))
            
            if not out.isOpened():
                print(f"[VIOLATION-VIDEO] [ERR] Failed to open OpenCV video writer")
                # Thử codec khác
                fourcc = cv2.VideoWriter_fourcc(*'XVID')
                out = cv2.VideoWriter(output_path, fourcc, fps, (width, height))
                if not out.isOpened():
                    print(f"[VIOLATION-VIDEO] [ERR] Failed with both codecs")
                    return None
            
            print(f"[VIOLATION-VIDEO] 📝 Writing {len(frames)} frames with OpenCV...")
            frames_written = 0
            for i, frame in enumerate(frames):
                try:
                    # Validate frame
                    if frame is None or not hasattr(frame, 'shape'):
                        print(f"[VIOLATION-VIDEO] [WARN] Skipping invalid frame at index {i}")
                        continue
                    
                    # Resize nếu cần
                    if frame.shape[:2] != (height, width):
                        frame = cv2.resize(frame, (width, height))
                    
                    # Ensure frame is in correct format (BGR for OpenCV)
                    if len(frame.shape) == 2:
                        # Grayscale, convert to BGR
                        frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
                    elif len(frame.shape) == 3 and frame.shape[2] == 4:
                        # RGBA, convert to BGR
                        frame = cv2.cvtColor(frame, cv2.COLOR_RGBA2BGR)
                    elif len(frame.shape) == 3 and frame.shape[2] != 3:
                        print(f"[VIOLATION-VIDEO] [WARN] Unexpected frame channels: {frame.shape[2]}")
                        continue
                    
                    out.write(frame)
                    frames_written += 1
                except Exception as e:
                    print(f"[VIOLATION-VIDEO] [WARN] Error writing frame {i}: {e}")
                    continue
            
            out.release()
            
            if frames_written == 0:
                print(f"[VIOLATION-VIDEO] [ERR] No frames written to video")
                return None
            
            # Wait a bit for file to be written
            import time
            time.sleep(0.5)
            
            if os.path.exists(output_path):
                file_size = os.path.getsize(output_path)
                if file_size > 0:
                    print(f"[VIOLATION-VIDEO] [OK] OpenCV video created: {output_path} ({file_size/1024/1024:.2f} MB, {frames_written} frames)")
                    return output_path
                else:
                    print(f"[VIOLATION-VIDEO] [ERR] Video file created but empty (0 bytes)")
            else:
                print(f"[VIOLATION-VIDEO] [ERR] Video file not created")
            return None
                
        except Exception as e:
            print(f"[VIOLATION-VIDEO] [ERR] OpenCV video creation failed: {e}")
            import traceback
            traceback.print_exc()
            return None

    def reset(self):
        with self._lock:
            count = len(self.violated_tracks)
            plate_count = len(self.recent_violations_by_plate)
            self.violated_tracks.clear()
            self.recent_violations.clear()
            self.recent_violations_by_plate.clear()
        print(f"[VIOLATION] Reset {count} violated tracks and {plate_count} plate records")
