# detector.py
import cv2
from fast_alpr import ALPR
from difflib import SequenceMatcher

# Memory chống nhận diện sai biển số
plate_memory = {}  # bbox_hash -> stable plate text


def similar(a, b):
    return SequenceMatcher(None, a, b).ratio()


class PlateDetector:
    def __init__(self):
        print(">>> Loading Fast-ALPR...")
        self.alpr = ALPR(
            detector_model="yolo-v9-t-384-license-plate-end2end",
            ocr_model="cct-s-v1-global-model"
        )
        print(">>> Fast-ALPR Loaded!")

    def detect(self, frame):
        results = self.alpr.predict(frame)

        plates = []
        for r in results:

            # ============================
            # BBOX
            # ============================
            x1 = int(r.detection.bounding_box.x1)
            y1 = int(r.detection.bounding_box.y1)
            x2 = int(r.detection.bounding_box.x2)
            y2 = int(r.detection.bounding_box.y2)

            bbox = (x1, y1, x2, y2)
            bbox_hash = hash(bbox)  # track ID thay thế

            # ============================
            # OCR
            # ============================
            plate_text = r.ocr.text.strip()

            # ============================
            # ỔN ĐỊNH BIỂN SỐ
            # ============================
            if bbox_hash in plate_memory:
                old_plate = plate_memory[bbox_hash]

                # Nếu giống nhau > 80% => dùng biển cũ
                if similar(old_plate, plate_text) > 0.8:
                    plate_text = old_plate
                else:
                    # OCR sai quá → bỏ qua biển số này
                    continue
            else:
                # Lần đầu thấy bbox này
                plate_memory[bbox_hash] = plate_text

            # ============================
            # Trả về kết quả
            # ============================
            plates.append({
                "bbox": bbox,
                "plate": plate_text,
                "track_id": bbox_hash     # track_id giả lập
            })

        return plates
