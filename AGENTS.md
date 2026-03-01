# AGENTS.md

## Cursor Cloud specific instructions

### Overview
This is a **Plate Violation Detection System** (Vietnamese: Hệ thống phát hiện vi phạm tốc độ và nhận diện biển số xe) — a Python/Flask web app for automated traffic speed violation detection and license plate recognition using YOLO, ByteTrack, and FastALPR. It stores data in MySQL.

### Services

| Service | How to run | Notes |
|---------|-----------|-------|
| **MySQL** | `sudo service mysql start` | Must run before the Flask app. Socket dir needs `chmod 755 /var/run/mysqld/` after service start if access is denied. |
| **Flask app** | `python3 app.py` (from repo root) | Runs on port 5000. Default credentials: `admin` / `123`. |

### Key gotchas

- **No GPU in cloud VM**: The app defaults to `DEVICE='cuda'` in `config/config.py`. The ML detection modules (YOLO, FastALPR) are **lazy-loaded** only when a video is uploaded, so the web UI works fine without a GPU. Video processing will fail at runtime without changing `DEVICE` to `'cpu'`.
- **MySQL socket permissions**: After `sudo service mysql start`, the `/var/run/mysqld/` directory may have `drwx------` permissions (owned by `mysql`). Run `sudo chmod 755 /var/run/mysqld/` to allow the Python process to connect via the Unix socket.
- **MySQL auth**: Root user must use `mysql_native_password` plugin (not `caching_sha2_password`) for `mysqlclient` to connect with an empty password. Set via: `sudo mysql -e "ALTER USER 'root'@'localhost' IDENTIFIED WITH mysql_native_password BY ''; FLUSH PRIVILEGES;"`
- **`fast-alpr` version**: `requirements.txt` specifies `>=1.0.0` but only `0.3.0` is available on PyPI. Install with `pip3 install fast-alpr` (latest).
- **Migration SQL syntax**: Some migration files use `ADD COLUMN IF NOT EXISTS` (MariaDB syntax, not MySQL 8.0). The full `database/schema.sql` already includes all columns, so this is only an issue if running migrations on a fresh schema.
- **Flask-MySQLdb connection warning**: On startup, a warning `'NoneType' object has no attribute 'cursor'` appears because the DB connection test runs outside Flask's app context. This is harmless; database queries work correctly within request handlers.

### Standard commands
See `README.md` for setup and run instructions. Key commands:
- **Lint**: `flake8 --max-line-length=120 --exclude=venv,uploads,__pycache__ .` (no lint config in repo)
- **Run app**: `python3 app.py`
- **DB schema**: `sudo mysql -u root < database/schema.sql`
- **DB migrations**: `python3 run_migration.py`
