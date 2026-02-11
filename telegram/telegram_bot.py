import os
import requests
import warnings
from datetime import datetime
from utils.logger import get_logger

logger = get_logger(__name__)


class TelegramNotifier:

    def __init__(self, bot_token=None, chat_id=None):
        # Development defaults (chỉ dùng khi không có .env)
        # Production: BẮT BUỘC phải set trong .env file
        default_bot_token = '8306836477:AAEJSaTQg2Pu7tZQMEHjoDPUSIC3Mz0QtGY'
        default_chat_id = '6680799636'
        
        self.bot_token = bot_token or os.getenv('TELEGRAM_BOT_TOKEN', default_bot_token)
        self.chat_id = chat_id or os.getenv('TELEGRAM_CHAT_ID', default_chat_id)
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}"

        # Security: Cảnh báo nếu dùng default values trong production
        flask_env = os.getenv('FLASK_ENV', 'development')
        if flask_env == 'production':
            if self.bot_token == default_bot_token:
                warnings.warn(
                    "SECURITY WARNING: Using default TELEGRAM_BOT_TOKEN in production! "
                    "Please set TELEGRAM_BOT_TOKEN in .env file.",
                    UserWarning
                )
            if self.chat_id == default_chat_id:
                warnings.warn(
                    "SECURITY WARNING: Using default TELEGRAM_CHAT_ID in production! "
                    "Please set TELEGRAM_CHAT_ID in .env file.",
                    UserWarning
                )

        if self.bot_token and self.chat_id:
            logger.info("Telegram bot initialized")
        else:
            logger.warning("Telegram bot not configured")

    def send_violation(self, violation_data, vehicle_image_path=None, plate_image_path=None, video_path=None):
        if not self.bot_token or not self.chat_id:
            return False

        try:
            plate = violation_data.get('plate_text', 'UNKNOWN')
            speed = violation_data.get('speed', 0)
            limit = violation_data.get('speed_limit', 40)
            over = speed - limit
            timestamp = violation_data.get('timestamp', datetime.now())

            if isinstance(timestamp, datetime):
                time_str = timestamp.strftime("%d/%m/%Y %H:%M:%S")
            else:
                time_str = str(timestamp)

            message = f"""
🚨 *PHÁT HIỆN VI PHẠM TỐC ĐỘ*

🚗 *Biển số:* `{plate}`
⚡ *Tốc độ:* {speed:.1f} km/h
🚫 *Giới hạn:* {limit} km/h
📈 *Vượt quá:* {over:.1f} km/h
🕐 *Thời gian:* {time_str}

_Hệ thống giám sát tốc độ tự động_
            """

            self._send_message(message)

            if vehicle_image_path and os.path.exists(vehicle_image_path):
                self._send_photo(vehicle_image_path, "Ảnh phương tiện vi phạm")

            if plate_image_path and os.path.exists(plate_image_path):
                self._send_photo(plate_image_path, "Ảnh biển số")

            if video_path and os.path.exists(video_path):
                self._send_video(video_path, f"Video vi phạm: {plate}")

            logger.info(f"Sent violation: {plate} @ {speed:.1f} km/h")
            return True

        except Exception as e:
            print(f"[TELEGRAM] Send error: {e}")
            return False

    def _send_message(self, text):
        url = f"{self.base_url}/sendMessage"
        payload = {
            'chat_id': self.chat_id,
            'text': text,
            'parse_mode': 'Markdown'
        }
        response = requests.post(url, data=payload, timeout=10)
        return response.ok

    def _send_photo(self, photo_path, caption=""):
        url = f"{self.base_url}/sendPhoto"
        with open(photo_path, 'rb') as f:
            files = {'photo': f}
            data = {
                'chat_id': self.chat_id,
                'caption': caption
            }
            response = requests.post(url, data=data, files=files, timeout=30)
        return response.ok

    def _send_video(self, video_path, caption=""):
        url = f"{self.base_url}/sendVideo"
        file_size = os.path.getsize(video_path)
        # Telegram limit: 50MB for videos
        max_size = 50 * 1024 * 1024
        
        if file_size > max_size:
            logger.warning(f"Video too large ({file_size / 1024 / 1024:.1f}MB > 50MB), skipping")
            return False
        
        with open(video_path, 'rb') as f:
            files = {'video': f}
            data = {
                'chat_id': self.chat_id,
                'caption': caption
            }
            response = requests.post(url, data=data, files=files, timeout=60)
        return response.ok

    def send_violation_simple(self, plate_text, speed, image_path):
        if not self.bot_token or not self.chat_id:
            return False

        try:
            time_str = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

            message = f"""
🚨 *VI PHAM TOC DO*

🚗 Bien so: `{plate_text}`
⚡ Toc do: {speed:.1f} km/h
🕐 Thoi gian: {time_str}
            """

            self._send_message(message)

            if image_path and os.path.exists(image_path):
                self._send_photo(image_path, f"Bien so: {plate_text}")

            return True

        except Exception as e:
            print(f"[TELEGRAM] Send error: {e}")
            return False

    def test_connection(self):
        if not self.bot_token or not self.chat_id:
            return False

        try:
            url = f"{self.base_url}/getMe"
            response = requests.get(url, timeout=10)
            if response.ok:
                data = response.json()
                bot_name = data.get('result', {}).get('username', 'unknown')
                logger.info(f"Connected as @{bot_name}")
                return True
        except:
            pass
        return False
