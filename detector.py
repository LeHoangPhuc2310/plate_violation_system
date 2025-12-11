# detector.py
import cv2
from fast_alpr import ALPR
from difflib import SequenceMatcher
import torch

# Memory chống nhận diện sai biển số
plate_memory = {}  # bbox_hash -> stable plate text


def similar(a, b):
    return SequenceMatcher(None, a, b).ratio()


class PlateDetector:
    def __init__(self, device=None):
        """
        Khởi tạo Fast-ALPR với GPU support
        Args:
            device: 'cuda', 'mps', hoặc None (auto-detect)
        """
        # Auto-detect device nếu không chỉ định
        if device is None:
            try:
                if torch.cuda.is_available():
                    device = 'cuda'
                    gpu_name = torch.cuda.get_device_name(0)
                    print(f"🚀 GPU CUDA detected for Fast-ALPR: {gpu_name}")
                elif hasattr(torch.backends, 'mps') and torch.backends.mps.is_available():
                    device = 'mps'
                    print("🚀 GPU MPS (Apple Silicon) detected for Fast-ALPR")
                else:
                    device = 'cpu'
                    print("⚠️  WARNING: No GPU detected for Fast-ALPR. Using CPU (SLOW!)")
                    print("⚠️  Please ensure CUDA is installed and GPU is available for optimal performance.")
            except Exception as e:
                device = 'cpu'
                print(f"⚠️  Error detecting device: {e}. Using CPU.")
        
        # Cho phép CPU với WARNING (không phải error)
        if device == 'cpu':
            print("⚠️  WARNING: Fast-ALPR will run on CPU (VERY SLOW!)")
            print("⚠️  For optimal performance, please install CUDA and ensure GPU is available")
            print("⚠️  Install CUDA: https://developer.nvidia.com/cuda-downloads")
        
        self.device = device
        print(f">>> Loading Fast-ALPR on {device.upper()}...")
        
        try:
            # Fast-ALPR với GPU support - thử với device parameter trước
            try:
                self.alpr = ALPR(
                    detector_model="yolo-v9-t-384-license-plate-end2end",
                    ocr_model="cct-s-v1-global-model",
                    device=device  # Pass device to Fast-ALPR
                )
                print(f">>> ✅ Fast-ALPR Loaded on {device.upper()}!")
            except TypeError:
                # Nếu Fast-ALPR không hỗ trợ device parameter, thử không truyền
                # Fast-ALPR sẽ tự động detect device
                print(f">>> Fast-ALPR không hỗ trợ device parameter, sử dụng auto-detect...")
                self.alpr = ALPR(
                    detector_model="yolo-v9-t-384-license-plate-end2end",
                    ocr_model="cct-s-v1-global-model"
                )
                print(f">>> ✅ Fast-ALPR Loaded (device auto-detected on {device.upper()})!")
        except Exception as e:
            print(f"❌ Error loading Fast-ALPR: {e}")
            import traceback
            traceback.print_exc()
            raise RuntimeError(f"❌ Failed to load Fast-ALPR: {e}")

    def detect(self, frame):
        """
        Nhận diện biển số trong frame bằng Fast-ALPR
        Trả về danh sách biển số với bounding box chính xác
        """
        results = self.alpr.predict(frame)

        plates = []
        for r in results:
            try:
                # ============================
                # BBOX - Lấy chính xác từ Fast-ALPR
                # ============================
                x1 = int(r.detection.bounding_box.x1)
                y1 = int(r.detection.bounding_box.y1)
                x2 = int(r.detection.bounding_box.x2)
                y2 = int(r.detection.bounding_box.y2)

                # Đảm bảo bbox hợp lệ
                if x2 <= x1 or y2 <= y1:
                    continue
                
                bbox = (x1, y1, x2, y2)
                bbox_hash = hash(bbox)  # track ID thay thế

                # ============================
                # OCR - Lấy text từ Fast-ALPR
                # ============================
                plate_text = r.ocr.text.strip()
                
                # Bỏ qua nếu text rỗng hoặc quá ngắn
                if not plate_text or len(plate_text) < 3:
                    continue

                # ============================
                # CONFIDENCE - Lấy confidence nếu có
                # ============================
                detection_confidence = 0.5  # Default
                ocr_confidence = 0.5  # Default
                
                try:
                    # Thử lấy confidence từ detection
                    if hasattr(r.detection, 'confidence'):
                        detection_confidence = float(r.detection.confidence)
                    elif hasattr(r.detection, 'score'):
                        detection_confidence = float(r.detection.score)
                except:
                    pass
                
                try:
                    # Thử lấy confidence từ OCR
                    if hasattr(r.ocr, 'confidence'):
                        ocr_confidence = float(r.ocr.confidence)
                    elif hasattr(r.ocr, 'score'):
                        ocr_confidence = float(r.ocr.score)
                except:
                    pass
                
                # Confidence tổng hợp (ưu tiên detection confidence)
                overall_confidence = (detection_confidence * 0.6 + ocr_confidence * 0.4)

                # ============================
                # ỔN ĐỊNH BIỂN SỐ
                # ============================
                if bbox_hash in plate_memory:
                    old_plate = plate_memory[bbox_hash]

                    # Nếu giống nhau > 80% => dùng biển cũ (ổn định hơn)
                    if similar(old_plate, plate_text) > 0.8:
                        plate_text = old_plate
                    else:
                        # OCR sai quá → bỏ qua biển số này
                        continue
                else:
                    # Lần đầu thấy bbox này
                    plate_memory[bbox_hash] = plate_text

                # ============================
                # Trả về kết quả với đầy đủ thông tin
                # ============================
                plates.append({
                    "bbox": bbox,
                    "plate": plate_text,
                    "track_id": bbox_hash,     # track_id giả lập
                    "confidence": overall_confidence,  # Confidence để chọn biển số tốt nhất
                    "detection_conf": detection_confidence,
                    "ocr_conf": ocr_confidence
                })
            except Exception as e:
                # Bỏ qua lỗi và tiếp tục với biển số tiếp theo
                print(f"[PlateDetector] Error processing result: {e}")
                continue

        return plates
