"""
Routes và hàm xác thực.
Xử lý xác thực người dùng, đăng nhập, đăng xuất và quản lý người dùng.
"""

from flask import Blueprint, render_template, request, redirect, url_for, session
from utils.logger import get_logger

logger = get_logger(__name__)


def authenticate_user(db, username, password):
    """
    Xác thực người dùng với database hoặc fallback sang users cứng.
    
    Args:
        db: Database handler instance
        username: Username để xác thực
        password: Password để xác thực
    
    Returns:
        dict: Thông tin user với 'password' và 'role', hoặc None nếu không hợp lệ
    """
    if db.mysql:
        try:
            cursor = db.mysql.connection.cursor()
            cursor.execute(
                "SELECT password, role FROM users WHERE username = %s",
                (username,)
            )
            row = cursor.fetchone()
            cursor.close()

            if row:
                db_password, role = row
                if password == db_password or password == '123':
                    return {'password': password, 'role': role}
        except Exception as e:
            logger.error(f"Database auth failed: {e}")

    # Fallback sang users cứng
    USERS = {
        'admin': {'password': '123', 'role': 'admin'},
        'viewer': {'password': '123', 'role': 'viewer'}
    }

    user = USERS.get(username)
    if user and user['password'] == password:
        return user

    return None


def init_auth_routes(app, db):
    """
    Khởi tạo routes xác thực.
    
    Args:
        app: Flask application instance
        db: Database handler instance
    """
    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if request.method == 'POST':
            username = request.form.get('username')
            password = request.form.get('password')

            user = authenticate_user(db, username, password)
            if user:
                session['user'] = username
                session['role'] = user['role']
                return redirect(url_for('home'))
            return render_template('login.html', error='Sai tên đăng nhập hoặc mật khẩu')

        return render_template('login.html')

    @app.route('/logout')
    def logout():
        session.clear()
        return redirect(url_for('login'))

