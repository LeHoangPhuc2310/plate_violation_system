"""
Cấu hình logging tập trung cho hệ thống phát hiện vi phạm biển số.
Hỗ trợ nhiều mức log, ghi vào console và file, tự động rotate log files.
"""

import os
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime


def setup_logging(log_level=None, log_dir='logs'):
    """
    Thiết lập cấu hình logging cho ứng dụng.
    
    Args:
        log_level: Mức log (DEBUG, INFO, WARNING, ERROR, CRITICAL)
                  Nếu None, tự động phát hiện từ FLASK_ENV
        log_dir: Thư mục lưu log files (mặc định: 'logs')
    
    Returns:
        logging.Logger: Logger instance đã cấu hình
    """
    # Tạo thư mục logs nếu chưa có
    os.makedirs(log_dir, exist_ok=True)
    
    # Xác định mức log
    if log_level is None:
        flask_env = os.getenv('FLASK_ENV', 'development')
        if flask_env == 'production':
            log_level = logging.INFO  # Production: Chỉ INFO trở lên
        else:
            log_level = logging.DEBUG  # Development: Tất cả logs
    
    # Chuyển string sang logging level nếu cần
    if isinstance(log_level, str):
        log_level = getattr(logging, log_level.upper(), logging.INFO)
    
    # Tạo formatter
    detailed_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    simple_formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Lấy root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    
    # Xóa handlers hiện có để tránh trùng lặp
    root_logger.handlers.clear()
    
    # Console handler (format đơn giản, cho development)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)
    console_handler.setFormatter(simple_formatter)
    root_logger.addHandler(console_handler)
    
    # File handler với rotation (format chi tiết, cho production)
    log_file = os.path.join(log_dir, 'app.log')
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=10 * 1024 * 1024,  # 10MB mỗi file
        backupCount=5,  # Giữ 5 file backup (tổng 50MB)
        encoding='utf-8'
    )
    file_handler.setLevel(log_level)
    file_handler.setFormatter(detailed_formatter)
    root_logger.addHandler(file_handler)
    
    # File log lỗi (chỉ ERROR và CRITICAL)
    error_log_file = os.path.join(log_dir, 'error.log')
    error_handler = RotatingFileHandler(
        error_log_file,
        maxBytes=5 * 1024 * 1024,  # 5MB mỗi file
        backupCount=3,  # Giữ 3 file backup (tổng 15MB)
        encoding='utf-8'
    )
    error_handler.setLevel(logging.ERROR)  # Chỉ ERROR và CRITICAL
    error_handler.setFormatter(detailed_formatter)
    root_logger.addHandler(error_handler)
    
    return root_logger


def get_logger(name=None):
    """
    Lấy logger instance cho một module.
    
    Args:
        name: Tên logger (thường là __name__ của module)
              Nếu None, trả về root logger
    
    Returns:
        logging.Logger: Logger instance
    """
    if name is None:
        return logging.getLogger()
    return logging.getLogger(name)


# Thiết lập logging khi module được import
setup_logging()

