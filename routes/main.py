"""
Routes ứng dụng chính.
Xử lý các routes chính bao gồm: trang index/home, upload và xử lý video, stream video, stream phát hiện.
"""

import os
import json
import threading
import time
from flask import render_template, request, jsonify, Response, session
from utils.logger import get_logger
from utils.helpers import login_required
from config.config import Config

logger = get_logger(__name__)


def init_main_routes(app, db, get_processor, init_detection_modules):
    """
    Khởi tạo routes ứng dụng chính.
    
    Args:
        app: Flask application instance
        db: Database handler instance
        get_processor: Function to get processor instance
        init_detection_modules: Function to initialize detection modules
    """
    @app.route('/')
    @login_required
    def index():
        db_ok, db_message = True, ""
        try:
            db_ok, db_message = db.check_connection()
            if db_ok and db.mysql:
                cursor = db.mysql.connection.cursor()
                cursor.execute("SELECT DATABASE()")
                db_name = cursor.fetchone()[0]
                cursor.execute("SELECT COUNT(*) FROM violations")
                total_violations = cursor.fetchone()[0]
                cursor.close()
                logger.info(f"Database: {db_name}, Total violations: {total_violations}")
        except Exception as e:
            logger.error(f"Database check error: {e}")
            db_ok, db_message = False, str(e)

        stats = db.get_today_stats()
        return render_template('index.html',
                             total=stats['total'],
                             manual_review=stats['manual_review'],
                             avg_speed=stats['avg_speed'],
                             db_ok=db_ok,
                             db_message=db_message)

    @app.route('/home')
    @login_required
    def home():
        return render_template('home.html',
                             user=session.get('user'),
                             role=session.get('role'))

    @app.route('/upload_video', methods=['POST'])
    @login_required
    def upload_video():
        try:
            if 'video' not in request.files:
                return jsonify({'status': 'error', 'msg': 'No video file'}), 400

            file = request.files['video']
            if file.filename == '':
                return jsonify({'status': 'error', 'msg': 'No file selected'}), 400

            file.seek(0, os.SEEK_END)
            file_size = file.tell()
            file.seek(0)
            max_size = 500 * 1024 * 1024

            if file_size > max_size:
                return jsonify({
                    'status': 'error',
                    'msg': f'File quá lớn ({file_size / 1024 / 1024:.1f}MB). Giới hạn: 500MB'
                }), 400

            logger.info(f"Receiving file: {file.filename}, Size: {file_size / 1024 / 1024:.2f}MB")

            processor = get_processor()
            try:
                if processor and processor.is_running:
                    logger.info("Stopping current video processing...")
                    processor.stop()
                    time.sleep(0.5)

                uploads_dir = Config.UPLOAD_FOLDER
                if os.path.exists(uploads_dir):
                    for existing_file in os.listdir(uploads_dir):
                        if existing_file.startswith('upload_') and existing_file.endswith('.mp4'):
                            old_filepath = os.path.join(uploads_dir, existing_file)
                            try:
                                if os.path.exists(old_filepath):
                                    os.remove(old_filepath)
                                    logger.debug(f"Deleted old upload file: {existing_file}")
                            except PermissionError:
                                logger.warning(f"File {existing_file} is in use")
                            except Exception as e:
                                logger.warning(f"Error deleting {existing_file}: {e}")
            except Exception as e:
                logger.warning(f"Error cleaning up old files: {e}")

            filename = "upload_current.mp4"
            filepath = os.path.join(Config.UPLOAD_FOLDER, filename)

            if os.path.exists(filepath):
                try:
                    os.remove(filepath)
                    logger.debug("Removed existing upload_current.mp4")
                except Exception as e:
                    logger.warning(f"Error removing existing file: {e}")

            try:
                file.save(filepath)
                logger.info(f"File saved: {filename}")
            except Exception as e:
                logger.error(f"Error saving file: {e}", exc_info=True)
                return jsonify({
                    'status': 'error',
                    'msg': f'Lỗi khi lưu file: {str(e)}'
                }), 500

            if not os.path.exists(filepath):
                return jsonify({
                    'status': 'error',
                    'msg': 'File không được lưu thành công'
                }), 500

            try:
                init_detection_modules()
            except Exception as e:
                logger.error(f"Error initializing detection modules: {e}", exc_info=True)
                return jsonify({
                    'status': 'error',
                    'msg': f'Lỗi khởi tạo detection modules: {str(e)}'
                }), 500

            # Lấy processor đã khởi tạo
            processor = get_processor()
            if processor is None:
                return jsonify({
                    'status': 'error',
                    'msg': 'Video processor chưa được khởi tạo'
                }), 500

            def start_processing():
                try:
                    logger.info(f"Starting background processing: {filepath}")
                    processor.start(filepath)
                    logger.info("Processing started successfully")
                except Exception as e:
                    logger.error(f"Error starting processing: {e}", exc_info=True)

            thread = threading.Thread(target=start_processing, daemon=True)
            thread.start()

            return jsonify({'status': 'ok', 'msg': 'Upload successful, processing started'})

        except Exception as e:
            logger.error(f"Unexpected error: {e}", exc_info=True)
            return jsonify({
                'status': 'error',
                'msg': f'Lỗi không xác định: {str(e)}'
            }), 500

    @app.route('/stop_video_upload')
    @login_required
    def stop_video_upload():
        processor = get_processor()
        if processor:
            processor.stop()
        return jsonify({'status': 'ok'})

    @app.route('/toggle_pause')
    @login_required
    def toggle_pause():
        processor = get_processor()
        if processor and processor.is_running:
            is_paused = processor.toggle_pause()
            return jsonify({'status': 'ok', 'paused': is_paused})
        return jsonify({'status': 'error', 'msg': 'No video running'}), 400

    @app.route('/toggle_loop', methods=['POST'])
    @login_required
    def toggle_loop():
        """Bật/tắt lặp video"""
        processor = get_processor()
        if processor and processor.is_running:
            processor.loop_video = not processor.loop_video
            return jsonify({
                'status': 'ok',
                'loop_enabled': processor.loop_video,
                'msg': 'Video loop ' + ('enabled' if processor.loop_video else 'disabled')
            })
        return jsonify({'status': 'error', 'msg': 'No video running'}), 400

    @app.route('/get_video_status')
    @login_required
    def get_video_status():
        """Lấy trạng thái video hiện tại bao gồm cài đặt lặp"""
        processor = get_processor()
        if processor and processor.is_running:
            return jsonify({
                'status': 'ok',
                'is_running': processor.is_running,
                'is_paused': processor.is_paused,
                'loop_enabled': processor.loop_video,
                'current_video': processor.current_video,
                'frame_count': processor.frame_count,
                'total_frames': processor.total_frames,
                'fps': processor.fps
            })
        return jsonify({
            'status': 'ok',
            'is_running': False,
            'loop_enabled': True  # Mặc định
        })

    @app.route('/video_feed')
    @login_required
    def video_feed():
        processor = get_processor()
        if processor is None or not processor.is_running:
            return Response(status=204)

        return Response(
            processor.generate_stream(),
            mimetype='multipart/x-mixed-replace; boundary=frame'
        )

    @app.route('/video_feed_smooth')
    @login_required
    def video_feed_smooth():
        return video_feed()

    @app.route('/detection_stream')
    @login_required
    def detection_stream():
        def generate():
            while True:
                processor = get_processor()
                if processor and processor.is_running:
                    detections = processor.get_detections()
                    data = {
                        'detections': [
                            {
                                'track_id': d.get('track_id'),
                                'bbox': d.get('bbox'),
                                'class': d.get('class'),
                                'speed': d.get('speed'),
                                'violation': d.get('violation', False),
                                'plate': d.get('plate_text')
                            }
                            for d in detections
                        ],
                        'video_resolution': [processor.width, processor.height] if processor else [1920, 1080],
                        'speed_limit': Config.SPEED_LIMIT,
                        'paused': processor.is_paused if processor else False
                    }
                    yield f"data: {json.dumps(data)}\n\n"
                else:
                    yield f"data: {json.dumps({'detections': []})}\n\n"

                time.sleep(0.1)

        return Response(generate(), mimetype='text/event-stream')

