import cv2
import numpy as np
import threading
from .plate_validator import PlateValidator
from .plate_validation_state import PlateValidationState, PlateValidator as StateValidator, PlateImageValidator
from utils.logger import get_logger

logger = get_logger(__name__)


class PlateReader:

    def __init__(self, cuda_lock=None):
        self.cuda_lock = cuda_lock
        try:
            from fast_alpr import ALPR
            self.alpr = ALPR(
                detector_model="yolo-v9-t-512-license-plate-end2end",
                ocr_model="global-plates-mobile-vit-v2-model"
            )
            logger.info("FastALPR initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize: {e}", exc_info=True)
            self.alpr = None

    def detect_plate_region(self, frame, vehicle_bbox=None):
        if self.alpr is None:
            return None

        try:
            if vehicle_bbox is not None:
                x1, y1, x2, y2 = map(int, vehicle_bbox)
                h, w = frame.shape[:2]
                pad = 40
                x1 = max(0, x1 - pad)
                y1 = max(0, y1 - pad)
                x2 = min(w, x2 + pad)
                y2 = min(h, y2 + pad)
                crop = frame[y1:y2, x1:x2]
            else:
                crop = frame
                x1, y1 = 0, 0

            crop_h, crop_w = crop.shape[:2]
            MIN_WIDTH = 400
            if crop_w < MIN_WIDTH:
                scale = MIN_WIDTH / crop_w
                new_w = int(crop_w * scale)
                new_h = int(crop_h * scale)
                crop = cv2.resize(crop, (new_w, new_h), interpolation=cv2.INTER_CUBIC)

            if self.cuda_lock:
                with self.cuda_lock:
                    results = self.alpr.predict(crop)
            else:
                results = self.alpr.predict(crop)

            if not results:
                return None

            best_result = None
            best_ocr_text = None
            best_ocr_confidence = 0.0

            for result in results:
                det = result.detection
                if det is None or det.bounding_box is None:
                    continue

                ocr_text = None
                ocr_conf = 0.0

                if result.ocr and result.ocr.text:
                    raw_text = result.ocr.text
                    plate_text = raw_text.upper().replace(' ', '').replace('.', '').replace('-', '')
                    ocr_conf = result.ocr.confidence if result.ocr.confidence else 0.0

                    # Không đọc nếu confidence quá thấp - tránh đoán bừa khi biển số mờ
                    if ocr_conf < 0.75:
                        continue  # Skip this result entirely

                    is_valid, normalized = PlateValidator.validate(plate_text)
                    if not is_valid:
                        corrected = PlateValidator.correct_ocr_mistakes(plate_text)
                        is_valid, normalized = PlateValidator.validate(corrected)
                        if is_valid:
                            plate_text = normalized
                        else:
                            # Nếu vẫn invalid sau correction → SKIP
                            continue

                    ocr_text = normalized if is_valid else None
                    if ocr_text is None:
                        continue

                det_conf = getattr(det, 'confidence', 0.5) if det else 0.5
                score = det_conf + ocr_conf

                if best_result is None or score > (getattr(best_result.detection, 'confidence', 0) + best_ocr_confidence):
                    best_result = result
                    best_ocr_text = ocr_text
                    best_ocr_confidence = ocr_conf

            if best_result is None:
                return None

            det = best_result.detection

            if det and det.bounding_box:
                pb = det.bounding_box
                plate_bbox = [
                    int(pb.x1 + x1),
                    int(pb.y1 + y1),
                    int(pb.x2 + x1),
                    int(pb.y2 + y1)
                ]

                detector_confidence = getattr(det, 'confidence', 1.0) if det else 1.0

                px1, py1, px2, py2 = plate_bbox
                fh, fw = frame.shape[:2]

                px1 = max(0, px1)
                py1 = max(0, py1)
                px2 = min(fw, px2)
                py2 = min(fh, py2)

                if px2 > px1 and py2 > py1:
                    plate_image = frame[py1:py2, px1:px2].copy()
                    return {
                        'plate_image': plate_image,
                        'plate_bbox': plate_bbox,
                        'detector_confidence': detector_confidence,
                        'ocr_text': best_ocr_text,
                        'ocr_confidence': best_ocr_confidence
                    }

            return None

        except Exception as e:
            logger.error(f"Detection error: {e}", exc_info=True)
            return None

    def detect_plate_only(self, frame, vehicle_bbox=None):
        """
        CHỈ DETECT VÙNG BIỂN SỐ - KHÔNG CẦN OCR THÀNH CÔNG
        Luôn trả về plate_image nếu detect được vùng biển số, kể cả khi mờ
        """
        if self.alpr is None:
            return None

        try:
            if vehicle_bbox is not None:
                x1, y1, x2, y2 = map(int, vehicle_bbox)
                h, w = frame.shape[:2]
                pad = 40
                x1 = max(0, x1 - pad)
                y1 = max(0, y1 - pad)
                x2 = min(w, x2 + pad)
                y2 = min(h, y2 + pad)
                crop = frame[y1:y2, x1:x2]
            else:
                crop = frame
                x1, y1 = 0, 0

            crop_h, crop_w = crop.shape[:2]
            MIN_WIDTH = 400
            scale_factor = 1.0
            if crop_w < MIN_WIDTH:
                scale_factor = MIN_WIDTH / crop_w
                new_w = int(crop_w * scale_factor)
                new_h = int(crop_h * scale_factor)
                crop = cv2.resize(crop, (new_w, new_h), interpolation=cv2.INTER_CUBIC)

            if self.cuda_lock:
                with self.cuda_lock:
                    results = self.alpr.predict(crop)
            else:
                results = self.alpr.predict(crop)

            if not results:
                return None

            # TÌM DETECTION CÓ CONFIDENCE CAO NHẤT (KHÔNG CẦN OCR)
            best_detection = None
            best_det_conf = 0.0
            best_ocr_text = None
            best_ocr_conf = 0.0

            for result in results:
                det = result.detection
                if det is None or det.bounding_box is None:
                    continue

                det_conf = getattr(det, 'confidence', 0.5)
                
                # Lấy OCR text nếu có (không bắt buộc)
                ocr_text = None
                ocr_conf = 0.0
                if result.ocr and result.ocr.text:
                    raw_text = result.ocr.text
                    ocr_text = raw_text.upper().replace(' ', '').replace('.', '').replace('-', '')
                    ocr_conf = result.ocr.confidence if result.ocr.confidence else 0.0

                # Chọn detection có confidence cao nhất
                if det_conf > best_det_conf:
                    best_detection = det
                    best_det_conf = det_conf
                    best_ocr_text = ocr_text
                    best_ocr_conf = ocr_conf

            if best_detection is None:
                return None

            # Crop plate image từ detection
            pb = best_detection.bounding_box
            
            # Scale về frame gốc
            pb_x1 = int(pb.x1 / scale_factor) + x1
            pb_y1 = int(pb.y1 / scale_factor) + y1
            pb_x2 = int(pb.x2 / scale_factor) + x1
            pb_y2 = int(pb.y2 / scale_factor) + y1

            fh, fw = frame.shape[:2]
            pb_x1 = max(0, pb_x1)
            pb_y1 = max(0, pb_y1)
            pb_x2 = min(fw, pb_x2)
            pb_y2 = min(fh, pb_y2)

            if pb_x2 > pb_x1 + 10 and pb_y2 > pb_y1 + 5:
                plate_image = frame[pb_y1:pb_y2, pb_x1:pb_x2].copy()
                
                # Validate OCR nếu có
                validated_text = None
                if best_ocr_text and best_ocr_conf >= 0.75:
                    is_valid, normalized = PlateValidator.validate(best_ocr_text)
                    if not is_valid:
                        corrected = PlateValidator.correct_ocr_mistakes(best_ocr_text)
                        is_valid, normalized = PlateValidator.validate(corrected)
                    if is_valid:
                        validated_text = normalized
                
                logger.debug(f"Plate region detected: {pb_x2-pb_x1}x{pb_y2-pb_y1}, det_conf={best_det_conf:.2f}, ocr='{validated_text or 'N/A'}'")
                
                return {
                    'plate_image': plate_image,
                    'plate_bbox': [pb_x1, pb_y1, pb_x2, pb_y2],
                    'detector_confidence': best_det_conf,
                    'ocr_text': validated_text,  # Có thể là None nếu OCR fail
                    'ocr_confidence': best_ocr_conf if validated_text else 0.0
                }

            return None

        except Exception as e:
            logger.error(f"Detect plate only error: {e}", exc_info=True)
            return None

    def ocr_plate_image(self, plate_image):
        if self.alpr is None or plate_image is None:
            return None

        try:
            h, w = plate_image.shape[:2]
            MIN_WIDTH = 200
            if w < MIN_WIDTH:
                scale = MIN_WIDTH / w
                plate_image = cv2.resize(plate_image, (int(w * scale), int(h * scale)),
                                        interpolation=cv2.INTER_CUBIC)

            if self.cuda_lock:
                with self.cuda_lock:
                    results = self.alpr.predict(plate_image)
            else:
                results = self.alpr.predict(plate_image)

            if not results:
                return None

            best_text = None
            best_conf = 0.0

            for result in results:
                if not result.ocr or not result.ocr.text:
                    continue

                raw_text = result.ocr.text
                plate_text = raw_text.upper().replace(' ', '').replace('.', '').replace('-', '')
                confidence = result.ocr.confidence if result.ocr.confidence else 0.0

                # Tăng minimum confidence từ 0.4 → 0.75 để tránh đoán bừa khi biển số mờ
                if confidence >= 0.75:
                    is_valid, normalized = PlateValidator.validate(plate_text)
                    if not is_valid:
                        corrected = PlateValidator.correct_ocr_mistakes(plate_text)
                        is_valid, normalized = PlateValidator.validate(corrected)

                    # Chỉ chấp nhận nếu valid
                    if is_valid:
                        final_text = normalized
                        if confidence > best_conf:
                            best_text = final_text
                            best_conf = confidence

            if best_text:
                return {
                    'plate_text': best_text,
                    'confidence': best_conf
                }

            # Không trả về nếu không có kết quả hợp lệ
            return None

        except Exception as e:
            logger.error(f"OCR error: {e}", exc_info=True)
            return None

    def read_plate(self, frame, vehicle_bbox=None):
        if self.alpr is None:
            return None

        try:
            if vehicle_bbox is not None:
                x1, y1, x2, y2 = map(int, vehicle_bbox)
                h, w = frame.shape[:2]
                pad = 60
                x1 = max(0, x1 - pad)
                y1 = max(0, y1 - pad)
                x2 = min(w, x2 + pad)
                y2 = min(h, y2 + pad)
                crop = frame[y1:y2, x1:x2]
            else:
                crop = frame
                x1, y1 = 0, 0

            crop_h, crop_w = crop.shape[:2]
            MIN_WIDTH = 300
            scale_factor = 1.0  # Lưu scale factor
            original_crop_h, original_crop_w = crop_h, crop_w
            
            if crop_w < MIN_WIDTH:
                scale_factor = MIN_WIDTH / crop_w
                new_w = int(crop_w * scale_factor)
                new_h = int(crop_h * scale_factor)
                crop = cv2.resize(crop, (new_w, new_h), interpolation=cv2.INTER_CUBIC)
                crop_h, crop_w = crop.shape[:2]  # Update sau resize

            crops_to_try = [
                ("full", crop, 0),
                ("bottom50", crop[crop_h//2:, :] if crop_h > 50 else crop, crop_h//2),
                ("bottom40", crop[int(crop_h*0.6):, :] if crop_h > 50 else crop, int(crop_h*0.6)),
            ]

            best_result_obj = None
            best_text = None
            best_conf = 0.0
            best_crop_name = "full"
            crop_offset_y = 0
            all_results = []

            for crop_name, test_crop, offset_y in crops_to_try:
                if test_crop.size == 0:
                    continue

                try:
                    if self.cuda_lock:
                        with self.cuda_lock:
                            results = self.alpr.predict(test_crop)
                    else:
                        results = self.alpr.predict(test_crop)

                    if not results:
                        continue

                    all_results.extend(results)

                    for result in results:
                        if not result.ocr or not result.ocr.text:
                            continue

                        raw_text = result.ocr.text
                        confidence = result.ocr.confidence if result.ocr.confidence else 0.0

                        plate_text = raw_text.upper().replace(' ', '').replace('.', '').replace('-', '')

                        # Tăng minimum confidence từ 0.6 → 0.75 để tránh đoán bừa khi biển số mờ
                        if confidence >= 0.75:
                            is_valid, normalized = PlateValidator.validate(plate_text)
                            if not is_valid:
                                corrected = PlateValidator.correct_ocr_mistakes(plate_text)
                                is_valid, normalized = PlateValidator.validate(corrected)

                            # CHỈ chấp nhận nếu valid - KHÔNG chấp nhận text không hợp lệ dù confidence cao
                            if is_valid:
                                final_text = normalized if is_valid else plate_text
                                if confidence > best_conf:
                                    best_result_obj = result
                                    best_text = final_text
                                    best_conf = confidence
                                    best_crop_name = crop_name
                                    crop_offset_y = offset_y
                except Exception as e:
                    continue

            # Ưu tiên: VẪN crop plate_image kể cả khi OCR fail
            # → Để đảm bảo mọi vi phạm đều có ảnh biển số
            plate_text_result = None
            is_valid = False
            
            # Nếu có OCR result với confidence đủ cao
            if best_result_obj is not None and best_text and best_conf >= 0.80:
                # Validate biển số
                is_valid, normalized = PlateValidator.validate(best_text)
                if not is_valid:
                    corrected = PlateValidator.correct_ocr_mistakes(best_text)
                    is_valid, normalized = PlateValidator.validate(corrected)
                    if is_valid:
                        best_text = normalized
                
                if is_valid:
                    plate_text_result = normalized
                    logger.debug(f"Valid plate: '{plate_text_result}' (conf={best_conf:.2f})")
                else:
                    logger.warning(f"Invalid plate format: '{best_text}' (conf={best_conf:.2f}), keeping image but no text")
                    plate_text_result = None
            else:
                if best_text:
                    logger.warning(f"Confidence too low: {best_conf:.2f} < 0.80, keeping image but no text (biển số mờ)")
                else:
                    logger.warning("No OCR text found, will try to crop plate region")
            
            # QUAN TRỌNG: Vẫn cố gắng crop plate_image kể cả khi OCR fail
            # Sử dụng best_result_obj nếu có, hoặc tìm bất kỳ detection nào
            
            plate_image = None
            plate_bbox = None
            det = None
            
            # Nếu có best_result_obj, dùng detection của nó
            if best_result_obj is not None:
                det = best_result_obj.detection
            
            # Nếu không có best_result_obj, tìm bất kỳ detection nào từ all_results
            if det is None and all_results:
                for result in all_results:
                    if result.detection and result.detection.bounding_box:
                        det = result.detection
                        logger.warning("Using fallback detection from all_results (no valid OCR)")
                        break
            
            if det and det.bounding_box:
                pb = det.bounding_box
                # QUAN TRỌNG: Bounding box từ detection là trên crop đã resize
                # Cần scale về crop gốc (trước resize) trước khi tính về frame gốc
                pb_x1_scaled = pb.x1 / scale_factor
                pb_y1_scaled = pb.y1 / scale_factor
                pb_x2_scaled = pb.x2 / scale_factor
                pb_y2_scaled = pb.y2 / scale_factor
                
                # crop_offset_y là trên crop đã resize, cần scale về crop gốc
                crop_offset_y_original = crop_offset_y / scale_factor
                
                # Tính về frame gốc
                plate_bbox = [
                    int(pb_x1_scaled) + x1,
                    int(pb_y1_scaled) + y1 + int(crop_offset_y_original),
                    int(pb_x2_scaled) + x1,
                    int(pb_y2_scaled) + y1 + int(crop_offset_y_original)
                ]

                px1, py1, px2, py2 = map(int, plate_bbox)
                fh, fw = frame.shape[:2]
                px1, py1 = max(0, px1), max(0, py1)
                px2, py2 = min(fw, px2), min(fh, py2)

                # Đảm bảo có kích thước tối thiểu
                if px2 > px1 and py2 > py1 and (px2 - px1) >= 10 and (py2 - py1) >= 10:
                    plate_image = frame[py1:py2, px1:px2].copy()
                    logger.debug(f"Plate image cropped: {px2-px1}x{py2-py1} from bbox [{px1},{py1},{px2},{py2}] (scale={scale_factor:.2f})")
                else:
                    logger.warning(f"Invalid plate bbox: [{px1},{py1},{px2},{py2}], size: {px2-px1}x{py2-py1}")
            
            # QUAN TRỌNG: Nếu không có plate_image, thử crop từ detection bbox trong crop image (đã resize)
            if plate_image is None and det and det.bounding_box:
                try:
                    pb = det.bounding_box
                    # Bounding box từ detection là trên crop đã resize, dùng trực tiếp
                    crop_px1 = max(0, int(pb.x1))
                    crop_py1 = max(0, int(pb.y1) + crop_offset_y)
                    crop_px2 = int(pb.x2)
                    crop_py2 = int(pb.y2) + crop_offset_y
                    
                    # Đảm bảo trong bounds của crop (đã resize)
                    crop_h_resized, crop_w_resized = crop.shape[:2]
                    crop_px1 = max(0, min(crop_px1, crop_w_resized - 10))
                    crop_py1 = max(0, min(crop_py1, crop_h_resized - 10))
                    crop_px2 = max(crop_px1 + 10, min(crop_px2, crop_w_resized))
                    crop_py2 = max(crop_py1 + 10, min(crop_py2, crop_h_resized))
                    
                    if crop_px2 > crop_px1 and crop_py2 > crop_py1:
                        # Crop từ crop image (đã resize)
                        plate_crop = crop[crop_py1:crop_py2, crop_px1:crop_px2].copy()
                        if plate_crop.size > 0 and plate_crop.shape[0] >= 10 and plate_crop.shape[1] >= 10:
                            plate_image = plate_crop
                            logger.debug(f"Got plate_image from resized crop: {crop_px2-crop_px1}x{crop_py2-crop_py1}")
                except Exception as e:
                    logger.error(f"Error cropping plate from detection: {e}", exc_info=True)

            # Log detection info
            logger.debug(f"Found detection: text='{plate_text_result}', conf={best_conf:.2f}, crop={best_crop_name}, plate_img={'YES' if plate_image is not None else 'NO'}")

            # NẾU KHÔNG CÓ PLATE IMAGE TỪ DETECTION → THỬ CROP TỪ VEHICLE BBOX
            if plate_image is None and vehicle_bbox is not None:
                logger.warning("No plate detection → Trying to crop plate region from vehicle bbox (bottom 30%)")
                try:
                    vx1, vy1, vx2, vy2 = map(int, vehicle_bbox)
                    vh = vy2 - vy1
                    vw = vx2 - vx1
                    # Crop phần dưới 30% của vehicle (thường là vị trí biển số)
                    plate_y1 = vy1 + int(vh * 0.65)  # Bottom 35%
                    plate_y2 = vy2
                    plate_x1 = vx1 + int(vw * 0.15)  # Center 70%
                    plate_x2 = vx2 - int(vw * 0.15)
                    
                    fh, fw = frame.shape[:2]
                    plate_x1, plate_y1 = max(0, plate_x1), max(0, plate_y1)
                    plate_x2, plate_y2 = min(fw, plate_x2), min(fh, plate_y2)
                    
                    if plate_x2 > plate_x1 + 20 and plate_y2 > plate_y1 + 10:
                        plate_image = frame[plate_y1:plate_y2, plate_x1:plate_x2].copy()
                        plate_bbox = [plate_x1, plate_y1, plate_x2, plate_y2]
                        logger.debug(f"Cropped estimated plate region: {plate_x2-plate_x1}x{plate_y2-plate_y1}")
                except Exception as e:
                    logger.error(f"Error cropping from vehicle bbox: {e}", exc_info=True)

            # QUAN TRỌNG: Vẫn trả về kết quả kể cả khi chỉ có plate_image mà không có text
            # Để đảm bảo MỌI vi phạm đều có ảnh biển số (dù mờ)
            if plate_image is None:
                logger.error("No plate_image at all → Cannot save violation evidence")
                return None

            # Validate image quality (sharpness, size, aspect ratio)
            is_valid_image, reason, sharpness = PlateImageValidator.validate_plate_image(plate_image)

            # Determine validation state
            text_is_valid = plate_text_result is not None
            validation_state = StateValidator.determine_state(plate_text_result, plate_image, text_is_valid=text_is_valid)

            if not is_valid_image:
                logger.warning(f"Plate image quality issue: {reason} - Still returning with state={validation_state.value}")
                # Return anyway - let ViolationHandler decide
                if plate_text_result is None:
                    validation_state = PlateValidationState.UNREADABLE
            
            if plate_text_result:
                logger.debug(f"Valid plate: '{plate_text_result}' (conf={best_conf:.2f}, sharpness={sharpness:.1f}, state={validation_state.value})")
            else:
                logger.warning(f"Plate image saved but TEXT='Biển số mờ' (no valid OCR, sharpness={sharpness:.1f})")

            return {
                'plate_text': plate_text_result,  # Có thể là None nếu OCR fail
                'plate_bbox': plate_bbox,
                'plate_image': plate_image,  # LUÔN có plate_image để lưu
                'confidence': best_conf if plate_text_result else 0.0,
                'validation_state': validation_state,
                'sharpness': sharpness
            }

        except Exception as e:
            logger.error(f"Error reading plate: {e}", exc_info=True)
            import traceback
            traceback.print_exc()
            return None

    def draw_plate(self, frame, plate_info):
        if plate_info is None or plate_info.get('plate_bbox') is None:
            return frame

        bbox = plate_info['plate_bbox']
        text = plate_info.get('plate_text', '')

        x1, y1, x2, y2 = map(int, bbox)

        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 255), 2)

        cv2.putText(frame, text, (x1, y1 - 10),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)

        return frame
