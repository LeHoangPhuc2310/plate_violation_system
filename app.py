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

from combined_detector import CombinedDetector
from speed_tracker import SpeedTracker
from detector import PlateDetector
# Thử import Enhanced Plate Detector (có fallback)
try:
    from enhanced_plate_detector import EnhancedPlateDetector
    ENHANCED_DETECTOR_AVAILABLE = True
except ImportError:
    ENHANCED_DETECTOR_AVAILABLE = False
    print(">>> ⚠️ Enhanced Plate Detector not available - using standard PlateDetector")

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

mysql = MySQL(app)

# ======================
# ROUTES
# ======================

@app.route('/')
def index():
    """Trang chủ - Dashboard"""
    return render_template('index.html')

@app.route('/home')
def home():
    """Trang home"""
    return render_template('home.html')

@app.route('/health')
def health():
    """Health check endpoint"""
    return jsonify({'status': 'ok', 'message': 'Server is running'}), 200

# ======================
# RUN APPLICATION
# ======================
if __name__ == '__main__':
    host = os.getenv('HOST', '0.0.0.0')
    port = int(os.getenv('PORT', 5000))
    debug = os.getenv('FLASK_DEBUG', 'False').lower() == 'true'
    
    print(f"Starting Flask server on {host}:{port}")
    print(f"Debug mode: {debug}")
    print(f"Environment: {os.getenv('FLASK_ENV', 'production')}")
    
    try:
        app.run(host=host, port=port, debug=debug, threaded=True)
    except Exception as e:
        print(f"Error starting server: {e}")
        raise
