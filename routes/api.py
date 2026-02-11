"""
API endpoints cho health checks và tiện ích.
Xử lý API endpoints cho giám sát sức khỏe, autocomplete và các tiện ích khác.
"""

from flask import request, jsonify, send_from_directory
from utils.logger import get_logger
from utils.helpers import login_required

logger = get_logger(__name__)


def init_api_routes(app, db, get_processor):
    """
    Khởi tạo API routes.
    
    Args:
        app: Flask application instance
        db: Database handler instance
        get_processor: Function to get processor instance
    """
    @app.route('/autocomplete')
    @login_required
    def autocomplete():
        q = request.args.get('q', '').upper()
        if len(q) < 2:
            return jsonify([])

        rows = db.get_violations(limit=1000)
        plates = list(set(r.get('plate', '') for r in rows if q in r.get('plate', '')))
        return jsonify(sorted(plates)[:10])

    @app.route('/health')
    def health():
        processor = get_processor()
        return jsonify({
            'status': 'healthy',
            'camera_running': processor.is_running if processor else False,
            'paused': processor.is_paused if processor else False,
            'uptime': 'N/A',
            'threads': {},
            'queues': {},
            'health_monitor': {
                'system': {'cpu_percent': 0, 'memory_percent': 0},
                'processing': {},
                'throughput': {},
                'alerts': []
            }
        })

    @app.route('/health/dashboard')
    def health_dashboard():
        from flask import render_template
        return render_template('health_dashboard.html')

    @app.route('/video_demo/<path:filename>')
    def serve_demo_video(filename):
        return send_from_directory('video_demo', filename)

    @app.route('/api/manual_review/stats')
    @login_required
    def manual_review_stats():
        """API endpoint để lấy thống kê manual review"""
        try:
            if db.mysql is None:
                return jsonify({
                    'success': False,
                    'error': 'Database connection not available',
                    'stats': {'pending': 0, 'in_review': 0, 'completed': 0, 'rejected': 0}
                }), 500

            cursor = db.mysql.connection.cursor()
            
            # Kiểm tra xem có cột manual_review_status không
            try:
                cursor.execute("SHOW COLUMNS FROM violations LIKE 'manual_review_status'")
                has_manual_review_status = cursor.fetchone() is not None
            except:
                has_manual_review_status = False
            
            if has_manual_review_status:
                # Query stats với manual_review_status
                cursor.execute("""
                    SELECT 
                        COUNT(CASE WHEN manual_review_status IS NULL OR manual_review_status = 'pending' THEN 1 END) as pending,
                        COUNT(CASE WHEN manual_review_status = 'in_review' THEN 1 END) as in_review,
                        COUNT(CASE WHEN manual_review_status = 'completed' THEN 1 END) as completed,
                        COUNT(CASE WHEN manual_review_status = 'rejected' THEN 1 END) as rejected
                    FROM violations
                    WHERE manual_review_required = 1 
                       OR plate_status IN ('MANUAL_REQUIRED', 'AUTO_SUGGESTED')
                       OR plate IS NULL 
                       OR plate = '' 
                       OR UPPER(TRIM(plate)) IN ('N/A', 'NULL', 'UNKNOWN', 'NONE', 'NAN')
                """)
            else:
                # Fallback: chỉ đếm pending (không có status)
                cursor.execute("""
                    SELECT 
                        COUNT(*) as pending,
                        0 as in_review,
                        0 as completed,
                        0 as rejected
                    FROM violations
                    WHERE manual_review_required = 1 
                       OR plate IS NULL 
                       OR plate = '' 
                       OR UPPER(TRIM(plate)) IN ('N/A', 'NULL', 'UNKNOWN', 'NONE', 'NAN')
                """)
            
            result = cursor.fetchone()
            cursor.close()
            
            stats = {
                'pending': result[0] if result else 0,
                'in_review': result[1] if result and len(result) > 1 else 0,
                'completed': result[2] if result and len(result) > 2 else 0,
                'rejected': result[3] if result and len(result) > 3 else 0
            }
            
            return jsonify({
                'success': True,
                'stats': stats
            })
            
        except Exception as e:
            logger.error(f"Manual review stats error: {e}", exc_info=True)
            return jsonify({
                'success': False,
                'error': str(e),
                'stats': {'pending': 0, 'in_review': 0, 'completed': 0, 'rejected': 0}
            }), 500

    @app.route('/api/manual_review/pending')
    @login_required
    def manual_review_pending():
        """API endpoint để lấy danh sách vi phạm cần manual review"""
        try:
            if db.mysql is None:
                return jsonify({
                    'success': False,
                    'error': 'Database connection not available',
                    'violations': []
                }), 500

            cursor = db.mysql.connection.cursor()
            
            # Kiểm tra xem có cột manual_review_required và plate_status không
            try:
                cursor.execute("SHOW COLUMNS FROM violations LIKE 'manual_review_required'")
                has_manual_review_required = cursor.fetchone() is not None
                cursor.execute("SHOW COLUMNS FROM violations LIKE 'plate_status'")
                has_plate_status = cursor.fetchone() is not None
            except:
                has_manual_review_required = False
                has_plate_status = False

            # Query violations cần manual review
            if has_manual_review_required and has_plate_status:
                query = """
                    SELECT v.*, o.owner_name, o.address, o.phone,
                           COALESCE(v.plate_status, 'MANUAL_REQUIRED') as plate_status
                    FROM violations v
                    LEFT JOIN vehicle_owner o ON v.plate = o.plate
                    WHERE (v.manual_review_required = 1 OR v.plate_status IN ('MANUAL_REQUIRED', 'AUTO_SUGGESTED'))
                       AND (v.manual_review_status IS NULL OR v.manual_review_status = 'pending')
                    ORDER BY v.time DESC
                    LIMIT 100
                """
            elif has_plate_status:
                query = """
                    SELECT v.*, o.owner_name, o.address, o.phone,
                           COALESCE(v.plate_status, 'MANUAL_REQUIRED') as plate_status
                    FROM violations v
                    LEFT JOIN vehicle_owner o ON v.plate = o.plate
                    WHERE (v.plate_status IN ('MANUAL_REQUIRED', 'AUTO_SUGGESTED')
                           OR v.plate IS NULL 
                           OR v.plate = '' 
                           OR UPPER(TRIM(v.plate)) IN ('N/A', 'NULL', 'UNKNOWN', 'NONE', 'NAN'))
                       AND (v.manual_review_status IS NULL OR v.manual_review_status = 'pending')
                    ORDER BY v.time DESC
                    LIMIT 100
                """
            else:
                # Fallback: Lấy violations không có plate hoặc plate = NULL/N/A
                query = """
                    SELECT v.*, o.owner_name, o.address, o.phone,
                           CASE 
                               WHEN v.plate IS NULL OR v.plate = '' OR UPPER(TRIM(v.plate)) IN ('N/A', 'NULL', 'UNKNOWN', 'NONE', 'NAN') THEN 'MANUAL_REQUIRED'
                               ELSE 'AUTO_CONFIRMED'
                           END as plate_status
                    FROM violations v
                    LEFT JOIN vehicle_owner o ON v.plate = o.plate
                    WHERE (v.plate IS NULL 
                           OR v.plate = '' 
                           OR UPPER(TRIM(v.plate)) IN ('N/A', 'NULL', 'UNKNOWN', 'NONE', 'NAN'))
                    ORDER BY v.time DESC
                    LIMIT 100
                """

            cursor.execute(query)
            columns = [desc[0] for desc in cursor.description]
            violations = []
            
            for row in cursor.fetchall():
                result_dict = dict(zip(columns, row))
                
                # Normalize plate field
                plate_value = result_dict.get('plate')
                if plate_value and str(plate_value).strip().upper() in ['N/A', 'NULL', 'UNKNOWN', 'NONE', 'NAN', '']:
                    result_dict['plate'] = None
                
                # Parse OCR suggestions nếu có
                ocr_suggestions = result_dict.get('ocr_suggestions')
                if ocr_suggestions:
                    try:
                        import json
                        if isinstance(ocr_suggestions, str):
                            result_dict['ocr_suggestions'] = json.loads(ocr_suggestions)
                    except:
                        result_dict['ocr_suggestions'] = []
                else:
                    result_dict['ocr_suggestions'] = []
                
                violations.append(result_dict)
            
            cursor.close()
            
            logger.info(f"Manual review API: Returning {len(violations)} violations")
            return jsonify({
                'success': True,
                'violations': violations
            })
            
        except Exception as e:
            logger.error(f"Manual review API error: {e}", exc_info=True)
            return jsonify({
                'success': False,
                'error': str(e),
                'violations': []
            }), 500

    @app.route('/api/manual_review/<int:violation_id>')
    @login_required
    def get_manual_review_violation(violation_id):
        """API endpoint để lấy thông tin chi tiết của một violation cho manual review"""
        try:
            if db.mysql is None:
                return jsonify({
                    'success': False,
                    'error': 'Database connection not available'
                }), 500

            cursor = db.mysql.connection.cursor()
            
            # Kiểm tra xem có cột plate_status không
            try:
                cursor.execute("SHOW COLUMNS FROM violations LIKE 'plate_status'")
                has_plate_status = cursor.fetchone() is not None
            except:
                has_plate_status = False
            
            # Query violation theo ID
            if has_plate_status:
                query = """
                    SELECT v.*, o.owner_name, o.address, o.phone,
                           COALESCE(v.plate_status, 'MANUAL_REQUIRED') as plate_status,
                           CASE 
                               WHEN v.plate IS NULL OR v.plate = '' OR UPPER(TRIM(v.plate)) IN ('N/A', 'NULL', 'UNKNOWN', 'NONE', 'NAN') THEN NULL
                               ELSE v.plate
                           END as plate_normalized
                    FROM violations v
                    LEFT JOIN vehicle_owner o ON v.plate = o.plate
                    WHERE v.id = %s
                """
            else:
                query = """
                    SELECT v.*, o.owner_name, o.address, o.phone,
                           CASE 
                               WHEN v.plate IS NULL OR v.plate = '' OR UPPER(TRIM(v.plate)) IN ('N/A', 'NULL', 'UNKNOWN', 'NONE', 'NAN') THEN 'MANUAL_REQUIRED'
                               ELSE 'AUTO_CONFIRMED'
                           END as plate_status,
                           CASE 
                               WHEN v.plate IS NULL OR v.plate = '' OR UPPER(TRIM(v.plate)) IN ('N/A', 'NULL', 'UNKNOWN', 'NONE', 'NAN') THEN NULL
                               ELSE v.plate
                           END as plate_normalized
                    FROM violations v
                    LEFT JOIN vehicle_owner o ON v.plate = o.plate
                    WHERE v.id = %s
                """
            
            cursor.execute(query, (violation_id,))
            columns = [desc[0] for desc in cursor.description]
            row = cursor.fetchone()
            
            if not row:
                cursor.close()
                return jsonify({
                    'success': False,
                    'error': f'Violation {violation_id} not found'
                }), 404
            
            result_dict = dict(zip(columns, row))
            
            # Normalize plate field - sử dụng plate_normalized nếu có
            if 'plate_normalized' in result_dict:
                result_dict['plate'] = result_dict.get('plate_normalized')
            else:
                plate_value = result_dict.get('plate')
                if plate_value and str(plate_value).strip().upper() in ['N/A', 'NULL', 'UNKNOWN', 'NONE', 'NAN', '']:
                    result_dict['plate'] = None
            
            # Ensure plate_status is set
            if 'plate_status' not in result_dict or not result_dict.get('plate_status'):
                if not result_dict.get('plate'):
                    result_dict['plate_status'] = 'MANUAL_REQUIRED'
                else:
                    result_dict['plate_status'] = 'AUTO_CONFIRMED'
            
            # Convert datetime objects and Decimal/Float to JSON-serializable types
            from datetime import datetime, date
            from decimal import Decimal
            for key, value in result_dict.items():
                if isinstance(value, (datetime, date)):
                    result_dict[key] = value.isoformat() if value else None
                elif isinstance(value, Decimal):
                    result_dict[key] = float(value) if value is not None else None
                elif isinstance(value, (bytes, bytearray)):
                    # Skip binary data
                    result_dict[key] = None
            
            # Parse OCR suggestions nếu có
            ocr_suggestions = result_dict.get('ocr_suggestions')
            if ocr_suggestions:
                try:
                    import json
                    if isinstance(ocr_suggestions, str):
                        result_dict['ocr_suggestions'] = json.loads(ocr_suggestions)
                except:
                    result_dict['ocr_suggestions'] = []
            else:
                result_dict['ocr_suggestions'] = []
            
            # Parse manual_review_notes nếu có
            manual_review_notes = result_dict.get('manual_review_notes')
            if manual_review_notes:
                try:
                    import json
                    if isinstance(manual_review_notes, str):
                        result_dict['manual_review_notes'] = json.loads(manual_review_notes)
                except:
                    result_dict['manual_review_notes'] = None
            else:
                result_dict['manual_review_notes'] = None
            
            cursor.close()
            
            logger.info(f"Manual review API: Returning violation {violation_id}")
            return jsonify({
                'success': True,
                'violation': result_dict
            })
            
        except Exception as e:
            logger.error(f"Get violation error: {e}", exc_info=True)
            import traceback
            traceback.print_exc()
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500

    @app.route('/api/manual_review/<int:violation_id>/claim', methods=['POST'])
    @login_required
    def claim_manual_review_violation(violation_id):
        """API endpoint để claim một violation cho manual review (optional)"""
        try:
            if db.mysql is None:
                return jsonify({
                    'success': False,
                    'error': 'Database connection not available'
                }), 500

            cursor = db.mysql.connection.cursor()
            
            # Kiểm tra xem có cột manual_review_status không
            try:
                cursor.execute("SHOW COLUMNS FROM violations LIKE 'manual_review_status'")
                has_manual_review_status = cursor.fetchone() is not None
            except:
                has_manual_review_status = False
            
            if has_manual_review_status:
                # Kiểm tra xem violation đã được claim chưa
                cursor.execute("""
                    SELECT manual_review_status FROM violations WHERE id = %s
                """, (violation_id,))
                result = cursor.fetchone()
                
                if result and result[0] == 'in_review':
                    cursor.close()
                    return jsonify({
                        'success': False,
                        'error': 'Violation is already being reviewed by another operator'
                    }), 409
                
                # Claim violation
                from flask import session
                username = session.get('user', 'unknown')
                
                cursor.execute("""
                    UPDATE violations 
                    SET manual_review_status = 'in_review', manual_review_by = %s
                    WHERE id = %s
                """, (username, violation_id))
                db.mysql.connection.commit()
            
            cursor.close()
            
            return jsonify({
                'success': True,
                'message': 'Violation claimed successfully'
            })
            
        except Exception as e:
            logger.error(f"Claim violation error: {e}", exc_info=True)
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500

    @app.route('/api/manual_review/<int:violation_id>/update_plate', methods=['POST'])
    @login_required
    def update_plate_manual_review(violation_id):
        """API endpoint để update biển số sau khi manual review"""
        try:
            data = request.get_json()
            plate_text = data.get('plate', '').strip().upper() if data.get('plate') else None
            notes = data.get('notes', '')
            
            if not plate_text:
                return jsonify({
                    'success': False,
                    'error': 'Biển số không được để trống'
                }), 400

            # Validate plate format (XX[A-Z]XXXXX - không có dấu gạch ngang)
            import re
            # Pattern: 2 số + 1-2 chữ cái + 4-5 số (ví dụ: 29A12345, 30AB1234)
            plate_pattern = r'^[0-9]{2}[A-Z]{1,2}[0-9]{4,5}$'
            if not re.match(plate_pattern, plate_text):
                return jsonify({
                    'success': False,
                    'error': f'Định dạng biển số không hợp lệ. Yêu cầu: XX[A-Z]XXXXX (ví dụ: 29A12345)'
                }), 400

            # Update violation plate
            success = db.update_violation_plate(violation_id, plate_text)
            
            if not success:
                return jsonify({
                    'success': False,
                    'error': 'Không thể cập nhật biển số'
                }), 500

            # Update manual_review_status
            try:
                cursor = db.mysql.connection.cursor()
                # Kiểm tra xem có cột manual_review_status không
                cursor.execute("SHOW COLUMNS FROM violations LIKE 'manual_review_status'")
                has_manual_review_status = cursor.fetchone() is not None
                
                if has_manual_review_status:
                    cursor.execute(
                        "UPDATE violations SET manual_review_status = 'completed', plate_status = 'AUTO_CONFIRMED' WHERE id = %s",
                        (violation_id,)
                    )
                    db.mysql.connection.commit()
                
                cursor.close()
            except Exception as e:
                logger.warning(f"Could not update manual_review_status: {e}")

            # Log vào manual_review_logs nếu có bảng này
            try:
                cursor = db.mysql.connection.cursor()
                cursor.execute("SHOW TABLES LIKE 'manual_review_logs'")
                has_logs_table = cursor.fetchone() is not None
                
                if has_logs_table:
                    from flask import session
                    username = session.get('user', 'unknown')
                    cursor.execute("""
                        INSERT INTO manual_review_logs (violation_id, old_plate_text, new_plate_text, reviewer, reason)
                        VALUES (%s, NULL, %s, %s, %s)
                    """, (violation_id, plate_text, username, notes))
                    db.mysql.connection.commit()
                
                cursor.close()
            except Exception as e:
                logger.warning(f"Could not log to manual_review_logs: {e}")

            # Get owner info
            owner_info = db.get_owner(plate_text)
            
            # Gửi Telegram nếu chưa gửi
            try:
                db.update_violation_status(violation_id, 'sent')
            except:
                pass

            logger.info(f"Manual review: Updated violation {violation_id} with plate {plate_text}")
            
            return jsonify({
                'success': True,
                'plate': plate_text,
                'owner_info': owner_info
            })
            
        except Exception as e:
            logger.error(f"Update plate error: {e}", exc_info=True)
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500

    @app.route('/api/manual_review/<int:violation_id>/reject', methods=['POST'])
    @login_required
    def reject_violation_manual_review(violation_id):
        """API endpoint để reject vi phạm trong manual review"""
        try:
            data = request.get_json()
            notes = data.get('notes', 'Vi phạm bị từ chối bởi người vận hành')
            
            # Update violation status to rejected
            try:
                cursor = db.mysql.connection.cursor()
                
                # Kiểm tra xem có cột manual_review_status không
                cursor.execute("SHOW COLUMNS FROM violations LIKE 'manual_review_status'")
                has_manual_review_status = cursor.fetchone() is not None
                
                if has_manual_review_status:
                    cursor.execute(
                        "UPDATE violations SET manual_review_status = 'rejected', status = 'rejected' WHERE id = %s",
                        (violation_id,)
                    )
                else:
                    cursor.execute(
                        "UPDATE violations SET status = 'rejected' WHERE id = %s",
                        (violation_id,)
                    )
                
                db.mysql.connection.commit()
                cursor.close()
            except Exception as e:
                logger.error(f"Error updating rejection status: {e}", exc_info=True)
                return jsonify({
                    'success': False,
                    'error': f'Không thể cập nhật trạng thái: {str(e)}'
                }), 500

            # Log vào manual_review_logs nếu có bảng này
            try:
                cursor = db.mysql.connection.cursor()
                cursor.execute("SHOW TABLES LIKE 'manual_review_logs'")
                has_logs_table = cursor.fetchone() is not None
                
                if has_logs_table:
                    from flask import session
                    username = session.get('user', 'unknown')
                    cursor.execute("""
                        INSERT INTO manual_review_logs (violation_id, old_plate_text, new_plate_text, reviewer, reason)
                        VALUES (%s, NULL, NULL, %s, %s)
                    """, (violation_id, username, notes))
                    db.mysql.connection.commit()
                
                cursor.close()
            except Exception as e:
                logger.warning(f"Could not log to manual_review_logs: {e}")

            logger.info(f"Manual review: Rejected violation {violation_id}")
            
            return jsonify({
                'success': True,
                'message': 'Vi phạm đã được từ chối'
            })
            
        except Exception as e:
            logger.error(f"Reject violation error: {e}", exc_info=True)
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500

