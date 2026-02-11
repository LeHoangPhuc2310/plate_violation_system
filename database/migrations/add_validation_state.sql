-- Migration: Add validation_state and sharpness columns to violations table
-- Date: 2026-01-11
-- Purpose: Track plate validation state and image quality

-- Add validation_state column
ALTER TABLE violations
ADD COLUMN validation_state VARCHAR(20) DEFAULT 'no_plate'
AFTER status;

-- Add sharpness column
ALTER TABLE violations
ADD COLUMN sharpness FLOAT DEFAULT 0.0
AFTER validation_state;

-- Add index for validation_state for faster queries
CREATE INDEX idx_validation_state ON violations(validation_state);

-- Update existing records to 'valid_plate' if they have plate_image
UPDATE violations
SET validation_state = 'valid_plate'
WHERE plate_image IS NOT NULL AND plate_image != '';

-- Update existing records to 'no_plate' if plate is 'UNKNOWN'
UPDATE violations
SET validation_state = 'no_plate'
WHERE plate = 'UNKNOWN' OR plate IS NULL;

-- Add comment to columns
ALTER TABLE violations
MODIFY COLUMN validation_state VARCHAR(20) DEFAULT 'no_plate'
COMMENT 'Plate validation state: no_plate, text_only, image_only, unreadable, valid_plate';

ALTER TABLE violations
MODIFY COLUMN sharpness FLOAT DEFAULT 0.0
COMMENT 'Plate image sharpness (Laplacian variance)';
