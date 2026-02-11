from enum import Enum
import cv2
import numpy as np


class PlateValidationState(Enum):
    """
    Plate validation state machine.
    Only VALID_PLATE state is allowed to be saved to database.
    """
    NO_PLATE = "no_plate"           # No plate detected at all
    TEXT_ONLY = "text_only"         # OCR text exists but no plate image
    IMAGE_ONLY = "image_only"       # Plate image exists but no valid text
    UNREADABLE = "unreadable"       # Plate image exists but too blurry/low quality
    VALID_PLATE = "valid_plate"     # Both valid text and valid image


class PlateImageValidator:
    """
    Validates plate image quality (blur, sharpness, size).
    """

    # Quality thresholds - PHẢI đảm bảo con người có thể đọc được
    # Nguyên tắc: Nếu con người không đọc được bằng mắt thì không xác nhận
    MIN_SHARPNESS = 4.0         # Laplacian variance - ngưỡng tối thiểu (giảm từ 8.0)
    MIN_WIDTH = 25              # Minimum plate width - đủ để nhìn thấy (giảm từ 35)
    MIN_HEIGHT = 8             # Minimum plate height - đủ để đọc (giảm từ 10)
    MIN_ASPECT_RATIO = 1.2      # Width / Height - tỷ lệ biển số VN
    MAX_ASPECT_RATIO = 7.0      # Width / Height maximum ratio

    # Human readability threshold - GIẢM để cho phép nhiều ảnh hơn được lưu
    MIN_READABLE_SHARPNESS = 4.0  # Ngưỡng để con người đọc được (giảm từ 8.0 xuống 4.0)

    @staticmethod
    def calculate_sharpness(image):
        """
        Calculate image sharpness using Laplacian variance.
        Higher value = sharper image.
        """
        if image is None or image.size == 0:
            return 0.0

        try:
            # Convert to grayscale if needed
            if len(image.shape) == 3:
                gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            else:
                gray = image

            # Calculate Laplacian variance
            laplacian = cv2.Laplacian(gray, cv2.CV_64F)
            variance = laplacian.var()

            return float(variance)
        except Exception as e:
            print(f"[PLATE_VALIDATOR] Error calculating sharpness: {e}")
            return 0.0

    @staticmethod
    def validate_plate_image(plate_image, min_sharpness=None, check_human_readable=True):
        """
        Validate plate image quality.

        NGUYÊN TẮC TỐI QUAN TRỌNG:
        Nếu con người không thể đọc được bằng mắt thường → KHÔNG hợp lệ

        Args:
            plate_image: numpy array của ảnh biển số
            min_sharpness: ngưỡng sharpness tối thiểu (nếu None dùng MIN_SHARPNESS)
            check_human_readable: kiểm tra xem con người có đọc được không

        Returns:
            tuple: (is_valid: bool, reason: str, sharpness: float)
        """
        if plate_image is None:
            return False, "plate_image is None", 0.0

        if not isinstance(plate_image, np.ndarray):
            return False, "plate_image is not numpy array", 0.0

        if plate_image.size == 0:
            return False, "plate_image is empty", 0.0

        # Check dimensions
        h, w = plate_image.shape[:2]

        if w < PlateImageValidator.MIN_WIDTH:
            return False, f"width too small ({w} < {PlateImageValidator.MIN_WIDTH}) - human cannot read", 0.0

        if h < PlateImageValidator.MIN_HEIGHT:
            return False, f"height too small ({h} < {PlateImageValidator.MIN_HEIGHT}) - human cannot read", 0.0

        # Check aspect ratio
        aspect_ratio = w / h
        if aspect_ratio < PlateImageValidator.MIN_ASPECT_RATIO:
            return False, f"aspect ratio too small ({aspect_ratio:.2f} < {PlateImageValidator.MIN_ASPECT_RATIO}) - not a plate", 0.0

        if aspect_ratio > PlateImageValidator.MAX_ASPECT_RATIO:
            return False, f"aspect ratio too large ({aspect_ratio:.2f} > {PlateImageValidator.MAX_ASPECT_RATIO}) - not a plate", 0.0

        # Check sharpness
        sharpness = PlateImageValidator.calculate_sharpness(plate_image)
        threshold = min_sharpness if min_sharpness is not None else PlateImageValidator.MIN_SHARPNESS

        if sharpness < threshold:
            return False, f"too blurry (sharpness={sharpness:.1f} < {threshold}) - human cannot read", sharpness

        # Kiểm tra ảnh đủ rõ để con người đọc (ngưỡng cao hơn)
        if check_human_readable and sharpness < PlateImageValidator.MIN_READABLE_SHARPNESS:
            return False, f"not readable by human (sharpness={sharpness:.1f} < {PlateImageValidator.MIN_READABLE_SHARPNESS})", sharpness

        return True, "OK - human readable", sharpness

    @staticmethod
    def is_readable(plate_image):
        """
        Quick check if plate image is readable by humans.
        """
        is_valid, reason, sharpness = PlateImageValidator.validate_plate_image(plate_image)
        return is_valid


class PlateValidator:
    """
    Main plate validator that determines validation state.
    """

    @staticmethod
    def determine_state(plate_text, plate_image, text_is_valid=None):
        """
        Determine plate validation state based on text and image.

        Args:
            plate_text: OCR text result (can be None)
            plate_image: Plate image (numpy array, can be None)
            text_is_valid: Whether text format is valid (if None, will check)

        Returns:
            PlateValidationState
        """
        from .plate_validator import PlateValidator as FormatValidator

        has_text = plate_text is not None and len(str(plate_text).strip()) > 0
        has_image = plate_image is not None and isinstance(plate_image, np.ndarray) and plate_image.size > 0

        # Case 1: No plate at all
        if not has_text and not has_image:
            return PlateValidationState.NO_PLATE

        # Case 2: Only text, no image (REJECT - no evidence)
        if has_text and not has_image:
            return PlateValidationState.TEXT_ONLY

        # Case 3: Only image, no text
        if not has_text and has_image:
            return PlateValidationState.IMAGE_ONLY

        # Case 4: Has both text and image - validate quality
        if has_text and has_image:
            # Check text format validity
            if text_is_valid is None:
                text_is_valid, _ = FormatValidator.validate(plate_text)

            if not text_is_valid:
                # Text format is invalid
                return PlateValidationState.TEXT_ONLY  # Treat as text-only (invalid)

            # Check image quality
            is_valid_image, reason, sharpness = PlateImageValidator.validate_plate_image(plate_image)

            if not is_valid_image:
                return PlateValidationState.UNREADABLE

            # Both text and image are valid
            return PlateValidationState.VALID_PLATE

        # Default: no plate
        return PlateValidationState.NO_PLATE

    @staticmethod
    def is_saveable(validation_state):
        """
        Check if this validation state allows saving to database.
        Only VALID_PLATE is saveable.
        """
        return validation_state == PlateValidationState.VALID_PLATE

    @staticmethod
    def get_state_description(validation_state):
        """
        Get human-readable description of validation state.
        """
        descriptions = {
            PlateValidationState.NO_PLATE: "No plate detected",
            PlateValidationState.TEXT_ONLY: "Text detected but no plate image (not saveable)",
            PlateValidationState.IMAGE_ONLY: "Plate image detected but no valid text",
            PlateValidationState.UNREADABLE: "Plate image too blurry or low quality",
            PlateValidationState.VALID_PLATE: "Valid plate with readable image and text"
        }
        return descriptions.get(validation_state, "Unknown state")


class PlateResolutionStatus(Enum):
    """
    Plate resolution decision status.
    Determines whether plate text should be trusted, suggested, or requires manual entry.

    Các trạng thái quyết định dữ liệu lưu vào database:
    - AUTO_CONFIRMED: plate_text is saved as-is (high confidence)
    - AUTO_SUGGESTED: plate_text = NULL, ocr_suggestions stored for review
    - MANUAL_REQUIRED: plate_text = NULL, no suggestions, human must review image
    """
    AUTO_CONFIRMED = "auto_confirmed"    # High confidence + good image + valid format
    AUTO_SUGGESTED = "auto_suggested"    # Medium confidence - OCR result saved as suggestion only
    MANUAL_REQUIRED = "manual_required"  # Low confidence or poor image - human must review


class PlateResolutionDecider:
    """
    Central decision logic for plate resolution.

    DESIGN PRINCIPLE:
    - Saving an INCORRECT plate is WORSE than saving NULL
    - When in doubt, require manual review
    - Preserve OCR suggestions for human reviewer
    """

    # Thresholds for decision making - centralized and explicit
    # These are the ONLY place where thresholds should be defined

    # HIGH confidence = AUTO_CONFIRMED (trust OCR completely)
    HIGH_CONFIDENCE_THRESHOLD = 0.80     # OCR confidence >= 80%
    HIGH_SHARPNESS_THRESHOLD = 300.0     # Laplacian variance >= 300

    # MEDIUM confidence = AUTO_SUGGESTED (save as suggestion, not final)
    MEDIUM_CONFIDENCE_THRESHOLD = 0.50   # OCR confidence >= 50%
    MEDIUM_SHARPNESS_THRESHOLD = 100.0   # Laplacian variance >= 100

    # Below MEDIUM = MANUAL_REQUIRED (don't trust OCR at all)
    # No thresholds needed - it's the default fallback

    @classmethod
    def decide(cls, plate_text, plate_image, confidence, sharpness, format_is_valid):
        """
        Decide how to handle plate resolution.

        Args:
            plate_text: OCR result (can be None)
            plate_image: Plate image (numpy array, can be None)
            confidence: OCR confidence score (0.0-1.0)
            sharpness: Image sharpness score (Laplacian variance)
            format_is_valid: Whether plate_text passes Vietnam format validation

        Returns:
            dict with:
                - status: PlateResolutionStatus
                - plate_text_to_save: str or None (what to save to DB)
                - ocr_suggestions: list of potential corrections (for manual review)
                - reason: str explaining the decision
                - manual_review_required: bool
        """
        result = {
            'status': PlateResolutionStatus.MANUAL_REQUIRED,
            'plate_text_to_save': None,
            'ocr_suggestions': [],
            'reason': '',
            'manual_review_required': True
        }

        # Case 1: No plate detected at all
        if not plate_text or plate_text.upper() in ['UNKNOWN', 'N/A', '']:
            result['status'] = PlateResolutionStatus.MANUAL_REQUIRED
            result['reason'] = 'No OCR result'
            return result

        # Case 2: No plate image (cannot verify OCR)
        has_image = (plate_image is not None and
                     isinstance(plate_image, np.ndarray) and
                     plate_image.size > 0)
        if not has_image:
            result['status'] = PlateResolutionStatus.MANUAL_REQUIRED
            result['reason'] = 'No plate image to verify OCR'
            result['ocr_suggestions'] = [plate_text] if plate_text else []
            return result

        # Case 3: Invalid format - cannot be AUTO_CONFIRMED
        if not format_is_valid:
            result['status'] = PlateResolutionStatus.MANUAL_REQUIRED
            result['reason'] = f'Invalid Vietnam plate format: {plate_text}'
            result['ocr_suggestions'] = [plate_text]  # Save for human to see
            return result

        # Case 4: Evaluate based on confidence and sharpness
        is_high_confidence = confidence >= cls.HIGH_CONFIDENCE_THRESHOLD
        is_high_sharpness = sharpness >= cls.HIGH_SHARPNESS_THRESHOLD
        is_medium_confidence = confidence >= cls.MEDIUM_CONFIDENCE_THRESHOLD
        is_medium_sharpness = sharpness >= cls.MEDIUM_SHARPNESS_THRESHOLD

        # Decision: AUTO_CONFIRMED
        # Requires BOTH high confidence AND high sharpness AND valid format
        if is_high_confidence and is_high_sharpness and format_is_valid:
            result['status'] = PlateResolutionStatus.AUTO_CONFIRMED
            result['plate_text_to_save'] = plate_text
            result['ocr_suggestions'] = []
            result['reason'] = f'High confidence ({confidence:.2f}) + high sharpness ({sharpness:.1f})'
            result['manual_review_required'] = False
            return result

        # Decision: AUTO_SUGGESTED
        # Medium confidence OR medium sharpness - save suggestion for review
        if (is_medium_confidence or is_medium_sharpness) and format_is_valid:
            result['status'] = PlateResolutionStatus.AUTO_SUGGESTED
            result['plate_text_to_save'] = None  # DO NOT save uncertain text as final
            result['ocr_suggestions'] = [plate_text]
            result['reason'] = f'Medium confidence ({confidence:.2f}) or sharpness ({sharpness:.1f}) - needs review'
            result['manual_review_required'] = True
            return result

        # Decision: MANUAL_REQUIRED (default fallback)
        result['status'] = PlateResolutionStatus.MANUAL_REQUIRED
        result['ocr_suggestions'] = [plate_text] if plate_text else []
        result['reason'] = f'Low confidence ({confidence:.2f}) and/or low sharpness ({sharpness:.1f})'
        result['manual_review_required'] = True
        return result

    @classmethod
    def get_status_description(cls, status):
        """Get human-readable description of resolution status."""
        descriptions = {
            PlateResolutionStatus.AUTO_CONFIRMED:
                'Plate automatically confirmed (high confidence + good image quality)',
            PlateResolutionStatus.AUTO_SUGGESTED:
                'Plate suggested but needs manual verification (medium confidence)',
            PlateResolutionStatus.MANUAL_REQUIRED:
                'Manual review required (low confidence or poor image quality)'
        }
        return descriptions.get(status, 'Unknown status')
