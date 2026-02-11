"""
Các hàm tiện ích cho hệ thống phát hiện vi phạm biển số.
Chứa các hàm dùng chung như format biển số, format thời gian, decorator xác thực.
"""

import pytz
from functools import wraps
from datetime import datetime, timedelta
from flask import redirect, url_for, session

# Múi giờ Việt Nam (UTC+7)
VIETNAM_TZ = pytz.timezone('Asia/Ho_Chi_Minh')
VIETNAM_OFFSET = timedelta(hours=7)


def format_plate(plate_text):
    """
    Format biển số cho hiển thị đẹp: 30A12345 → 30A-12345
    Nếu không có biển số → trả về "Biển số mờ"
    
    Args:
        plate_text: Biển số cần format (có thể là None, string, hoặc số)
    
    Returns:
        str: Biển số đã được format hoặc "Biển số mờ"
    """
    # Xử lý các trường hợp NULL/empty/invalid
    if plate_text is None:
        return 'Biển số mờ'
    
    # Chuyển thành string và loại bỏ khoảng trắng
    plate_text = str(plate_text).strip()
    
    # Kiểm tra giá trị không hợp lệ (không phân biệt hoa thường)
    plate_upper = plate_text.upper()
    invalid_values = ['UNKNOWN', 'NONE', 'N/A', 'NULL', 'NAN', 'NONE', '']
    
    if not plate_text or plate_upper in invalid_values:
        return 'Biển số mờ'  # Thay N/A/NULL thành "Biển số mờ"
    
    # Giữ nguyên text "Biển số mờ" hoặc "Biển quá mờ" - không format
    if plate_text in ['Biển số mờ', 'Biển quá mờ']:
        return 'Biển số mờ'  # Chuẩn hóa thành "Biển số mờ"
    
    # Nếu đã có format (có space hoặc dấu gạch), giữ nguyên
    if ' ' in plate_text or '-' in plate_text or '.' in plate_text:
        return plate_text.upper()
    
    # Format: 30A12345 → 30A-12345
    if len(plate_text) >= 7:
        # Tìm vị trí chữ cái đầu tiên
        first_letter_pos = -1
        for i, char in enumerate(plate_text):
            if char.isalpha():
                first_letter_pos = i
                break
        
        if first_letter_pos >= 2:  # Mã tỉnh (2 chữ số) + chữ cái
            # Tìm vị trí sau chữ cái cuối cùng
            last_letter_pos = first_letter_pos
            for i in range(first_letter_pos + 1, len(plate_text)):
                if plate_text[i].isalpha():
                    last_letter_pos = i
                else:
                    break
            
            # Format: 30A-12345 hoặc 30AB-12345
            return f"{plate_text[:last_letter_pos+1]}-{plate_text[last_letter_pos+1:]}"
    
    return plate_text.upper()


def format_time_vietnam(dt, format_str='%d/%m/%Y %H:%M:%S'):
    """
    Format datetime theo múi giờ Việt Nam (UTC+7)
    Giả sử datetime từ database là UTC, convert sang UTC+7
    
    Args:
        dt: Datetime object hoặc string
        format_str: Format string cho datetime
    
    Returns:
        str: Datetime đã được format hoặc '-' nếu None
    """
    if dt is None:
        return '-'
    
    try:
        # Nếu dt là string, chuyển sang datetime
        if isinstance(dt, str):
            # Thử parse các format phổ biến
            try:
                dt = datetime.fromisoformat(dt.replace('Z', '+00:00'))
            except:
                try:
                    dt = datetime.strptime(dt, '%Y-%m-%d %H:%M:%S')
                except:
                    return dt  # Trả về string gốc nếu không parse được
        
        # Nếu dt là naive datetime (không có timezone), giả sử là UTC
        if isinstance(dt, datetime) and dt.tzinfo is None:
            # Giả sử datetime từ database là UTC, chuyển sang UTC+7
            dt = dt + VIETNAM_OFFSET
        
        # Format datetime
        if hasattr(dt, 'strftime'):
            return dt.strftime(format_str)
        return str(dt)
    except Exception as e:
        # Fallback: format trực tiếp nếu có lỗi
        try:
            if hasattr(dt, 'strftime'):
                return dt.strftime(format_str)
            return str(dt)
        except:
            return str(dt)


def login_required(f):
    """Decorator để yêu cầu đăng nhập."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    """Decorator để yêu cầu quyền admin."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user' not in session:
            return redirect(url_for('login'))
        if session.get('role') != 'admin':
            return "Access denied", 403
        return f(*args, **kwargs)
    return decorated

