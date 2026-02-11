-- =====================================================
-- MIGRATION: Add Manual Review System for HITL
-- Date: 2026-01-14
-- Purpose: Separate violation validity from plate recognition
-- =====================================================

-- Step 1: Add manual review columns to violations table
ALTER TABLE violations
ADD COLUMN IF NOT EXISTS manual_review_required BOOLEAN DEFAULT FALSE COMMENT 'TRUE if plate needs human review',
ADD COLUMN IF NOT EXISTS manual_review_status ENUM('pending', 'in_review', 'completed', 'rejected') DEFAULT NULL COMMENT 'Review workflow status',
ADD COLUMN IF NOT EXISTS manual_review_by VARCHAR(100) DEFAULT NULL COMMENT 'Username who reviewed',
ADD COLUMN IF NOT EXISTS manual_review_at DATETIME DEFAULT NULL COMMENT 'When was reviewed',
ADD COLUMN IF NOT EXISTS manual_review_notes TEXT DEFAULT NULL COMMENT 'Human reviewer notes',
ADD COLUMN IF NOT EXISTS original_ocr_text VARCHAR(20) DEFAULT NULL COMMENT 'Original OCR result before manual correction',
ADD COLUMN IF NOT EXISTS ocr_confidence FLOAT DEFAULT NULL COMMENT 'OCR confidence score',
ADD COLUMN IF NOT EXISTS plate_recognition_method ENUM('ocr_auto', 'ocr_low_conf', 'manual_entry', 'no_plate') DEFAULT 'ocr_auto' COMMENT 'How was plate obtained',
ADD COLUMN IF NOT EXISTS violation_confirmed BOOLEAN DEFAULT TRUE COMMENT 'Is this a real violation (vs false positive)';

-- Step 2: Add indexes for performance (use ALTER TABLE ADD INDEX for MySQL compatibility)
ALTER TABLE violations ADD INDEX idx_manual_review_required (manual_review_required, manual_review_status);
ALTER TABLE violations ADD INDEX idx_manual_review_status (manual_review_status);
ALTER TABLE violations ADD INDEX idx_plate_recognition_method (plate_recognition_method);

-- Step 3: Update existing records
UPDATE violations
SET manual_review_required = FALSE,
    plate_recognition_method = 'ocr_auto',
    violation_confirmed = TRUE
WHERE manual_review_required IS NULL;

-- Step 4: Allow plate column to be NULL
ALTER TABLE violations
MODIFY COLUMN plate VARCHAR(20) DEFAULT NULL COMMENT 'License plate number - can be NULL if unreadable';

-- =====================================================
-- Explanation of Design Decisions
-- =====================================================

/*
WHY THIS APPROACH IS LEGALLY SAFER:

1. **Evidence Preservation**
   - Store violation IMMEDIATELY with video/images
   - Don't wait for plate recognition
   - Evidence timestamp is accurate

2. **Audit Trail**
   - Track WHO reviewed (manual_review_by)
   - Track WHEN reviewed (manual_review_at)
   - Track WHAT changed (original_ocr_text vs final plate)
   - Defensible in court

3. **Separate Concerns**
   - Violation occurred (confirmed by video) ≠ Plate readable
   - Can prove speeding even if plate unclear
   - Human review adds credibility

4. **No False Accusations**
   - NULL plate = "we don't know" (honest)
   - Low confidence = human review (safe)
   - No guessing = no wrong person ticketed

5. **Workflow Transparency**
   - manual_review_status shows process
   - Can prove due diligence
   - Clear chain of custody

6. **Quality Control**
   - violation_confirmed allows rejecting false positives
   - Humans can override bad detections
   - System accuracy improves over time
*/
