"""
TEST VIDEO CREATION - Debug script
"""
import cv2
import os
import time

def test_opencv_video_creation():
    """Test tạo video 5s bằng OpenCV từ video gốc"""

    print("=" * 70)
    print("TEST: OpenCV Video Creation (5 seconds)")
    print("=" * 70)

    # Tìm video trong uploads/
    video_files = []
    if os.path.exists("uploads"):
        video_files = [f for f in os.listdir("uploads") if f.endswith(('.mp4', '.avi', '.mov'))]

    if not video_files:
        print("[ERROR] No video files found in uploads/")
        print("   Please upload a video first via web interface")
        return False

    source_video = os.path.join("uploads", video_files[0])
    print(f"[OK] Found source video: {source_video}")

    # Mở video
    cap = cv2.VideoCapture(source_video)

    if not cap.isOpened():
        print(f"[ERROR] Cannot open video: {source_video}")
        return False

    # Lấy properties
    fps = cap.get(cv2.CAP_PROP_FPS)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = total_frames / fps

    print(f"\nVideo Properties:")
    print(f"   - Resolution: {width}x{height}")
    print(f"   - FPS: {fps}")
    print(f"   - Total frames: {total_frames}")
    print(f"   - Duration: {duration:.2f}s")

    # Giả lập vi phạm ở giữa video
    violation_frame = total_frames // 2
    violation_timestamp = violation_frame / fps

    print(f"\nSimulated Violation:")
    print(f"   - Frame: {violation_frame}")
    print(f"   - Timestamp: {violation_timestamp:.2f}s")

    # Calculate extraction window (2s before + 3s after = 5s)
    pre_frames = int(fps * 2.0)
    post_frames = int(fps * 3.0)

    start_frame = max(0, violation_frame - pre_frames)
    end_frame = min(total_frames, violation_frame + post_frames)

    extract_frames = end_frame - start_frame
    extract_duration = extract_frames / fps

    print(f"\nExtraction Window:")
    print(f"   - Start frame: {start_frame}")
    print(f"   - End frame: {end_frame}")
    print(f"   - Total frames to extract: {extract_frames}")
    print(f"   - Expected duration: {extract_duration:.2f}s")

    # Seek to start frame
    cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
    print(f"\nSeeking to frame {start_frame}...")

    # Create output
    os.makedirs("static/violation_videos", exist_ok=True)
    output_path = f"static/violation_videos/test_video_{int(time.time())}.mp4"

    print(f"\nCreating video:")
    print(f"   - Output: {output_path}")
    print(f"   - Codec: mp4v")
    print(f"   - FPS: {fps}")
    print(f"   - Resolution: {width}x{height}")

    # Try different codecs
    codecs_to_try = [
        ('mp4v', 'MPEG-4'),
        ('avc1', 'H.264 AVC'),
        ('H264', 'H.264'),
        ('X264', 'x264')
    ]

    out = None
    used_codec = None

    for codec_code, codec_name in codecs_to_try:
        try:
            fourcc = cv2.VideoWriter_fourcc(*codec_code)
            test_out = cv2.VideoWriter(output_path, fourcc, fps, (width, height))

            if test_out.isOpened():
                out = test_out
                used_codec = codec_name
                print(f"   [OK] Using codec: {codec_name} ({codec_code})")
                break
            else:
                test_out.release()
                print(f"   [SKIP] Codec {codec_code} not available")
        except Exception as e:
            print(f"   [ERROR] Codec {codec_code} error: {e}")

    if not out or not out.isOpened():
        print(f"\n[ERROR] Cannot create VideoWriter with any codec")
        cap.release()
        return False

    # Extract frames
    print(f"\nExtracting frames...")
    frames_written = 0
    current_frame = start_frame

    start_time = time.time()

    while current_frame < end_frame:
        ret, frame = cap.read()

        if not ret:
            print(f"   [WARN] Cannot read frame {current_frame}")
            break

        out.write(frame)
        frames_written += 1
        current_frame += 1

        # Progress every 30 frames
        if frames_written % 30 == 0:
            progress = (frames_written / extract_frames) * 100
            print(f"   Progress: {frames_written}/{extract_frames} frames ({progress:.1f}%)")

    elapsed = time.time() - start_time

    # Release
    out.release()
    cap.release()

    print(f"\nProcessing time: {elapsed:.2f}s")

    # Verify output
    if os.path.exists(output_path):
        file_size = os.path.getsize(output_path)

        if file_size > 0:
            actual_duration = frames_written / fps

            print(f"\nSUCCESS! Video created:")
            print(f"   - File: {os.path.basename(output_path)}")
            print(f"   - Size: {file_size / 1024:.1f} KB")
            print(f"   - Frames written: {frames_written}")
            print(f"   - Duration: {actual_duration:.2f}s")
            print(f"   - Codec: {used_codec}")

            # Verify with ffprobe if available
            try:
                import subprocess
                result = subprocess.run(
                    ['ffprobe', '-v', 'error', '-show_entries',
                     'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1',
                     output_path],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                if result.returncode == 0:
                    probe_duration = float(result.stdout.strip())
                    print(f"   - Verified duration (ffprobe): {probe_duration:.2f}s")

                    if abs(probe_duration - 5.0) < 0.5:
                        print(f"   [OK] Duration is correct (~5s)")
                    else:
                        print(f"   [WARN] Duration mismatch: expected 5s, got {probe_duration:.2f}s")
            except:
                pass

            print(f"\nPlay video with:")
            print(f"   ffplay {output_path}")
            print(f"   or open in browser/player")

            return True
        else:
            print(f"\n[ERROR] Output file is EMPTY (0 bytes)")
            return False
    else:
        print(f"\n[ERROR] Output file NOT CREATED")
        return False


def test_ffmpeg_availability():
    """Test FFmpeg có sẵn không"""

    print("\n" + "=" * 70)
    print("TEST: FFmpeg Availability")
    print("=" * 70)

    try:
        import subprocess
        result = subprocess.run(
            ['ffmpeg', '-version'],
            capture_output=True,
            text=True,
            timeout=5
        )

        if result.returncode == 0:
            version_line = result.stdout.split('\n')[0]
            print(f"[OK] FFmpeg available: {version_line}")
            return True
        else:
            print(f"[ERROR] FFmpeg command failed")
            return False

    except FileNotFoundError:
        print(f"[ERROR] FFmpeg NOT FOUND in PATH")
        print(f"\nInstall FFmpeg:")
        print(f"   Windows: choco install ffmpeg")
        print(f"   Linux:   sudo apt install ffmpeg")
        print(f"   Or download: https://ffmpeg.org/download.html")
        return False
    except Exception as e:
        print(f"[ERROR] Error checking FFmpeg: {e}")
        return False


def check_system_info():
    """Kiểm tra thông tin hệ thống"""

    print("\n" + "=" * 70)
    print("SYSTEM INFORMATION")
    print("=" * 70)

    # Python version
    import sys
    print(f"Python: {sys.version}")

    # OpenCV version
    print(f"OpenCV: {cv2.__version__}")

    # Check directories
    dirs_to_check = ['uploads', 'static', 'static/violation_videos']
    for d in dirs_to_check:
        exists = os.path.exists(d)
        status = "OK" if exists else "MISSING"
        print(f"[{status}] Directory: {d}")

    # Check video files
    if os.path.exists("uploads"):
        videos = [f for f in os.listdir("uploads") if f.endswith(('.mp4', '.avi', '.mov'))]
        print(f"\nVideos in uploads/: {len(videos)}")
        for v in videos[:5]:  # Show first 5
            print(f"   - {v}")


if __name__ == "__main__":
    print("\nVIDEO CREATION DEBUG SCRIPT\n")

    # 1. Check system info
    check_system_info()

    # 2. Test FFmpeg
    ffmpeg_ok = test_ffmpeg_availability()

    # 3. Test OpenCV video creation
    opencv_ok = test_opencv_video_creation()

    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"FFmpeg available: {'YES' if ffmpeg_ok else 'NO'}")
    print(f"OpenCV test: {'SUCCESS' if opencv_ok else 'FAILED'}")

    if opencv_ok:
        print("\n[SUCCESS] Video creation is WORKING!")
        print("   The 5-second video should be in static/violation_videos/")
    else:
        print("\n[FAILED] Video creation FAILED!")
        print("   Check errors above for details")

    print("\n" + "=" * 70)
