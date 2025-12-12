from flask import Flask, Response, render_template, request, jsonify, redirect, session, url_for, send_from_directory, make_response
from flask_mysqldb import MySQL
import cv2
import numpy as np
import time
import json
import os
import re
import requests
import threading
from collections import deque
import queue
from datetime import datetime, timezone, timedelta

# Lazy import - chỉ import khi cần (tránh load models nặng khi start)
# from combined_detector import CombinedDetector
# from speed_tracker import SpeedTracker
# from detector import PlateDetector

# ======================
# TIMEZONE CONFIG (Vietnam UTC+7)
# ======================
VIETNAM_TZ = timezone(timedelta(hours=7))

def get_vietnam_time():
    """Trả về thời gian hiện tại theo múi giờ Vietnam (UTC+7)"""
    return datetime.now(VIETNAM_TZ)

def format_vietnam_time(dt=None):
    """Format thời gian theo định dạng Vietnam"""
    if dt is None:
        dt = get_vietnam_time()
    elif isinstance(dt, str):
        # Nếu là string từ database, parse và convert
        try:
            dt = datetime.strptime(dt, '%Y-%m-%d %H:%M:%S')
            dt = dt.replace(tzinfo=timezone.utc).astimezone(VIETNAM_TZ)
        except:
            return dt
    elif isinstance(dt, datetime):
        if dt.tzinfo is None:
            # Nếu không có timezone, giả sử là UTC
            dt = dt.replace(tzinfo=timezone.utc).astimezone(VIETNAM_TZ)
        else:
            dt = dt.astimezone(VIETNAM_TZ)
    return dt.strftime('%d/%m/%Y %H:%M:%S')

# ======================
# FLASK APP
# ======================
app = Flask(__name__)
# Sử dụng environment variable cho secret key (bảo mật hơn)
app.secret_key = os.getenv('SECRET_KEY', 'your-secret-key-123-change-in-production')

# ======================
# DATABASE CONFIGURATION
# ======================
app.config['MYSQL_HOST'] = os.getenv('MYSQL_HOST', 'localhost')
app.config['MYSQL_USER'] = os.getenv('MYSQL_USER', 'root')
app.config['MYSQL_PASSWORD'] = os.getenv('MYSQL_PASSWORD', '')
app.config['MYSQL_DB'] = os.getenv('MYSQL_DB', 'plate_violation')
app.config['MYSQL_CURSORCLASS'] = 'DictCursor'
# Thêm timeout để tránh block khi kết nối
app.config['MYSQL_CONNECT_TIMEOUT'] = 5

mysql = MySQL(app)

# Test database connection (non-blocking)
def test_db_connection():
    """Test database connection without blocking startup"""
    try:
        with app.app_context():
            conn = mysql.connection
            if conn:
                print("✅ Database connection OK")
                return True
    except Exception as e:
        print(f"⚠️  Database connection warning: {e}")
        print("⚠️  App will continue but database features may not work")
    return False

# ======================
# ROUTES
# ======================

@app.route('/')
def index():
    """Trang chủ - Dashboard"""
    try:
        return render_template('index.html')
    except Exception as e:
        print(f"Error rendering index.html: {e}")
        return f"<h1>Plate Violation System</h1><p>Server is running</p><p>Error loading template: {e}", 200

@app.route('/home')
def home():
    """Trang home"""
    try:
        return render_template('home.html')
    except Exception as e:
        print(f"Error rendering home.html: {e}")
        return f"<h1>Home</h1><p>Error loading template: {e}", 200

@app.route('/health')
def health():
    """Health check endpoint"""
    return jsonify({
        'status': 'ok', 
        'message': 'Server is running',
        'timestamp': datetime.now().isoformat()
    }), 200

@app.route('/test')
def test():
    """Simple test endpoint"""
    return "<h1>Test OK</h1><p>Flask is working!</p>", 200

# ======================
# RUN APPLICATION
# ======================
if __name__ == '__main__':
    # Đọc environment variables TRƯỚC KHI Flask load config
    # Override bất kỳ config nào từ .env file
    host = os.environ.get('HOST', '0.0.0.0')
    port_str = os.environ.get('PORT', '5000')
    port = int(port_str) if port_str.isdigit() else 5000
    
    # FORCE tắt debug mode - không cho phép bật từ bất kỳ đâu
    os.environ['FLASK_DEBUG'] = '0'
    os.environ['FLASK_ENV'] = 'production'
    debug = False
    
    print("=" * 60)
    print("Starting Plate Violation System")
    print("=" * 60)
    print(f"Host: {host}")
    print(f"Port: {port}")
    print(f"Debug mode: {debug} (FORCED OFF)")
    print(f"Environment: production (FORCED)")
    print(f"PORT from env: {os.environ.get('PORT', 'NOT SET')}")
    print("=" * 60)
    
    # Test database connection (non-blocking, delayed)
    import threading
    def delayed_db_test():
        time.sleep(2)  # Đợi 2 giây sau khi server start
        test_db_connection()
    
    db_thread = threading.Thread(target=delayed_db_test, daemon=True)
    db_thread.start()
    
    print(f"\n🚀 Server starting on http://{host}:{port}")
    print("Press CTRL+C to quit\n")
    
    try:
        # FORCE tắt tất cả debug features
        app.run(
            host=host, 
            port=port, 
            debug=False,           # Tắt debug
            threaded=True,
            use_reloader=False,    # Tắt reloader
            use_debugger=False,    # Tắt debugger
            extra_files=None      # Không watch files
        )
    except KeyboardInterrupt:
        print("\n\n👋 Server stopped by user")
    except Exception as e:
        print(f"\n❌ Error starting server: {e}")
        import traceback
        traceback.print_exc()
        raise
