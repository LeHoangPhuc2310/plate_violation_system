-- Migration: Add confidence column to violations table
-- Date: 2026-01-11
-- Purpose: Store OCR confidence score for plate detection

-- Add confidence column (độ tin cậy của OCR)
ALTER TABLE violations
ADD COLUMN confidence FLOAT DEFAULT 0.0
AFTER sharpness;

-- Add comment to column
ALTER TABLE violations
MODIFY COLUMN confidence FLOAT DEFAULT 0.0
COMMENT 'OCR confidence score (0.0-1.0) for plate text accuracy';

-- Update existing records with default confidence
UPDATE violations
SET confidence = 0.0
WHERE confidence IS NULL;

-- Add index for querying by confidence
CREATE INDEX idx_confidence ON violations(confidence);
