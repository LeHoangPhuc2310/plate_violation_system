# Quick Fix cho EC2

## Bước 1: Pull code mới

```bash
cd ~/plate_project
git pull origin main
```

## Bước 2: Chạy app

### Option 1: Dùng script (Khuyến nghị)

```bash
chmod +x run-app.sh
PORT=5001 ./run-app.sh
```

### Option 2: Chạy trực tiếp

```bash
# Unset các biến có thể conflict
unset FLASK_DEBUG
unset FLASK_ENV
unset FLASK_APP

# Set lại
export FLASK_DEBUG=0
export FLASK_ENV=production
export PORT=5001

# Chạy
python3 app.py
```

### Option 3: Kiểm tra file .env

```bash
# Kiểm tra xem có FLASK_DEBUG trong .env không
grep FLASK .env

# Nếu có, sửa file .env
nano .env
# Comment hoặc xóa dòng: FLASK_DEBUG=True

# Sau đó chạy
PORT=5001 python3 app.py
```

## Bước 3: Kiểm tra

Sau khi chạy, bạn sẽ thấy:
```
============================================================
Starting Plate Violation System
============================================================
Host: 0.0.0.0
Port: 5001
Debug mode: False (FORCED OFF)
Environment: production (FORCED)
PORT from env: 5001
============================================================

🚀 Server starting on http://0.0.0.0:5001
Press CTRL+C to quit
```

Test:
```bash
curl http://localhost:5001/health
```

