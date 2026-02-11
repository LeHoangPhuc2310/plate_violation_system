import os
import threading
from datetime import datetime
from utils.logger import get_logger

logger = get_logger(__name__)


class DatabaseHandler:

    def __init__(self, app=None):
        self.mysql = None
        self.app = None
        self.db_config = None
        self._connection_lock = threading.Lock()

        if app:
            self.init_app(app)

    def init_app(self, app):
        try:
            from flask_mysqldb import MySQL
            self.mysql = MySQL(app)
            self.app = app

            self.db_config = {
                'host': app.config.get('MYSQL_HOST', 'localhost'),
                'user': app.config.get('MYSQL_USER', 'root'),
                'password': app.config.get('MYSQL_PASSWORD', ''),
                'database': app.config.get('MYSQL_DB', 'plate_violation')
            }

            logger.info("MySQL initialized")

            with app.app_context():
                try:
                    cursor = self.mysql.connection.cursor()
                    cursor.execute("SELECT DATABASE()")
                    result = cursor.fetchone()
                    db_name = result[0] if result else None
                    cursor.execute("SHOW TABLES")
                    tables = [row[0] for row in cursor.fetchall()]
                    cursor.close()
                    logger.info(f"Connected to: {db_name}")
                except Exception as e:
                    logger.warning(f"Connection test failed: {e}. Kiểm tra MYSQL_HOST, MYSQL_USER, MYSQL_PASSWORD, MYSQL_DB trong file .env")

        except Exception as e:
            logger.error(f"MySQL init failed: {e}", exc_info=True)
            if not hasattr(self, 'db_config') or self.db_config is None:
                self.mysql = None

    def check_connection(self):
        """Kiểm tra kết nối DB, trả về (ok: bool, message: str)."""
        if self.mysql is None:
            return False, "MySQL chưa được cấu hình (thiếu .env hoặc MYSQL_*)"
        try:
            cursor = self.mysql.connection.cursor()
            cursor.execute("SELECT 1")
            cursor.fetchone()
            cursor.execute("SHOW TABLES LIKE 'violations'")
            if cursor.fetchone() is None:
                cursor.close()
                return False, "Bảng violations không tồn tại. Chạy database/schema.sql"
            cursor.close()
            return True, "OK"
        except Exception as e:
            msg = str(e)
            if "Access denied" in msg or "1045" in msg:
                return False, "Sai user/password MySQL. Kiểm tra MYSQL_USER, MYSQL_PASSWORD trong .env"
            if "Unknown database" in msg or "1049" in msg:
                return False, "Database không tồn tại. Tạo database và chạy database/schema.sql"
            if "Can't connect" in msg or "2003" in msg:
                return False, "Không kết nối được MySQL server. Kiểm tra MYSQL_HOST và MySQL đã chạy chưa"
            logger.warning(f"DB check_connection error: {e}")
            return False, f"Lỗi DB: {msg}"

    def _get_direct_connection(self, retry=3):
        if not self.db_config:
            return None

        for attempt in range(retry):
            try:
                import MySQLdb
                connection = MySQLdb.connect(
                    host=self.db_config['host'],
                    user=self.db_config['user'],
                    password=self.db_config['password'],
                    database=self.db_config['database'],
                    charset='utf8mb4',
                    connect_timeout=10,
                    read_timeout=10,
                    write_timeout=10,
                    autocommit=False
                )
                connection.ping(True)
                return connection
            except Exception as e:
                if attempt < retry - 1:
                    import time
                    time.sleep(0.5 * (attempt + 1))
                else:
                    logger.error(f"Failed to create direct connection: {e}", exc_info=True)
        return None

    def save_violation(self, violation_data):
        if not self.db_config:
            logger.warning("MySQL config not available")
            return None

        connection = None
        is_direct_connection = False

        try:
            connection = self._get_direct_connection()
            is_direct_connection = True

            if connection is None:
                logger.warning("No database connection available")
                return None

            try:
                connection.ping(True)
            except Exception as ping_error:
                logger.warning(f"Connection ping failed: {ping_error}")
                if is_direct_connection and connection:
                    try:
                        connection.close()
                    except:
                        pass
                connection = self._get_direct_connection()
                if connection is None:
                    return None
                is_direct_connection = True

            plate_text = violation_data.get('plate_text')
            plate_status = violation_data.get('plate_status', 'MANUAL_REQUIRED')
            
            # For MANUAL_REQUIRED, save plate_text as NULL (not "Biển số mờ")
            # "Biển số mờ" is only for display purposes, database should store NULL
            if plate_status == 'MANUAL_REQUIRED':
                # If plate_text is "Biển số mờ" or empty, save as NULL
                if plate_text in ['Biển số mờ', 'Biển quá mờ', 'UNKNOWN', 'N/A', '', None]:
                    plate_text = None  # Save NULL for MANUAL_REQUIRED
            else:
                # For AUTO_CONFIRMED, keep the plate_text as-is
                if plate_text in ['UNKNOWN', 'N/A', '', None]:
                    plate_text = None
                elif plate_text == 'Biển quá mờ':
                    plate_text = 'Biển số mờ'  # Normalize

            # Kiểm tra xem cột resolution_status và plate_status có tồn tại không
            try:
                cursor = connection.cursor()
                cursor.execute("SHOW COLUMNS FROM violations LIKE 'resolution_status'")
                has_resolution_status = cursor.fetchone() is not None
                cursor.execute("SHOW COLUMNS FROM violations LIKE 'plate_status'")
                has_plate_status = cursor.fetchone() is not None
                cursor.close()
            except:
                has_resolution_status = False
                has_plate_status = False
            
            if has_resolution_status and has_plate_status:
                # Query với tất cả các cột mới (bao gồm plate_status)
                query = """
                    INSERT INTO violations
                    (plate, speed, speed_limit, time, image, plate_image, video,
                     status, vehicle_class, track_id, validation_state, sharpness, confidence,
                     manual_review_required, manual_review_flag, manual_review_status, original_ocr_text,
                     ocr_confidence, plate_recognition_method, violation_confirmed,
                     resolution_status, plate_status, ocr_suggestions, manual_review_notes)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """
            elif has_resolution_status:
                # Query với resolution_status nhưng chưa có plate_status
                query = """
                    INSERT INTO violations
                    (plate, speed, speed_limit, time, image, plate_image, video,
                     status, vehicle_class, track_id, validation_state, sharpness, confidence,
                     manual_review_required, manual_review_status, original_ocr_text,
                     ocr_confidence, plate_recognition_method, violation_confirmed,
                     resolution_status, ocr_suggestions, manual_review_notes)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """
            else:
                # Query không có các cột mới (fallback)
                logger.warning("resolution_status column not found, using fallback query")
                query = """
                    INSERT INTO violations
                    (plate, speed, speed_limit, time, image, plate_image, video,
                     status, vehicle_class, track_id, validation_state, sharpness, confidence,
                     manual_review_required, manual_review_status, original_ocr_text,
                     ocr_confidence, plate_recognition_method, violation_confirmed)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """

            if has_resolution_status and has_plate_status:
                values = (
                    plate_text,  # Can be NULL for MANUAL_REQUIRED
                    violation_data.get('speed', 0),
                    violation_data.get('speed_limit', 40),
                    violation_data.get('timestamp', datetime.now()),
                    violation_data.get('vehicle_image'),
                    violation_data.get('plate_image'),
                    violation_data.get('video'),
                    'pending',
                    violation_data.get('vehicle_class', 'unknown'),
                    violation_data.get('track_id'),
                    violation_data.get('validation_state', 'no_plate'),
                    violation_data.get('sharpness', 0.0),
                    violation_data.get('confidence', 0.0),
                    # Plate resolution fields
                    violation_data.get('manual_review_required', False),
                    violation_data.get('manual_review_flag', violation_data.get('manual_review_required', False)),  # Alias
                    violation_data.get('manual_review_status'),
                    violation_data.get('original_ocr_text'),
                    violation_data.get('ocr_confidence', 0.0),
                    violation_data.get('plate_recognition_method', 'ocr_auto'),
                    violation_data.get('violation_confirmed', True),
                    # New fields for plate resolution
                    violation_data.get('resolution_status', 'manual_required'),
                    plate_status,  # AUTO_CONFIRMED or MANUAL_REQUIRED
                    violation_data.get('ocr_suggestions'),  # JSON array of suggestions
                    violation_data.get('manual_review_notes')  # JSON with full analysis
                )
            elif has_resolution_status:
                values = (
                    plate_text,  # Can be NULL for AUTO_SUGGESTED and MANUAL_REQUIRED
                    violation_data.get('speed', 0),
                    violation_data.get('speed_limit', 40),
                    violation_data.get('timestamp', datetime.now()),
                    violation_data.get('vehicle_image'),
                    violation_data.get('plate_image'),
                    violation_data.get('video'),
                    'pending',
                    violation_data.get('vehicle_class', 'unknown'),
                    violation_data.get('track_id'),
                    violation_data.get('validation_state', 'no_plate'),
                    violation_data.get('sharpness', 0.0),
                    violation_data.get('confidence', 0.0),
                    # Plate resolution fields
                    violation_data.get('manual_review_required', False),
                    violation_data.get('manual_review_status'),
                    violation_data.get('original_ocr_text'),
                    violation_data.get('ocr_confidence', 0.0),
                    violation_data.get('plate_recognition_method', 'ocr_auto'),
                    violation_data.get('violation_confirmed', True),
                    # New fields for plate resolution
                    violation_data.get('resolution_status', 'manual_required'),
                    violation_data.get('ocr_suggestions'),  # JSON array of suggestions
                    violation_data.get('manual_review_notes')  # JSON with full analysis
                )
            else:
                # Fallback values (không có các cột mới)
                values = (
                    plate_text,
                    violation_data.get('speed', 0),
                    violation_data.get('speed_limit', 40),
                    violation_data.get('timestamp', datetime.now()),
                    violation_data.get('vehicle_image'),
                    violation_data.get('plate_image'),
                    violation_data.get('video'),
                    'pending',
                    violation_data.get('vehicle_class', 'unknown'),
                    violation_data.get('track_id'),
                    violation_data.get('validation_state', 'no_plate'),
                    violation_data.get('sharpness', 0.0),
                    violation_data.get('confidence', 0.0),
                    # Plate resolution fields
                    violation_data.get('manual_review_required', False),
                    violation_data.get('manual_review_status'),
                    violation_data.get('original_ocr_text'),
                    violation_data.get('ocr_confidence', 0.0),
                    violation_data.get('plate_recognition_method', 'ocr_auto'),
                    violation_data.get('violation_confirmed', True)
                )

            max_retries = 3
            for attempt in range(max_retries):
                try:
                    cursor = connection.cursor()
                    cursor.execute(query, values)
                    connection.commit()
                    violation_id = cursor.lastrowid
                    cursor.close()

                    if is_direct_connection:
                        connection.close()

                    logger.info(f"Saved violation ID={violation_id}")
                    return violation_id

                except Exception as exec_error:
                    error_code = getattr(exec_error, 'args', [None])[0] if hasattr(exec_error, 'args') else None

                    if (error_code == 2006 or error_code == 1452) and attempt < max_retries - 1:
                        try:
                            if 'cursor' in locals():
                                cursor.close()
                        except:
                            pass

                        if connection:
                            try:
                                connection.close()
                            except:
                                pass

                        import time
                        time.sleep(0.2 * (attempt + 1))
                        connection = self._get_direct_connection()
                        if connection is None:
                            continue

                        is_direct_connection = True
                    else:
                        if 'cursor' in locals():
                            try:
                                cursor.close()
                            except:
                                pass
                        raise exec_error

        except Exception as e:
            logger.error(f"Save error: {e}", exc_info=True)

            if is_direct_connection and connection:
                try:
                    connection.close()
                except:
                    pass
            return None

    def update_violation_plate(self, violation_id, plate_text, plate_image_path=None, vehicle_image_path=None):
        if self.mysql is None:
            return False

        if not violation_id:
            return False

        try:
            connection = self._get_direct_connection()
            if connection is None:
                return False

            try:
                connection.ping(True)
            except Exception as ping_error:
                try:
                    connection.close()
                except:
                    pass
                connection = self._get_direct_connection()
                if connection is None:
                    return False

            cursor = connection.cursor()

            update_fields = ["plate = %s", "status = 'completed'"]
            values = [plate_text]

            if plate_image_path:
                update_fields.append("plate_image = %s")
                values.append(plate_image_path)

            if vehicle_image_path:
                update_fields.append("image = %s")
                values.append(vehicle_image_path)

            values.append(violation_id)

            query = f"""
                UPDATE violations
                SET {', '.join(update_fields)}
                WHERE id = %s
            """

            max_retries = 3
            for attempt in range(max_retries):
                try:
                    cursor.execute(query, tuple(values))
                    connection.commit()

                    rows_affected = cursor.rowcount
                    cursor.close()
                    connection.close()

                    if rows_affected > 0:
                        logger.info(f"Updated violation {violation_id}: plate={plate_text}")
                        return True
                    else:
                        return False

                except Exception as exec_error:
                    error_code = getattr(exec_error, 'args', [None])[0] if hasattr(exec_error, 'args') else None

                    if error_code == 2006 and attempt < max_retries - 1:
                        try:
                            cursor.close()
                            connection.close()
                        except:
                            pass

                        import time
                        time.sleep(0.2 * (attempt + 1))
                        connection = self._get_direct_connection()
                        if connection is None:
                            continue

                        cursor = connection.cursor()
                    else:
                        raise exec_error

        except Exception as e:
            logger.error(f"Update plate error: {e}", exc_info=True)
            return False

    def update_violation_status(self, violation_id, status):
        if self.mysql is None:
            return False

        try:
            connection = self._get_direct_connection()
            if connection is None:
                if not hasattr(self.mysql, 'connection') or self.mysql.connection is None:
                    return False
                cursor = self.mysql.connection.cursor()
                
                # Check if telegram_sent column exists
                cursor.execute("SHOW COLUMNS FROM violations LIKE 'telegram_sent'")
                has_telegram_sent = cursor.fetchone() is not None
                
                if has_telegram_sent and status == 'sent':
                    # Update telegram_sent status
                    cursor.execute(
                        "UPDATE violations SET status = %s, telegram_sent = 1, telegram_sent_at = NOW() WHERE id = %s",
                        (status, violation_id)
                    )
                else:
                    cursor.execute(
                        "UPDATE violations SET status = %s WHERE id = %s",
                        (status, violation_id)
                    )
                self.mysql.connection.commit()
                cursor.close()
            else:
                cursor = connection.cursor()
                
                # Check if telegram_sent column exists
                cursor.execute("SHOW COLUMNS FROM violations LIKE 'telegram_sent'")
                has_telegram_sent = cursor.fetchone() is not None
                
                if has_telegram_sent and status == 'sent':
                    # Update telegram_sent status
                    cursor.execute(
                        "UPDATE violations SET status = %s, telegram_sent = 1, telegram_sent_at = NOW() WHERE id = %s",
                        (status, violation_id)
                    )
                else:
                    cursor.execute(
                        "UPDATE violations SET status = %s WHERE id = %s",
                        (status, violation_id)
                    )
                connection.commit()
                cursor.close()
                connection.close()

            return True

        except Exception as e:
            logger.error(f"Update status error: {e}", exc_info=True)
            return False

    def get_violations(self, limit=100, plate=None, from_date=None, to_date=None):
        if self.mysql is None:
            logger.warning("get_violations: MySQL chưa cấu hình. Kiểm tra file .env")
            return []

        try:
            if not hasattr(self.mysql, 'connection') or self.mysql.connection is None:
                logger.warning("get_violations: Không có connection trong request")
                return []

            cursor = self.mysql.connection.cursor()

            # Kiểm tra xem có cột plate_status không
            try:
                cursor.execute("SHOW COLUMNS FROM violations LIKE 'plate_status'")
                has_plate_status = cursor.fetchone() is not None
            except:
                has_plate_status = False
            
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
                    WHERE 1=1
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
                    WHERE 1=1
                """
            params = []

            if plate:
                query += " AND v.plate LIKE %s"
                params.append(f"%{plate}%")

            if from_date:
                query += " AND v.time >= %s"
                params.append(from_date)

            if to_date:
                query += " AND v.time <= %s"
                params.append(to_date)

            query += " ORDER BY v.time DESC LIMIT %s"
            params.append(limit)

            cursor.execute(query, params)

            columns = [desc[0] for desc in cursor.description]
            results = []
            for row in cursor.fetchall():
                result_dict = dict(zip(columns, row))
                
                # Normalize plate field - replace "N/A" with NULL
                if 'plate_normalized' in result_dict:
                    # Use normalized plate if available
                    result_dict['plate'] = result_dict.get('plate_normalized')
                else:
                    # Fallback: normalize plate directly
                    plate_value = result_dict.get('plate')
                    if plate_value and str(plate_value).strip().upper() in ['N/A', 'NULL', 'UNKNOWN', 'NONE', 'NAN', '']:
                        result_dict['plate'] = None
                
                # Ensure plate_status is set
                if 'plate_status' not in result_dict or not result_dict.get('plate_status'):
                    if not result_dict.get('plate'):
                        result_dict['plate_status'] = 'MANUAL_REQUIRED'
                    else:
                        result_dict['plate_status'] = 'AUTO_CONFIRMED'
                
                results.append(result_dict)
                
                # Debug: Log sample violation data (first result only)
                if len(results) == 1:
                    logger.debug(f"Sample violation: Plate={result_dict.get('plate')}, "
                               f"Status={result_dict.get('plate_status')}, "
                               f"Image={result_dict.get('image')}, "
                               f"Plate Image={result_dict.get('plate_image')}, "
                               f"Video={result_dict.get('video')}")

            cursor.close()
            logger.debug(f"Total violations returned: {len(results)}")
            return results

        except Exception as e:
            logger.error(f"get_violations error: {e}. Kiểm tra MySQL và bảng violations.", exc_info=True)
            return []

    def get_owner(self, plate):
        if self.mysql is None:
            return None

        cursor = None
        try:
            if not hasattr(self.mysql, 'connection') or self.mysql.connection is None:
                return None
            cursor = self.mysql.connection.cursor()
            cursor.execute(
                "SELECT * FROM vehicle_owner WHERE plate = %s",
                (plate,)
            )
            row = cursor.fetchone()

            if row:
                columns = [desc[0] for desc in cursor.description]
                cursor.close()
                return dict(zip(columns, row))

            cursor.close()
            return None

        except Exception as e:
            logger.error(f"Owner query error: {e}", exc_info=True)
            if cursor:
                try:
                    cursor.close()
                except:
                    pass
            return None

    def get_all_owners(self, plate=None, owner_name=None, address=None, phone=None):
        if self.mysql is None:
            return []

        try:
            if not hasattr(self.mysql, 'connection') or self.mysql.connection is None:
                return []

            cursor = self.mysql.connection.cursor()

            query = """
                SELECT plate, owner_name, address, phone
                FROM vehicle_owner
                WHERE 1=1
            """
            params = []

            if plate:
                query += " AND plate LIKE %s"
                params.append(f"%{plate}%")

            if owner_name:
                query += " AND owner_name LIKE %s"
                params.append(f"%{owner_name}%")

            if address:
                query += " AND address LIKE %s"
                params.append(f"%{address}%")

            if phone:
                query += " AND phone LIKE %s"
                params.append(f"%{phone}%")

            query += " ORDER BY plate ASC"

            cursor.execute(query, params)

            columns = [desc[0] for desc in cursor.description]
            results = []
            for row in cursor.fetchall():
                results.append(dict(zip(columns, row)))

            cursor.close()
            return results

        except Exception as e:
            logger.error(f"get_all_owners error: {e}", exc_info=True)
            return []

    def get_today_stats(self):
        if self.mysql is None:
            logger.warning("get_today_stats: MySQL chưa cấu hình (mysql is None). Tạo file .env với MYSQL_HOST, MYSQL_USER, MYSQL_PASSWORD, MYSQL_DB")
            return {'total': 0, 'manual_review': 0, 'avg_speed': 0}

        try:
            if not hasattr(self.mysql, 'connection') or self.mysql.connection is None:
                logger.warning("get_today_stats: Không có connection trong request")
                return {'total': 0, 'manual_review': 0, 'avg_speed': 0}

            cursor = self.mysql.connection.cursor()

            # Tổng vi phạm hôm nay
            cursor.execute("""
                SELECT COUNT(*) FROM violations
                WHERE DATE(time) = CURDATE()
            """)
            result = cursor.fetchone()
            total = result[0] if result else 0

            # Số vi phạm cần manual review (manual_review_required = TRUE)
            cursor.execute("""
                SELECT COUNT(*) FROM violations
                WHERE DATE(time) = CURDATE()
                AND manual_review_required = TRUE
            """)
            result = cursor.fetchone()
            manual_review = result[0] if result else 0

            cursor.execute("""
                SELECT AVG(speed) FROM violations
                WHERE DATE(time) = CURDATE()
            """)
            result = cursor.fetchone()
            avg_speed = result[0] if result and result[0] is not None else 0

            cursor.close()

            return {
                'total': total,
                'manual_review': manual_review,
                'avg_speed': round(avg_speed, 1)
            }

        except Exception as e:
            logger.error(f"get_today_stats error: {e}. Kiểm tra MySQL đang chạy, bảng violations tồn tại, và .env đúng.", exc_info=True)
            return {'total': 0, 'manual_review': 0, 'avg_speed': 0}
