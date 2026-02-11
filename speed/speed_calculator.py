import cv2
from typing import Optional, Tuple, Dict
from utils.logger import get_logger

logger = get_logger(__name__)


class SpeedCalculator:
    """
    Tính tốc độ bằng phương pháp Two-Line với state machine.

    State machine:
    - waiting: Chờ xe di chuyển ổn định
    - ready_to_measure: Đã ổn định, chờ qua LINE1
    - crossed_line1: Đã qua LINE1, đang đến LINE2
    - completed: Đã qua LINE2, tính tốc độ xong

    Chống spawn: Yêu cầu track tồn tại MIN_TRACK_AGE frames và di chuyển MIN_MOVEMENT_PIXELS.
    """

    def __init__(self, line1_y: int, line2_y: int, real_distance_meters: float, fps: float = 30.0):
        """Khởi tạo speed calculator với 2 vạch đo và khoảng cách thực tế."""
        self.line1_y = line1_y
        self.line2_y = line2_y
        self.real_distance = real_distance_meters
        self.fps = fps

        # Ngưỡng chống spawn
        self.MIN_TRACK_AGE = 3  # Số frame tối thiểu trước khi cho phép đo
        self.MIN_MOVEMENT_PIXELS = 10  # Di chuyển tối thiểu để chứng minh xe thật
        self.HYSTERESIS = 5  # Vùng dung sai (pixels)

        self.track_states: Dict[int, dict] = {}  # {track_id: state_dict}

        logger.info(f"SpeedCalculator initialized (ANTI-SPAWN FIX)")
        logger.info(f"LINE 1 (START): Y={line1_y} (bottom), LINE 2 (END): Y={line2_y} (top)")
        logger.info(f"Real distance: {real_distance_meters}m, Anti-spawn: min_age={self.MIN_TRACK_AGE} frames, min_movement={self.MIN_MOVEMENT_PIXELS}px")

    def reset(self):
        """Reset trạng thái cho video mới"""
        count = len(self.track_states)
        self.track_states.clear()
        logger.debug(f"Reset: đã xóa {count} track states")

    def update(self, track_id: int, bbox: list, video_timestamp_ms: float) -> Tuple[Optional[float], bool]:
        """
        Cập nhật tính toán tốc độ cho một xe.

        Returns:
            (speed_kmh, is_newly_calculated): Tốc độ km/h và flag tính mới lần đầu
        """
        x1, y1, x2, y2 = bbox
        bottom_y = y2  # Dùng bottom của bbox làm điểm neo

        if track_id not in self.track_states:
            self.track_states[track_id] = {
                'state': 'waiting',
                'first_seen_y': bottom_y,
                'first_seen_timestamp': video_timestamp_ms,
                'track_age': 0,
                'line1_timestamp_ms': None,
                'line1_y': None,
                'line2_timestamp_ms': None,
                'final_speed': None,
                'last_y': None,
                'jump_count': 0
            }

        state = self.track_states[track_id]
        state['track_age'] += 1

        # Phát hiện nhảy lùi (lỗi tracking hoặc đổi ID)
        if state['last_y'] is not None:
            if bottom_y > state['last_y'] + 20:  # Nhảy lùi
                state['jump_count'] += 1
                logger.warning(f"Track {track_id}: Nhảy lùi Y {state['last_y']:.0f} → {bottom_y:.0f}")

                if state['jump_count'] >= 3:  # Quá nhiều lần nhảy = đổi ID
                    logger.warning(f"Track {track_id}: RESET (nghi đổi ID)")
                    self.track_states[track_id] = {
                        'state': 'waiting',
                        'first_seen_y': bottom_y,
                        'first_seen_timestamp': video_timestamp_ms,
                        'track_age': 0,
                        'line1_timestamp_ms': None,
                        'line1_y': None,
                        'line2_timestamp_ms': None,
                        'final_speed': None,
                        'last_y': bottom_y,
                        'jump_count': 0
                    }
                    return None, False

        state['last_y'] = bottom_y

        # STATE MACHINE
        if state['state'] == 'waiting':
            track_age = state['track_age']
            movement_y = state['first_seen_y'] - bottom_y

            if track_age < self.MIN_TRACK_AGE:
                return None, False

            if movement_y < self.MIN_MOVEMENT_PIXELS:
                return None, False

            state['state'] = 'ready_to_measure'
            logger.debug(f"Track {track_id}: Sẵn sàng đo (age={track_age}, moved={movement_y:.0f}px)")

        elif state['state'] == 'ready_to_measure':
            if bottom_y <= self.line1_y + self.HYSTERESIS:
                state['state'] = 'crossed_line1'
                state['line1_timestamp_ms'] = video_timestamp_ms
                state['line1_y'] = bottom_y
                logger.debug(f"Track {track_id}: Qua LINE1 tại t={video_timestamp_ms:.0f}ms")

        elif state['state'] == 'crossed_line1':
            if bottom_y <= self.line2_y + self.HYSTERESIS:
                was_completed = (state['state'] == 'completed')
                state['state'] = 'completed'
                state['line2_timestamp_ms'] = video_timestamp_ms

                is_newly_calculated = False
                if state['line1_timestamp_ms'] is not None and not was_completed:
                    final_speed = self._calculate_final_speed(
                        state['line1_timestamp_ms'],
                        state['line2_timestamp_ms'],
                        track_id
                    )
                    state['final_speed'] = final_speed
                    is_newly_calculated = True

                    if final_speed is not None and final_speed > 0:
                        logger.info(f"Track {track_id}: TỐC ĐỘ = {final_speed:.1f} km/h "
                              f"(Δt={(state['line2_timestamp_ms'] - state['line1_timestamp_ms']):.0f}ms)")
                    else:
                        logger.warning(f"Track {track_id}: Tính tốc độ không hợp lệ")
                        is_newly_calculated = False

                return state.get('final_speed'), is_newly_calculated

        elif state['state'] == 'completed' or state['state'] == 'invalid':
            pass

        return state.get('final_speed'), False

    def _calculate_final_speed(self, line1_time_ms: float, line2_time_ms: float, track_id: int) -> Optional[float]:
        """Tính tốc độ cuối cùng từ timestamp video. Trả về km/h hoặc None nếu không hợp lệ."""
        time_diff_ms = line2_time_ms - line1_time_ms

        if time_diff_ms <= 0:
            logger.warning(f"Track {track_id}: Chênh lệch thời gian <= 0")
            return None

        time_seconds = time_diff_ms / 1000.0

        MIN_TIME_SECONDS = 0.15
        if time_seconds < MIN_TIME_SECONDS:
            logger.warning(f"Track {track_id}: Thời gian quá ngắn {time_seconds:.3f}s")
            return None

        speed_mps = self.real_distance / time_seconds
        speed_kmh = speed_mps * 3.6

        MIN_SPEED = 5.0
        MAX_SPEED = 200.0

        if speed_kmh < MIN_SPEED:
            logger.debug(f"Track {track_id}: Tốc độ quá chậm {speed_kmh:.1f} km/h")
            return None

        if speed_kmh > MAX_SPEED:
            logger.warning(f"Track {track_id}: Tốc độ không thực tế {speed_kmh:.1f} km/h")
            return None

        return speed_kmh

    def is_inside_zone(self, y2: float) -> bool:
        """Kiểm tra xe có trong vùng đo không"""
        return self.line2_y <= y2 <= self.line1_y

    def is_before_zone(self, y2: float) -> bool:
        """Kiểm tra xe có trước vùng đo không"""
        return y2 > self.line1_y

    def is_after_zone(self, y2: float) -> bool:
        """Kiểm tra xe có sau vùng đo không"""
        return y2 < self.line2_y

    def draw_lines(self, frame, color: Tuple[int, int, int] = (0, 255, 255), thickness: int = 2):
        """Vẽ 2 vạch đo lên frame"""
        h, w = frame.shape[:2]

        cv2.line(frame, (0, self.line1_y), (w, self.line1_y), color, thickness)
        cv2.line(frame, (0, self.line2_y), (w, self.line2_y), color, thickness)

        cv2.putText(frame, "LINE 1 (START)", (10, self.line1_y - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
        cv2.putText(frame, "LINE 2 (END)", (10, self.line2_y - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

        zone_center_y = (self.line1_y + self.line2_y) // 2
        cv2.putText(frame, "DETECTION ZONE", (w - 200, zone_center_y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)

        return frame

    def draw_zone_overlay(self, frame, alpha: float = 0.2):
        """Vẽ vùng đo bán trong suốt"""
        overlay = frame.copy()
        h, w = frame.shape[:2]

        cv2.rectangle(overlay, (0, self.line2_y), (w, self.line1_y), (0, 255, 0), -1)

        cv2.addWeighted(overlay, alpha, frame, 1 - alpha, 0, frame)

        return frame

    def get_state_info(self, track_id: int) -> Optional[Dict]:
        """Lấy thông tin debug của track"""
        return self.track_states.get(track_id)