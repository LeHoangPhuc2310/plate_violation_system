import cv2
from fast_alpr import ALPR
import json

# =============================
#  ALPR DEBUGGER - FULL STRUCT
# =============================
# Tác dụng: In đầy đủ thông tin của từng biển số
# - Bounding Box
# - Confidence
# - OCR text
# - Các thuộc tính ẩn của object
# - Xuất JSON rõ ràng
# =============================

def dump_alpr_result(r):
    """Trả về dict đầy đủ để chuyển sang JSON."""
    det = r.detection
    ocr = r.ocr
    bbox = det.bounding_box

    return {
        "label": det.label,
        "confidence": float(det.confidence),
        "bbox": {
            "x1": int(bbox.x1), "y1": int(bbox.y1),
            "x2": int(bbox.x2), "y2": int(bbox.y2),
            "width": int(bbox.width), "height": int(bbox.height),
            "area": int(bbox.area()),
            "center": bbox.center(),
        },
        "ocr": {
            "text": ocr.text,
            "confidence": float(ocr.confidence),
            "valid": bool(ocr.is_valid()),
        },
        "raw_attributes": {
            "detection_keys": dir(det),
            "ocr_keys": dir(ocr),
            "bbox_keys": dir(bbox),
        }
    }


def debug_alpr(image_path):
    print(">>> Loading ALPR model...")
    alpr = ALPR()

    img = cv2.imread(image_path)
    if img is None:
        raise FileNotFoundError(f"Không tìm thấy ảnh: {image_path}")

    preds = alpr.predict(img)

    if not preds:
        print("❌ Không tìm thấy biển số!")
        return

    print(f"\n>>> Tìm thấy {len(preds)} biển số")

    # Xuất JSON
    results_json = []

    for i, r in enumerate(preds):
        print(f"\n============================")
        print(f"BIỂN SỐ #{i+1}")
        print("============================")

        det = r.detection
        ocr = r.ocr
        bbox = det.bounding_box

        print("Label:", det.label)
        print("Confidence:", det.confidence)
        print("BBox:", bbox.to_list())
        print("OCR Text:", ocr.text)
        print("OCR Confidence:", ocr.confidence)

        results_json.append(dump_alpr_result(r))

    print("\n>>> JSON OUTPUT:")
    print(json.dumps(results_json, indent=4, ensure_ascii=False))


if __name__ == "__main__":
    # NHẬP ĐƯỜNG DẪN ẢNH Ở ĐÂY
    debug_alpr(r"C:\Users\ASUS\Downloads\NhanDienBienSo\dataset_plate\images\train\0105_01594_b.jpg")