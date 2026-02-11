-- =====================================================
-- MIGRATION: Fix N/A plates in violations table
-- Date: 2026-01-14
-- Purpose: Update old records with "N/A" plate to NULL and set plate_status
-- =====================================================

-- Step 1: Update records with "N/A" or invalid plate values to NULL
UPDATE violations
SET plate = NULL
WHERE plate IN ('N/A', 'NONE', 'NULL', 'UNKNOWN', 'NAN', '')
   OR plate IS NULL;

-- Step 2: Set plate_status = 'MANUAL_REQUIRED' for NULL plates
UPDATE violations
SET plate_status = 'MANUAL_REQUIRED',
    manual_review_flag = TRUE,
    manual_review_required = TRUE
WHERE plate IS NULL
  AND (plate_status IS NULL OR plate_status != 'AUTO_CONFIRMED');

-- Step 3: Ensure plate_status is set for existing records
UPDATE violations
SET plate_status = CASE
    WHEN plate IS NULL OR plate = '' THEN 'MANUAL_REQUIRED'
    WHEN plate_status = 'AUTO_CONFIRMED' THEN 'AUTO_CONFIRMED'
    ELSE 'MANUAL_REQUIRED'
END
WHERE plate_status IS NULL;

-- Step 4: Sync manual_review_flag with plate_status
UPDATE violations
SET manual_review_flag = (plate_status = 'MANUAL_REQUIRED'),
    manual_review_required = (plate_status = 'MANUAL_REQUIRED')
WHERE plate_status IS NOT NULL;

-- =====================================================
-- VERIFICATION QUERIES
-- =====================================================

-- Check how many records have NULL plate
-- SELECT COUNT(*) FROM violations WHERE plate IS NULL;

-- Check plate_status distribution
-- SELECT plate_status, COUNT(*) as count 
-- FROM violations 
-- GROUP BY plate_status;

-- Check for any remaining "N/A" values
-- SELECT COUNT(*) FROM violations WHERE plate = 'N/A';

