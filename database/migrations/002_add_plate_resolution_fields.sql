-- =====================================================
-- MIGRATION: Add Plate Resolution Fields
-- Date: 2026-01-14
-- Purpose: Support new plate resolution decision flow
--          (AUTO_CONFIRMED, AUTO_SUGGESTED, MANUAL_REQUIRED)
-- =====================================================

-- Step 1: Add resolution_status column
-- This is the primary decision field from PlateResolutionDecider
ALTER TABLE violations
ADD COLUMN IF NOT EXISTS resolution_status ENUM('auto_confirmed', 'auto_suggested', 'manual_required')
    DEFAULT 'manual_required'
    COMMENT 'Plate resolution decision: auto_confirmed=trusted, auto_suggested=needs review, manual_required=human must decide';

-- Step 2: Add ocr_suggestions column
-- Stores JSON array of suggested plate texts for manual review
ALTER TABLE violations
ADD COLUMN IF NOT EXISTS ocr_suggestions TEXT DEFAULT NULL
    COMMENT 'JSON array of OCR suggestions for manual reviewer';

-- Step 3: Ensure manual_review_notes column exists (may already exist from previous migration)
-- This now stores the full analysis including resolution details
ALTER TABLE violations
MODIFY COLUMN manual_review_notes TEXT DEFAULT NULL
    COMMENT 'JSON with full analysis: resolution_status, reason, original_ocr, suggestions, corrections';

-- Step 4: Add index for filtering by resolution status
ALTER TABLE violations ADD INDEX idx_resolution_status (resolution_status);

-- Step 5: Update existing records
-- Records with plate text and high confidence → auto_confirmed
-- Records with plate text and low confidence → auto_suggested
-- Records without plate text → manual_required
UPDATE violations
SET resolution_status = CASE
    WHEN plate IS NOT NULL AND confidence >= 0.80 AND sharpness >= 300.0 THEN 'auto_confirmed'
    WHEN plate IS NOT NULL AND (confidence >= 0.50 OR sharpness >= 100.0) THEN 'auto_suggested'
    ELSE 'manual_required'
END
WHERE resolution_status IS NULL;

-- Step 6: For auto_suggested records, copy plate to ocr_suggestions and set plate to NULL
-- This ensures we don't have uncertain plates in the final field
UPDATE violations
SET ocr_suggestions = CONCAT('["', plate, '"]'),
    manual_review_notes = JSON_OBJECT(
        'resolution_status', 'auto_suggested',
        'resolution_reason', 'Migrated from legacy data',
        'original_ocr', plate,
        'confidence', confidence,
        'sharpness', sharpness
    ),
    plate = NULL,
    manual_review_required = TRUE,
    manual_review_status = 'pending'
WHERE resolution_status = 'auto_suggested'
  AND plate IS NOT NULL
  AND ocr_suggestions IS NULL;

-- =====================================================
-- DECISION FLOW EXPLANATION
-- =====================================================

/*
NEW PLATE RESOLUTION LOGIC:

1. AUTO_CONFIRMED (plate_text is saved)
   - OCR confidence >= 80%
   - Image sharpness >= 300.0
   - Valid Vietnam plate format
   - manual_review_required = FALSE

2. AUTO_SUGGESTED (plate_text = NULL, suggestions stored)
   - OCR confidence >= 50% OR sharpness >= 100.0
   - Valid Vietnam plate format
   - manual_review_required = TRUE
   - Human reviewer sees suggestions

3. MANUAL_REQUIRED (plate_text = NULL, no suggestions)
   - OCR confidence < 50% AND sharpness < 100.0
   - OR invalid plate format
   - OR no OCR result at all
   - manual_review_required = TRUE
   - Human must look at image and enter plate

CRITICAL PRINCIPLE:
Saving an INCORRECT plate is WORSE than saving NULL.
When in doubt, require manual review.
*/
