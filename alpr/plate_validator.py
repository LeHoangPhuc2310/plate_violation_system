import re


class PlateValidator:

    MIN_CONFIDENCE = 0.6  # Tăng từ 0.05 → 0.6 để loại bỏ OCR không chính xác
    MIN_SHARPNESS = 100.0  # Minimum sharpness để chấp nhận plate image

    PATTERNS = [
        r'^[0-9]{2}[A-Z][0-9]{4,5}$',
        r'^[0-9]{2}[A-Z]{2}[0-9]{4,5}$',
        r'^[0-9]{2}[A-Z][0-9][0-9]{4,5}$',

        r'^[0-9]{2}[A-Z]{1,2}[0-9]{3}\.[0-9]{2}$',
        r'^[0-9]{2}[A-Z]{1,2}\-[0-9]{4,5}$',
        r'^[0-9]{2}[A-Z][0-9]\-[0-9]{4,5}$',
        r'^[0-9]{2}[A-Z][0-9][0-9]{3}\.[0-9]{2}$',

        r'^[0-9]{2}[A-Z0-9]{5,8}$',
    ]

    PROVINCE_CODES = {
        '11', '12', '14', '15', '16', '17', '18', '19', '20',
        '21', '22', '23', '24', '25', '26', '27', '28', '29', '30', '31', '32', '33', '34', '35', '36', '37', '38',
        '39', '40', '41', '42', '43',
        '47', '48', '49', '50', '51', '52', '53', '54', '55', '56', '57', '58', '59', '60',
        '61', '62', '63', '64', '65', '66', '67', '68', '69', '70', '71', '72', '73', '74', '75', '76', '77', '78', '79',
        '80', '81', '82', '83', '84', '85', '86', '88', '89', '90', '92', '93', '94', '95', '97', '99'
    }

    OCR_CORRECTIONS = {
        'O': '0',
        'I': '1',
        'Z': '2',
        'S': '5',
        'B': '8',
        'G': '6',
        'Q': '0',
        'D': '0',
    }

    @staticmethod
    def normalize_plate(text):
        if not text:
            return ""

        normalized = text.upper().replace(" ", "").replace(".", "").replace("-", "")
        return normalized

    @staticmethod
    def correct_ocr_mistakes(text):
        if not text or len(text) < 7:
            return text

        corrected = list(text)

        for i in range(min(2, len(corrected))):
            if corrected[i] in PlateValidator.OCR_CORRECTIONS:
                corrected[i] = PlateValidator.OCR_CORRECTIONS[corrected[i]]

        start_digits = 3 if len(text) > 7 else 3

        if len(corrected) >= 4:
            if corrected[3].isdigit():
                start_digits = 4
            else:
                start_digits = 3

        for i in range(start_digits, len(corrected)):
            if corrected[i] in PlateValidator.OCR_CORRECTIONS:
                corrected[i] = PlateValidator.OCR_CORRECTIONS[corrected[i]]

        return ''.join(corrected)

    @classmethod
    def validate(cls, text):
        if not text or len(text) < 6:
            return False, ""

        normalized = cls.normalize_plate(text)

        if len(normalized) < 6:
            return False, normalized

        for pattern in cls.PATTERNS:
            if re.match(pattern, normalized):
                province = normalized[:2]
                if province.isdigit() and province in cls.PROVINCE_CODES:
                    return True, normalized
                if province.isdigit():
                    return True, normalized

        corrected = cls.correct_ocr_mistakes(normalized)
        if corrected != normalized:
            for pattern in cls.PATTERNS:
                if re.match(pattern, corrected):
                    province = corrected[:2]
                    if province.isdigit():
                        return True, corrected

        original_upper = text.upper().replace(" ", "")
        for pattern in cls.PATTERNS:
            if re.match(pattern, original_upper):
                clean = original_upper.replace(".", "").replace("-", "")
                province = clean[:2]
                if province.isdigit():
                    return True, clean

        if len(normalized) >= 7 and len(normalized) <= 10:
            province = normalized[:2]
            if province.isdigit() and int(province) >= 11 and int(province) <= 99:
                if len(normalized) > 2 and normalized[2].isalpha():
                    return True, normalized

        return False, normalized

    @staticmethod
    def is_vietnam_plate(text):
        is_valid, _ = PlateValidator.validate(text)
        return is_valid

    @classmethod
    def validate_with_confidence(cls, plate_text, confidence):
        if confidence < cls.MIN_CONFIDENCE:
            return False, "", f"Low confidence: {confidence:.2f} < {cls.MIN_CONFIDENCE}"

        is_valid, normalized = cls.validate(plate_text)
        if not is_valid:
            return False, normalized, f"Invalid format: '{plate_text}'"

        return True, normalized, "OK"

    @classmethod
    def get_validation_score(cls, plate_text, confidence, vote_count=1):
        is_valid, normalized, _ = cls.validate_with_confidence(plate_text, confidence)

        if not is_valid:
            return 0.0

        score = confidence * vote_count

        if len(normalized) >= 2:
            province = normalized[:2]
            if province.isdigit() and province in cls.PROVINCE_CODES:
                score *= 1.1

        if 7 <= len(normalized) <= 9:
            score *= 1.05

        return score
