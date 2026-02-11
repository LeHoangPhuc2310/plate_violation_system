"""
Chạy database migration.
Chạy tất cả migrations theo thứ tự đúng.
Migrations nằm trong thư mục database/migrations/.
"""

import os
import sys
from pathlib import Path
from utils.logger import get_logger, setup_logging
from config.config import Config

# Thử dùng MySQLdb trước (từ mysqlclient), fallback sang mysql.connector nếu không có
try:
    import MySQLdb
    USE_MYSQL_CONNECTOR = False
except ImportError:
    try:
        import mysql.connector
        from mysql.connector import Error
        USE_MYSQL_CONNECTOR = True
    except ImportError:
        # Logger chưa khởi tạo, dùng print
        print("ERROR: Neither MySQLdb (mysqlclient) nor mysql.connector is available.")
        print("Please install mysqlclient: pip install mysqlclient")
        print("Or install mysql-connector-python: pip install mysql-connector-python")
        sys.exit(1)

# Setup logging
setup_logging()
logger = get_logger(__name__)


def get_migration_files():
    """Lấy danh sách file migration theo thứ tự."""
    migrations_dir = Path('database/migrations')
    
    # File migration theo thứ tự
    ordered_migrations = [
        '001_add_manual_review_system.sql',
        '002_add_plate_resolution_fields.sql',
        '003_add_plate_status_and_audit_log.sql',
        '004_fix_na_plates.sql',
        '005_add_telegram_sent_status.sql',
        '006_fill_vehicle_owner_data.sql',
        'add_confidence_column.sql',
        'add_validation_state.sql'
    ]
    
    migration_files = []
    for migration in ordered_migrations:
        file_path = migrations_dir / migration
        if file_path.exists():
            migration_files.append(file_path)
        else:
            logger.warning(f"Migration file not found: {file_path}")
    
    return migration_files


def read_sql_file(file_path):
    """Đọc file SQL và tách thành các câu lệnh riêng."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Tách theo dấu chấm phẩy, nhưng giữ nguyên khối DELIMITER
        statements = []
        current_statement = ""
        in_delimiter_block = False
        
        for line in content.split('\n'):
            line = line.strip()
            
            # Bỏ qua comment và dòng trống
            if not line or line.startswith('--'):
                continue
            
            # Kiểm tra lệnh DELIMITER
            if line.upper().startswith('DELIMITER'):
                in_delimiter_block = True
                continue
            
            current_statement += line + '\n'
            
            # Kết thúc câu lệnh (dấu chấm phẩy hoặc kết thúc khối DELIMITER)
            if ';' in line and not in_delimiter_block:
                if current_statement.strip():
                    statements.append(current_statement.strip())
                current_statement = ""
            elif in_delimiter_block and line.endswith('$$'):
                if current_statement.strip():
                    statements.append(current_statement.strip())
                current_statement = ""
                in_delimiter_block = False
        
        # Thêm câu lệnh còn lại
        if current_statement.strip():
            statements.append(current_statement.strip())
        
        return statements
    except Exception as e:
        logger.error(f"Error reading SQL file {file_path}: {e}")
        return []


def run_migration(migration_file, connection):
    """Chạy một file migration."""
    logger.info(f"Running migration: {migration_file.name}")
    
    statements = read_sql_file(migration_file)
    
    if not statements:
        logger.warning(f"No SQL statements found in {migration_file.name}")
        return False
    
    cursor = connection.cursor()
    
    try:
        for i, statement in enumerate(statements, 1):
            if not statement.strip():
                continue
            
            try:
                # Thực thi câu lệnh
                cursor.execute(statement)
                logger.debug(f"  Statement {i}/{len(statements)} executed successfully")
            except Exception as e:
                # Một số lỗi là bình thường (ví dụ: cột đã tồn tại)
                error_msg = str(e).lower()
                if any(keyword in error_msg for keyword in ['already exists', 'duplicate', 'unknown column']):
                    logger.warning(f"  Statement {i}/{len(statements)} skipped (expected): {e}")
                else:
                    logger.error(f"  Statement {i}/{len(statements)} failed: {e}")
                    raise
        
        # Commit tất cả câu lệnh
        connection.commit()
        logger.info(f"✓ Migration {migration_file.name} completed successfully")
        return True
        
    except Exception as e:
        connection.rollback()
        logger.error(f"✗ Migration {migration_file.name} failed: {e}")
        return False
    finally:
        cursor.close()


def main():
    """Hàm chính chạy migration."""
    logger.info("=" * 60)
    logger.info("DATABASE MIGRATION RUNNER")
    logger.info("=" * 60)
    
    # Lấy kết nối database
    try:
        if USE_MYSQL_CONNECTOR:
            connection = mysql.connector.connect(
                host=Config.MYSQL_HOST,
                user=Config.MYSQL_USER,
                password=Config.MYSQL_PASSWORD,
                database=Config.MYSQL_DB,
                charset='utf8mb4',
                collation='utf8mb4_unicode_ci'
            )
        else:
            connection = MySQLdb.connect(
                host=Config.MYSQL_HOST,
                user=Config.MYSQL_USER,
                passwd=Config.MYSQL_PASSWORD,
                db=Config.MYSQL_DB,
                charset='utf8mb4'
            )
        logger.info(f"Connected to database: {Config.MYSQL_DB}")
    except Exception as e:
        logger.error(f"Failed to connect to database: {e}")
        sys.exit(1)
    
    # Lấy file migration
    migration_files = get_migration_files()
    
    if not migration_files:
        logger.warning("No migration files found!")
        connection.close()
        return
    
    logger.info(f"Found {len(migration_files)} migration file(s)")
    logger.info("")
    
    # Chạy migrations
    success_count = 0
    for migration_file in migration_files:
        if run_migration(migration_file, connection):
            success_count += 1
        logger.info("")
    
    # Tóm tắt
    logger.info("=" * 60)
    logger.info(f"MIGRATION SUMMARY: {success_count}/{len(migration_files)} migrations completed")
    logger.info("=" * 60)
    
    connection.close()


if __name__ == '__main__':
    main()

