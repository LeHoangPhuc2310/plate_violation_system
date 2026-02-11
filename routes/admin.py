"""
Routes admin cho quản lý xe.
Xử lý routes chỉ dành cho admin để quản lý chủ xe.
"""

from flask import render_template, request, redirect, url_for
from utils.logger import get_logger
from utils.helpers import admin_required

logger = get_logger(__name__)


def init_admin_routes(app, db):
    """
    Khởi tạo routes admin.
    
    Args:
        app: Flask application instance
        db: Database handler instance
    """
    @app.route('/admin/vehicles')
    @admin_required
    def manage_vehicle():
        plate = request.args.get('plate')
        owner_name = request.args.get('owner_name')
        address = request.args.get('address')
        phone = request.args.get('phone')

        data = db.get_all_owners(
            plate=plate,
            owner_name=owner_name,
            address=address,
            phone=phone
        )

        logger.debug(f"manage_vehicle: Found {len(data)} owners")

        return render_template('admin_vehicle.html',
                             data=data,
                             plate=plate,
                             owner_name=owner_name,
                             address=address,
                             phone=phone)

    @app.route('/edit_owner/<plate>', methods=['GET', 'POST'])
    @admin_required
    def edit_owner(plate):
        if request.method == 'POST':
            owner_name = request.form.get('owner_name')
            address = request.form.get('address')
            phone = request.form.get('phone')

            if db.mysql:
                try:
                    cursor = db.mysql.connection.cursor()
                    cursor.execute("SELECT * FROM vehicle_owner WHERE plate = %s", (plate,))
                    if cursor.fetchone():
                        cursor.execute("""
                            UPDATE vehicle_owner
                            SET owner_name = %s, address = %s, phone = %s
                            WHERE plate = %s
                        """, (owner_name, address, phone, plate))
                    else:
                        cursor.execute("""
                            INSERT INTO vehicle_owner (plate, owner_name, address, phone)
                            VALUES (%s, %s, %s, %s)
                        """, (plate, owner_name, address, phone))
                    db.mysql.connection.commit()
                    cursor.close()
                except Exception as e:
                    logger.error(f"Edit owner error: {e}", exc_info=True)

            return redirect(url_for('manage_vehicle'))

        owner = db.get_owner(plate) or {'plate': plate}
        return render_template('edit_owner.html', owner=owner)

    @app.route('/delete/<plate>')
    @admin_required
    def delete_owner(plate):
        if db.mysql:
            try:
                cursor = db.mysql.connection.cursor()
                cursor.execute("DELETE FROM vehicle_owner WHERE plate = %s", (plate,))
                db.mysql.connection.commit()
                cursor.close()
            except Exception as e:
                logger.error(f"Delete owner error: {e}", exc_info=True)

        return redirect(url_for('manage_vehicle'))

