"""
Advanced Plate Format Validator for Vietnamese License Plates
Handles edge cases, common OCR errors, and invalid formats
"""
import re
from typing import Tuple, Optional


class PlateFormatValidator:
    """
    Validates and normalizes Vietnamese license plates
    """

    # Valid province codes (01-99)
    VALID_PROVINCES = list(range(1, 100))

    # Valid vehicle type letters
    VALID_LETTERS = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'K', 'L',
                     'M', 'N', 'P', 'S', 'T', 'U', 'V', 'X', 'Y', 'Z']

    # Common OCR mistakes
    OCR_CORRECTIONS = {
        '0': 'O',  # Zero -> O
        'O': '0',  # O -> Zero (context-dependent)
        '1': 'I',  # One -> I
        'I': '1',  # I -> One (context-dependent)
        '5': 'S',  # Five -> S
        'S': '5',  # S -> Five (context-dependent)
        '8': 'B',  # Eight -> B
        'B': '8',  # B -> Eight (context-dependent)
        '6': 'G',  # Six -> G
        'G': '6',  # G -> Six (context-dependent)
        '2': 'Z',  # Two -> Z
        'Z': '2',  # Z -> Two (context-dependent)
    }

    @staticmethod
    def normalize(plate_text: str) -> str:
        """Remove spaces, dots, dashes"""
        if not plate_text:
            return ""
        return plate_text.upper().replace(' ', '').replace('.', '').replace('-', '').strip()

    @classmethod
    def validate_structure(cls, plate: str) -> Tuple[bool, Optional[dict]]:
        """
        Validate basic structure: [2 digits][1 letter][4-5 digits]
        Returns: (is_valid, parsed_components)
        """
        # Pattern: 2 digits, 1 letter, 4-5 digits
        pattern = r'^(\d{2})([A-Z])(\d{4,5})$'
        match = re.match(pattern, plate)

        if not match:
            return False, None

        province, letter, number = match.groups()

        return True, {
            'province': province,
            'letter': letter,
            'number': number,
            'full': f"{province}{letter}{number}"
        }

    @classmethod
    def validate_components(cls, components: dict) -> Tuple[bool, str]:
        """
        Validate individual components
        Returns: (is_valid, error_message)
        """
        province = int(components['province'])
        letter = components['letter']
        number = components['number']

        # Check province code
        if province not in cls.VALID_PROVINCES:
            return False, f"Invalid province code: {province}"

        # Check letter
        if letter not in cls.VALID_LETTERS:
            return False, f"Invalid vehicle type letter: {letter}"

        # Check number length
        if len(number) < 4 or len(number) > 5:
            return False, f"Invalid number length: {len(number)} (must be 4-5 digits)"

        return True, ""

    @classmethod
    def try_ocr_correction(cls, plate: str) -> list:
        """
        Try to fix common OCR mistakes
        Returns: list of possible corrected plates
        """
        candidates = []

        # Try correcting letters that might be numbers
        # Example: "30C66473" → "30G66473" (C→G)
        # Example: "231OO283" → "23100283" (O→0)

        # Strategy 1: Fix letter position (index 2)
        if len(plate) >= 3:
            letter_pos = plate[2]
            if letter_pos in cls.OCR_CORRECTIONS:
                corrected = plate[:2] + cls.OCR_CORRECTIONS[letter_pos] + plate[3:]
                candidates.append(corrected)

        # Strategy 2: Fix numbers that might be letters
        # Check if any digit looks like a letter
        for i, char in enumerate(plate):
            if char in cls.OCR_CORRECTIONS:
                corrected = plate[:i] + cls.OCR_CORRECTIONS[char] + plate[i+1:]
                candidates.append(corrected)

        # Strategy 3: Handle missing letter
        # Example: "3933797" → Try inserting common letters
        if re.match(r'^\d{2}\d{5}$', plate):
            # Missing letter - try inserting common ones
            for letter in ['D', 'G', 'H', 'N']:
                corrected = plate[:2] + letter + plate[2:]
                candidates.append(corrected)

        # Strategy 4: Handle extra digit
        # Example: "23100283" (8 chars) → Try removing or converting
        if len(plate) > 7:
            # Try removing digits
            for i in range(3, len(plate)):
                corrected = plate[:i] + plate[i+1:]
                candidates.append(corrected)

        return list(set(candidates))  # Remove duplicates

    @classmethod
    def validate(cls, plate_text: str) -> Tuple[bool, Optional[str], str]:
        """
        Main validation function
        Returns: (is_valid, normalized_plate, reason)
        """
        # Normalize
        plate = cls.normalize(plate_text)

        if not plate:
            return False, None, "Empty plate"

        # Try direct validation
        is_valid, components = cls.validate_structure(plate)
        if is_valid:
            is_valid_components, error = cls.validate_components(components)
            if is_valid_components:
                return True, components['full'], "Valid format"
            else:
                return False, None, error

        # Try OCR correction
        candidates = cls.try_ocr_correction(plate)
        for candidate in candidates:
            is_valid, components = cls.validate_structure(candidate)
            if is_valid:
                is_valid_components, error = cls.validate_components(components)
                if is_valid_components:
                    return True, components['full'], f"Corrected from '{plate}' to '{components['full']}'"

        # All attempts failed
        return False, None, f"Invalid format after all correction attempts"

    @classmethod
    def analyze_invalid_plate(cls, plate_text: str) -> dict:
        """
        Analyze why a plate is invalid and suggest fixes
        Returns detailed analysis for manual review
        """
        plate = cls.normalize(plate_text)

        analysis = {
            'original': plate_text,
            'normalized': plate,
            'length': len(plate),
            'issues': [],
            'suggestions': [],
            'needs_manual_review': True
        }

        # Check length
        if len(plate) < 7:
            analysis['issues'].append(f"Too short: {len(plate)} chars (need 7-8)")
        elif len(plate) > 8:
            analysis['issues'].append(f"Too long: {len(plate)} chars (need 7-8)")

        # Check structure
        is_valid, components = cls.validate_structure(plate)
        if not is_valid:
            analysis['issues'].append("Invalid structure (need: [2 digits][1 letter][4-5 digits])")

            # Try to identify what's wrong
            if not re.match(r'^\d{2}', plate):
                analysis['issues'].append("First 2 chars are not digits (province code)")

            if len(plate) >= 3 and not plate[2].isalpha():
                analysis['issues'].append(f"3rd char '{plate[2]}' is not a letter (vehicle type)")
                analysis['suggestions'].append("Check if this is a misread letter (e.g., 0→O, 1→I)")

            if len(plate) > 3 and not re.match(r'^\d+$', plate[3:]):
                analysis['issues'].append("Chars after letter contain non-digits")

        # Try OCR corrections
        candidates = cls.try_ocr_correction(plate)
        if candidates:
            valid_candidates = []
            for candidate in candidates:
                is_valid, components = cls.validate_structure(candidate)
                if is_valid:
                    is_valid_components, _ = cls.validate_components(components)
                    if is_valid_components:
                        valid_candidates.append(candidate)

            if valid_candidates:
                analysis['suggestions'] = [
                    f"Possible correction: {candidate}" for candidate in valid_candidates
                ]

        return analysis


# Test cases
if __name__ == '__main__':
    validator = PlateFormatValidator()

    test_plates = [
        "30G66473",   # Valid
        "29D07277",   # Valid
        "30A52970",   # Valid but rare
        "23100283",   # Invalid - 6 digits, no letter
        "30H26444",   # Valid
        "30N1553",    # Valid - 4 digits
        "3933797",    # Invalid - missing letter
        "30C66473",   # Might be 30G66473 (C→G)
    ]

    print("=" * 80)
    print("PLATE VALIDATION TESTS")
    print("=" * 80)

    for plate in test_plates:
        is_valid, normalized, reason = validator.validate(plate)
        status = "VALID" if is_valid else "INVALID"
        print(f"\n{plate:12} -> {status:8} | {normalized or 'N/A':12} | {reason}")

        if not is_valid:
            analysis = validator.analyze_invalid_plate(plate)
            print("  Issues:")
            for issue in analysis['issues']:
                print(f"    - {issue}")
            if analysis['suggestions']:
                print("  Suggestions:")
                for suggestion in analysis['suggestions']:
                    print(f"    - {suggestion}")
