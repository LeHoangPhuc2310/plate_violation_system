-- =====================================================
-- MIGRATION: Add plate_status ENUM and manual_review_logs audit table
-- Date: 2026-01-14
-- Purpose: Support plate_status field and audit trail for manual reviews
-- =====================================================

-- Step 1: Add plate_status ENUM column
-- This is the primary field for filtering violations by plate confirmation status
ALTER TABLE violations
ADD COLUMN IF NOT EXISTS plate_status ENUM('AUTO_CONFIRMED', 'MANUAL_REQUIRED')
    DEFAULT 'MANUAL_REQUIRED'
    COMMENT 'Plate confirmation status: AUTO_CONFIRMED=AI confirmed, MANUAL_REQUIRED=needs human review';

-- Step 2: Add index for filtering by plate_status
ALTER TABLE violations ADD INDEX idx_plate_status (plate_status);

-- Step 3: Update existing records based on resolution_status
-- AUTO_CONFIRMED resolution_status → plate_status = AUTO_CONFIRMED
-- AUTO_SUGGESTED or MANUAL_REQUIRED → plate_status = MANUAL_REQUIRED
UPDATE violations
SET plate_status = CASE
    WHEN resolution_status = 'auto_confirmed' THEN 'AUTO_CONFIRMED'
    ELSE 'MANUAL_REQUIRED'
END
WHERE plate_status IS NULL;

-- Step 4: Ensure manual_review_flag exists (alias for manual_review_required)
-- If manual_review_required exists, we can use it as manual_review_flag
-- Otherwise, add it
ALTER TABLE violations
ADD COLUMN IF NOT EXISTS manual_review_flag BOOLEAN DEFAULT FALSE
    COMMENT 'TRUE if plate needs manual review (alias for manual_review_required)';

-- Step 5: Sync manual_review_flag with manual_review_required
UPDATE violations
SET manual_review_flag = COALESCE(manual_review_required, FALSE)
WHERE manual_review_flag IS NULL;

-- Step 6: Create manual_review_logs audit table
CREATE TABLE IF NOT EXISTS manual_review_logs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    violation_id INT NOT NULL,
    old_plate_text VARCHAR(20) DEFAULT NULL COMMENT 'Plate text before manual review',
    new_plate_text VARCHAR(20) DEFAULT NULL COMMENT 'Plate text after manual review',
    reviewer VARCHAR(100) NOT NULL COMMENT 'Username who performed the review',
    reviewed_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT 'When the review was performed',
    reason TEXT DEFAULT NULL COMMENT 'Reason for the change or notes',
    FOREIGN KEY (violation_id) REFERENCES violations(id) ON DELETE CASCADE,
    INDEX idx_violation_id (violation_id),
    INDEX idx_reviewer (reviewer),
    INDEX idx_reviewed_at (reviewed_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='Audit log for all manual plate review actions';

-- =====================================================
-- EXPLANATION
-- =====================================================

/*
PLATE_STATUS FIELD:
- AUTO_CONFIRMED: AI has high confidence, plate_text is saved
- MANUAL_REQUIRED: AI cannot confirm, plate_text = NULL, needs human review

MANUAL_REVIEW_LOGS TABLE:
- Tracks every manual plate edit for legal audit trail
- Records who changed what and when
- Required for legal defensibility
- Never delete records (only CASCADE on violation deletion)
*/

