-- Database initialization script for plate_violation system
-- This script will be executed when MySQL container starts for the first time

CREATE DATABASE IF NOT EXISTS plate_violation CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE plate_violation;

-- Table: users (for authentication)
CREATE TABLE IF NOT EXISTS users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    password VARCHAR(255) NOT NULL,
    role ENUM('admin', 'viewer') DEFAULT 'viewer',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Table: vehicle_owner (vehicle registry)
CREATE TABLE IF NOT EXISTS vehicle_owner (
    plate VARCHAR(20) PRIMARY KEY,
    owner_name VARCHAR(100),
    address VARCHAR(255),
    phone VARCHAR(20),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Table: violations (violation records)
CREATE TABLE IF NOT EXISTS violations (
    id INT AUTO_INCREMENT PRIMARY KEY,
    plate VARCHAR(20),
    speed FLOAT NOT NULL,
    speed_limit INT NOT NULL DEFAULT 40,
    image VARCHAR(255),
    plate_image VARCHAR(255),
    video VARCHAR(255),
    status ENUM('pending', 'sent', 'failed') DEFAULT 'pending',
    vehicle_class VARCHAR(50),
    time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    owner_name VARCHAR(100),
    address VARCHAR(255),
    phone VARCHAR(20),
    INDEX idx_plate (plate),
    INDEX idx_time (time),
    INDEX idx_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Insert default admin user (password: admin123)
-- Password is hashed using werkzeug.security.generate_password_hash
INSERT INTO users (username, password, role) VALUES 
('admin', 'pbkdf2:sha256:600000$randomsalt$hashedpassword', 'admin'),
('viewer', 'pbkdf2:sha256:600000$randomsalt$hashedpassword', 'viewer')
ON DUPLICATE KEY UPDATE username=username;

-- Insert sample vehicle owners
INSERT INTO vehicle_owner (plate, owner_name, address, phone) VALUES
('29H95559', 'Nguyễn Văn A', 'Cà Mau', '0123456789'),
('51F12345', 'Trần Thị B', 'TP.HCM', '0987654321'),
('92A67890', 'Lê Văn C', 'Hà Nội', '0912345678')
ON DUPLICATE KEY UPDATE plate=plate;

-- Grant privileges
GRANT ALL PRIVILEGES ON plate_violation.* TO 'admin'@'%';
FLUSH PRIVILEGES;

