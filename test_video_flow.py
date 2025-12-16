"""
TEST VIDEO 5S FLOW - KIỂM TRA TOÀN BỘ
Kiểm tra xem video 5s có được tạo, lưu DB, và gửi Telegram không
"""

import os
import sys
import mysql.connector
from datetime import datetime

print("\n" + "=" * 70)
print("TEST VIDEO 5S FLOW - KIỂM TRA TOÀN BỘ")
print("=" * 70)

# ============================================================================
# 1. CHECK VIDEO FILES
# ============================================================================
print("\n[1/4] Kiểm tra video files trong static/violation_videos/")
print("-" * 70)

video_dir = "static/violation_videos"
if not os.path.exists(video_dir):
    print(f"[ERROR] Directory không tồn tại: {video_dir}")
    sys.exit(1)

video_files = [f for f in os.listdir(video_dir) if f.endswith('.mp4') and f.startswith('violation_clean_')]

if not video_files:
    print(f"[WARNING] Chưa có video nào trong {video_dir}/")
    print(f"   Hãy chạy app và trigger violation trước")
else:
    print(f"[OK] Tìm thấy {len(video_files)} video(s):")
    for i, vf in enumerate(video_files[-5:], 1):  # Show 5 newest
        file_path = os.path.join(video_dir, vf)
        file_size = os.path.getsize(file_path) / 1024 / 1024  # MB
        print(f"   {i}. {vf}")
        print(f"      - Size: {file_size:.2f} MB")
        print(f"      - Path: {file_path}")

# ============================================================================
# 2. CHECK DATABASE
# ============================================================================
print("\n[2/4] Kiểm tra video trong database")
print("-" * 70)

try:
    # Connect to database
    db_config = {
        'host': 'localhost',
        'user': 'root',
        'password': '',
        'database': 'plate_violation_db'
    }

    conn = mysql.connector.connect(**db_config)
    cursor = conn.cursor(dictionary=True)

    # Get latest violations with video
    cursor.execute("""
        SELECT id, plate, speed, speed_limit, video, time
        FROM violations
        WHERE video IS NOT NULL AND video != ''
        ORDER BY id DESC
        LIMIT 5
    """)

    results = cursor.fetchall()

    if not results:
        print("[WARNING] Chưa có violation nào có video trong database")
        print("   Column 'video' đều là NULL hoặc empty")
    else:
        print(f"[OK] Tìm thấy {len(results)} violation(s) có video:")
        for i, row in enumerate(results, 1):
            print(f"\n   {i}. Violation ID: {row['id']}")
            print(f"      - Plate: {row['plate']}")
            print(f"      - Speed: {row['speed']} km/h (Limit: {row['speed_limit']} km/h)")
            print(f"      - Video: {row['video']}")
            print(f"      - Time: {row['time']}")

            # Check if video file exists
            video_path = os.path.join(video_dir, row['video'])
            if os.path.exists(video_path):
                file_size = os.path.getsize(video_path) / 1024 / 1024  # MB
                print(f"      - File exists: YES ({file_size:.2f} MB)")
            else:
                print(f"      - File exists: NO (MISSING!)")

    # Get violations without video
    cursor.execute("""
        SELECT COUNT(*) as count
        FROM violations
        WHERE video IS NULL OR video = ''
    """)

    no_video_count = cursor.fetchone()['count']
    if no_video_count > 0:
        print(f"\n[WARNING] Có {no_video_count} violation(s) KHÔNG có video")
        print(f"   → Video creation có thể đang fail")

    cursor.close()
    conn.close()

except mysql.connector.Error as e:
    print(f"[ERROR] Không thể kết nối database: {e}")
    print(f"   Check MySQL có đang chạy không")
    print(f"   Check database config: host=localhost, user=root, password='', db=plate_violation_db")

# ============================================================================
# 3. CHECK VIDEO DURATION
# ============================================================================
print("\n[3/4] Kiểm tra video duration")
print("-" * 70)

try:
    import cv2

    if video_files:
        # Check first 3 videos
        for vf in video_files[-3:]:
            file_path = os.path.join(video_dir, vf)
            cap = cv2.VideoCapture(file_path)

            if not cap.isOpened():
                print(f"[ERROR] Không thể mở video: {vf}")
                continue

            fps = cap.get(cv2.CAP_PROP_FPS)
            frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            duration = frame_count / fps if fps > 0 else 0

            cap.release()

            status = "OK" if abs(duration - 5.0) < 0.5 else "FAIL"
            print(f"[{status}] {vf}")
            print(f"   - Duration: {duration:.2f}s")
            print(f"   - FPS: {fps:.2f}")
            print(f"   - Frames: {frame_count}")

            if abs(duration - 5.0) >= 0.5:
                print(f"   - WARNING: Duration không đúng 5s!")
    else:
        print("[SKIP] Không có video để kiểm tra")

except ImportError:
    print("[ERROR] OpenCV không có sẵn, bỏ qua check duration")
    print("   Install: pip install opencv-python")

# ============================================================================
# 4. SUMMARY
# ============================================================================
print("\n" + "=" * 70)
print("SUMMARY")
print("=" * 70)

if video_files:
    print(f"✅ Video files: {len(video_files)} file(s) trong {video_dir}/")
else:
    print(f"❌ Video files: KHÔNG CÓ")

print(f"\nCHECKLIST:")
print(f"- [ ] Video files tồn tại trong static/violation_videos/")
print(f"- [ ] Video được lưu vào database (column 'video')")
print(f"- [ ] Video duration = 5.00s")
print(f"- [ ] Video được gửi qua Telegram (check Telegram bot)")

print(f"\nNẾU THIẾU VIDEO:")
print(f"1. Chạy app: python app.py")
print(f"2. Upload video qua web interface")
print(f"3. Đợi vi phạm được phát hiện")
print(f"4. Check logs để debug:")
print(f"   - [DETECTION] 📍 Violation frame: XXX")
print(f"   - [VIOLATION THREAD] 🎬 Creating video")
print(f"   - [VIOLATION THREAD] ✅ Video created")
print(f"   - [TELEGRAM] ✓ Đã gửi video")

print(f"\nTÀI LIỆU:")
print(f"- VIDEO_5S_STATUS.md - Hướng dẫn chi tiết")
print(f"- FINAL_VERIFICATION.md - Báo cáo kiểm tra code")
print(f"- QUICK_START.md - Hướng dẫn nhanh")

print("\n" + "=" * 70)
