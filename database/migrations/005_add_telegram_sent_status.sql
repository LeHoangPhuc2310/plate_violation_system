-- Migration: Add telegram_sent column to violations table
-- Purpose: Track whether violation has been sent to Telegram

ALTER TABLE violations 
ADD COLUMN telegram_sent TINYINT(1) DEFAULT 0 COMMENT '1 if sent to Telegram, 0 otherwise';

ALTER TABLE violations 
ADD COLUMN telegram_sent_at DATETIME NULL COMMENT 'Timestamp when sent to Telegram';

ALTER TABLE violations 
ADD INDEX idx_telegram_sent (telegram_sent);

