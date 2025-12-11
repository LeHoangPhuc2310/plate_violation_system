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
