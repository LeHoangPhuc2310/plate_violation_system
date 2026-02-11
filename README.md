# Plate Violation Detection System

Hệ thống phát hiện vi phạm tốc độ và nhận diện biển số xe. Flask, YOLO, ByteTrack, FastALPR, MySQL.

## Yêu cầu

- Python 3.10+
- MySQL
- Trong project: xem `requirements.txt`

## Cài đặt

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

Tạo database và user MySQL, sau đó:

```bash
copy .env.example .env
# Sửa .env: MYSQL_HOST, MYSQL_USER, MYSQL_PASSWORD, MYSQL_DB

python run_migration.py
python app.py
```

Mở http://localhost:5000. Đăng nhập mặc định: `admin` / `123`, `viewer` / `123`.

## Cấu hình (.env)

- `SECRET_KEY`, `FLASK_ENV`
- `MYSQL_HOST`, `MYSQL_USER`, `MYSQL_PASSWORD`, `MYSQL_DB`
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` (tùy chọn)

Cấu hình khác (tốc độ, YOLO, cooldown, video vi phạm) trong `config/config.py`.

## Cấu trúc code

| Thư mục / file | Nội dung |
|----------------|----------|
| `app.py` | Entry: Flask app, đăng ký routes, lazy load detector/tracker/ALPR/violation/processor |
| `config/config.py` | Config: MySQL, Telegram, YOLO, SPEED_LIMIT, LINE1_Y/LINE2_Y, REAL_DISTANCE, UPLOAD_FOLDER, VIOLATION_* |
| `routes/auth.py` | `/login`, `/logout` |
| `routes/main.py` | `/`, `/home`, `/upload_video`, `/stop_video_upload`, `/toggle_pause`, `/toggle_loop`, `/get_video_status`, `/video_feed`, `/video_feed_smooth`, `/detection_stream` |
| `routes/violations.py` | `/history`, `/manual_review`, `/violations`, `/violations/<path:filename>` |
| `routes/admin.py` | `/admin/vehicles`, `/edit_owner/<plate>`, `/delete/<plate>` |
| `routes/api.py` | `/autocomplete`, `/health`, `/health/dashboard`, `/video_demo/<path>`, `/api/manual_review/*` (stats, pending, get, claim, update_plate, reject) |
| `detector/` | YOLO vehicle detection |
| `tracker/` | ByteTrack |
| `speed/` | SpeedCalculator (LINE1, LINE2, real distance) |
| `alpr/` | PlateReader, validator, format, voter |
| `video_processor/` | VideoProcessor, track buffer, shared memory |
| `violation/` | ViolationHandler (lưu ảnh, video, cooldown) |
| `database/` | DatabaseHandler, schema.sql, migrations |
| `telegram/` | TelegramNotifier |
| `utils/` | logger, helpers (format_plate, format_time_vietnam, login_required, admin_required) |
| `templates/` | base, index, login, home, view_violations, manual_review, admin_vehicle, edit_owner, health_dashboard |
| `static/` | css (design-system.css), img |
| `run_migration.py` | Chạy migrations |

## API / Routes chính

- **Auth:** POST `/login`, GET `/logout`
- **Video:** POST `/upload_video`, GET `/video_feed`, GET `/video_feed_smooth`, GET `/detection_stream`, GET `/stop_video_upload`, POST `/toggle_pause`, POST `/toggle_loop`, GET `/get_video_status`
- **Vi phạm:** GET `/history`, GET `/violations`, GET `/violations/<path>`, GET `/manual_review`
- **Admin:** GET `/admin/vehicles`, GET/POST `/edit_owner/<plate>`, GET `/delete/<plate>`
- **API:** GET `/autocomplete`, GET `/health`, GET `/health/dashboard`, GET `/video_demo/<path>`, các GET/POST `/api/manual_review/*`

## License

MIT
