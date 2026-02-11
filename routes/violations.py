"""
Routes xem và quản lý vi phạm.
Xử lý routes xem vi phạm, phục vụ file vi phạm và API vi phạm.
"""

import os
from flask import render_template, request, jsonify, send_from_directory, make_response
from utils.logger import get_logger
from utils.helpers import login_required
from config.config import Config

logger = get_logger(__name__)


def init_violations_routes(app, db):
    """
    Khởi tạo routes liên quan đến vi phạm.
    
    Args:
        app: Flask application instance
        db: Database handler instance
    """
    @app.route('/history')
    @login_required
    def history():
        try:
            plate = request.args.get('plate')
            from_date = request.args.get('from_date')
            to_date = request.args.get('to_date')

            rows = db.get_violations(limit=100, plate=plate, from_date=from_date, to_date=to_date)

            # Debug: Log số lượng violations và dữ liệu mẫu
            logger.debug(f"Found {len(rows)} violations")
            if rows:
                sample = rows[0]
                logger.debug(f"Sample violation: Plate={sample.get('plate')}, Image={sample.get('image')}, "
                            f"Plate Image={sample.get('plate_image')}, Video={sample.get('video')}")
            else:
                logger.info("No violations found in database")

            violation_count = None
            if plate:
                violation_count = len([r for r in rows if plate.upper() in r.get('plate', '').upper()])

            return render_template('view_violations.html',
                                 rows=rows,
                                 violation_count=violation_count)
        except Exception as e:
            logger.error(f"History error: {e}", exc_info=True)
            return f"Error: {str(e)}", 500

    @app.route('/manual_review')
    @login_required
    def manual_review_page():
        """Giao diện hàng đợi kiểm tra thủ công"""
        return render_template('manual_review.html')

    @app.route('/violations')
    @login_required
    def get_violations_api():
        rows = db.get_violations(limit=50)
        
        # Debug: Log phản hồi API
        logger.debug(f"/violations API - Returning {len(rows)} violations")
        if rows:
            sample = rows[0]
            logger.debug(f"Sample violation: Plate={sample.get('plate')}, "
                        f"Image={sample.get('image')}, Plate Image={sample.get('plate_image')}, "
                        f"Video={sample.get('video')}")
        else:
            logger.debug("No violations found")
        
        return jsonify(rows)

    @app.route('/violations/<path:filename>')
    def serve_violation_file(filename):
        # Chuẩn hóa dấu phân cách đường dẫn (tương thích Windows)
        filename_normalized = filename.replace('\\', '/')
        file_path = os.path.join(Config.VIOLATION_FOLDER, filename_normalized)

        # Debug: Log request
        logger.debug(f"Request: /violations/{filename}, Normalized: {filename_normalized}, "
                    f"File path: {file_path}, Exists: {os.path.exists(file_path)}")

        if not os.path.exists(file_path):
            logger.warning(f"File NOT found: {file_path}")
            # Thử liệt kê thư mục để debug
            dir_path = os.path.dirname(file_path)
            if os.path.exists(dir_path):
                files = os.listdir(dir_path)
                logger.debug(f"Directory exists: {dir_path}, Files: {files[:10]}")
            else:
                logger.warning(f"Directory NOT found: {dir_path}")
        else:
            logger.info(f"Serving file: {file_path}")

        # QUAN TRỌNG: Tắt cache để tránh trình duyệt tải ảnh cũ
        response = make_response(send_from_directory(Config.VIOLATION_FOLDER, filename_normalized))
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        return response

