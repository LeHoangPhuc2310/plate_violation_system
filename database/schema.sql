-- =====================================================
-- PLATE VIOLATION SYSTEM - DATABASE SCHEMA
-- Version: 1.0
-- Date: 2026-01-25
-- Purpose: Initial database schema for traffic violation detection system
-- =====================================================

-- Create database if not exists
CREATE DATABASE IF NOT EXISTS plate_violation
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE plate_violation;

-- =====================================================
-- Table 1: violations
-- Purpose: Store all traffic violations with evidence
-- =====================================================
CREATE TABLE IF NOT EXISTS violations (
    id INT AUTO_INCREMENT PRIMARY KEY,

    -- Core violation data
    plate VARCHAR(20) DEFAULT NULL COMMENT 'License plate number - NULL if unreadable',
    speed FLOAT NOT NULL COMMENT 'Detected speed in km/h',
    speed_limit INT DEFAULT 40 COMMENT 'Speed limit at location',
    time DATETIME NOT NULL COMMENT 'Violation timestamp',

    -- Evidence files
    image VARCHAR(255) DEFAULT NULL COMMENT 'Path to vehicle image',
    plate_image VARCHAR(255) DEFAULT NULL COMMENT 'Path to plate crop image',
    video VARCHAR(255) DEFAULT NULL COMMENT 'Path to 4-second video clip',

    -- Status and classification
    status ENUM('pending', 'completed', 'sent', 'rejected') DEFAULT 'pending' COMMENT 'Processing status',
    vehicle_class VARCHAR(50) DEFAULT 'unknown' COMMENT 'Vehicle type (car, motorbike, truck)',
    track_id INT DEFAULT NULL COMMENT 'ByteTrack tracking ID',

    -- ALPR data
    validation_state VARCHAR(50) DEFAULT 'no_plate' COMMENT 'Plate validation state',
    sharpness FLOAT DEFAULT 0.0 COMMENT 'Plate image sharpness score',
    confidence FLOAT DEFAULT 0.0 COMMENT 'OCR confidence score (0-1)',

    -- Manual review system (added by migration 001)
    manual_review_required BOOLEAN DEFAULT FALSE COMMENT 'TRUE if plate needs human review',
    manual_review_flag BOOLEAN DEFAULT FALSE COMMENT 'Alias for manual_review_required',
    manual_review_status ENUM('pending', 'in_review', 'completed', 'rejected') DEFAULT NULL COMMENT 'Review workflow status',
    manual_review_by VARCHAR(100) DEFAULT NULL COMMENT 'Username who reviewed',
    manual_review_at DATETIME DEFAULT NULL COMMENT 'When was reviewed',
    manual_review_notes TEXT DEFAULT NULL COMMENT 'JSON with full analysis',

    original_ocr_text VARCHAR(20) DEFAULT NULL COMMENT 'Original OCR result before manual correction',
    ocr_confidence FLOAT DEFAULT NULL COMMENT 'OCR confidence score',
    plate_recognition_method ENUM('ocr_auto', 'ocr_low_conf', 'manual_entry', 'no_plate') DEFAULT 'ocr_auto' COMMENT 'How was plate obtained',
    violation_confirmed BOOLEAN DEFAULT TRUE COMMENT 'Is this a real violation',

    -- Plate resolution fields (added by migration 002)
    resolution_status ENUM('auto_confirmed', 'auto_suggested', 'manual_required') DEFAULT 'manual_required' COMMENT 'Plate resolution decision',
    plate_status ENUM('AUTO_CONFIRMED', 'MANUAL_REQUIRED') DEFAULT 'MANUAL_REQUIRED' COMMENT 'Simple plate status',
    ocr_suggestions TEXT DEFAULT NULL COMMENT 'JSON array of OCR suggestions',

    -- Telegram notification tracking (added by migration 005)
    telegram_sent BOOLEAN DEFAULT FALSE COMMENT 'Whether Telegram notification was sent',
    telegram_sent_at DATETIME DEFAULT NULL COMMENT 'When Telegram notification was sent',

    -- Metadata
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    -- Indexes
    INDEX idx_plate (plate),
    INDEX idx_time (time),
    INDEX idx_status (status),
    INDEX idx_track_id (track_id),
    INDEX idx_manual_review_required (manual_review_required, manual_review_status),
    INDEX idx_manual_review_status (manual_review_status),
    INDEX idx_plate_recognition_method (plate_recognition_method),
    INDEX idx_resolution_status (resolution_status),
    INDEX idx_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Traffic violations with evidence';

-- =====================================================
-- Table 2: vehicle_owner
-- Purpose: Store vehicle owner information for lookup
-- =====================================================
CREATE TABLE IF NOT EXISTS vehicle_owner (
    plate VARCHAR(20) PRIMARY KEY COMMENT 'License plate number',
    owner_name VARCHAR(255) NOT NULL COMMENT 'Owner full name',
    address TEXT DEFAULT NULL COMMENT 'Owner address',
    phone VARCHAR(20) DEFAULT NULL COMMENT 'Owner phone number',

    -- Metadata
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    INDEX idx_owner_name (owner_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Vehicle owner information';

-- =====================================================
-- Table 3: users
-- Purpose: Admin users for web interface authentication
-- =====================================================
CREATE TABLE IF NOT EXISTS users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(100) NOT NULL UNIQUE COMMENT 'Login username',
    password_hash VARCHAR(255) NOT NULL COMMENT 'Hashed password (bcrypt)',
    full_name VARCHAR(255) DEFAULT NULL COMMENT 'Full name',
    role ENUM('admin', 'operator', 'viewer') DEFAULT 'viewer' COMMENT 'User role',
    is_active BOOLEAN DEFAULT TRUE COMMENT 'Account active status',

    -- Metadata
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    last_login DATETIME DEFAULT NULL COMMENT 'Last login timestamp',

    INDEX idx_username (username),
    INDEX idx_role (role)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Admin users for web interface';

-- =====================================================
-- Table 4: manual_review_logs (added by migration 003)
-- Purpose: Audit trail for manual plate reviews
-- =====================================================
CREATE TABLE IF NOT EXISTS manual_review_logs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    violation_id INT NOT NULL COMMENT 'FK to violations table',
    action ENUM('created', 'reviewed', 'approved', 'rejected', 'edited') NOT NULL COMMENT 'Action performed',
    performed_by VARCHAR(100) NOT NULL COMMENT 'Username who performed action',
    performed_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT 'When action was performed',

    -- Changes made
    old_plate VARCHAR(20) DEFAULT NULL COMMENT 'Previous plate value',
    new_plate VARCHAR(20) DEFAULT NULL COMMENT 'New plate value',
    old_status VARCHAR(50) DEFAULT NULL COMMENT 'Previous status',
    new_status VARCHAR(50) DEFAULT NULL COMMENT 'New status',
    notes TEXT DEFAULT NULL COMMENT 'Review notes',

    -- Metadata
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    INDEX idx_violation_id (violation_id),
    INDEX idx_performed_by (performed_by),
    INDEX idx_performed_at (performed_at),

    FOREIGN KEY (violation_id) REFERENCES violations(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Audit log for manual plate reviews';

-- =====================================================
-- Insert default admin user
-- Password: admin123 (bcrypt hash)
-- IMPORTANT: Change this password in production!
-- =====================================================
INSERT INTO users (username, password_hash, full_name, role)
VALUES (
    'admin',
    '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewY5oi2JxVcDWPsW',  -- admin123
    'System Administrator',
    'admin'
) ON DUPLICATE KEY UPDATE username=username;

-- =====================================================
-- Sample vehicle owner data (for testing)
-- =====================================================
INSERT INTO vehicle_owner (plate, owner_name, address, phone) VALUES
('51A-12345', 'Nguyễn Văn A', '123 Đường ABC, Quận 1, TP.HCM', '0901234567'),
('92B-67890', 'Trần Thị B', '456 Đường XYZ, Quận 3, TP.HCM', '0907654321'),
('30C-11111', 'Lê Văn C', '789 Đường DEF, Quận 5, TP.HCM', '0909876543')
ON DUPLICATE KEY UPDATE plate=plate;

-- =====================================================
-- Grant permissions (adjust as needed)
-- =====================================================
-- GRANT ALL PRIVILEGES ON plate_violation.* TO 'root'@'localhost';
-- FLUSH PRIVILEGES;

-- =====================================================
-- END OF SCHEMA
-- =====================================================
