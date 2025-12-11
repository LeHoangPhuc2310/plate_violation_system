# enhanced_plate_detector.py
"""
Enhanced Plate Detector với nhiều phương pháp fallback:
1. Fast-ALPR (chính)
2. Preprocessing nâng cao (nhiều phương pháp enhance)
3. EasyOCR fallback (nếu Fast-ALPR không đọc được)
4. Ensemble kết quả từ nhiều phương pháp
"""
import cv2
import numpy as np
from detector import PlateDetector

# Thử import EasyOCR (optional)
try:
    import easyocr
    EASYOCR_AVAILABLE = True
    print(">>> EasyOCR available - sẽ dùng làm fallback")
except ImportError:
    EASYOCR_AVAILABLE = False
    print(">>> EasyOCR not available - cài đặt: pip install easyocr")


class EnhancedPlateDetector:
    def __init__(self):
        """Khởi tạo Enhanced Plate Detector với nhiều phương pháp"""
        print(">>> Loading Enhanced Plate Detector...")
        
        # 1. Fast-ALPR (chính)
        self.fast_alpr = PlateDetector()
        
        # 2. EasyOCR (fallback) - chỉ load nếu cần
        self.easyocr_reader = None
        if EASYOCR_AVAILABLE:
            try:
                print(">>> Loading EasyOCR (fallback)...")
                # Chỉ load tiếng Việt và tiếng Anh để nhanh hơn
                self.easyocr_reader = easyocr.Reader(['vi', 'en'], gpu=True, verbose=False)
                print(">>> ✅ EasyOCR loaded!")
            except Exception as e:
                print(f">>> ⚠️ EasyOCR load failed: {e}")
                self.easyocr_reader = None
        
        print(">>> ✅ Enhanced Plate Detector loaded!")
    
    def preprocess_image(self, img, method='default'):
        """
        Preprocess ảnh với nhiều phương pháp khác nhau
        
        Methods:
        - 'default': Không enhance
        - 'clahe': CLAHE contrast enhancement
        - 'sharpen': Unsharp masking
        - 'denoise': Denoising
        - 'bright': Brightness adjustment
        - 'contrast': Contrast enhancement
        - 'combined': Kết hợp nhiều phương pháp
        """
        if method == 'default':
            return img
        
        # Đảm bảo ảnh có 3 kênh màu
        if len(img.shape) == 2:
            img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        
        if method == 'clahe':
            # CLAHE (Contrast Limited Adaptive Histogram Equalization)
            lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
            l, a, b = cv2.split(lab)
            clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
            l_enhanced = clahe.apply(l)
            lab_enhanced = cv2.merge([l_enhanced, a, b])
            return cv2.cvtColor(lab_enhanced, cv2.COLOR_LAB2BGR)
        
        elif method == 'sharpen':
            # Unsharp masking
            gaussian = cv2.GaussianBlur(img, (0, 0), 2.0)
            sharpened = cv2.addWeighted(img, 1.5, gaussian, -0.5, 0)
            return sharpened
        
        elif method == 'denoise':
            # Denoising
            denoised = cv2.fastNlMeansDenoisingColored(img, None, 10, 10, 7, 21)
            return denoised
        
        elif method == 'bright':
            # Tăng brightness
            hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
            h, s, v = cv2.split(hsv)
            v = cv2.add(v, 30)  # Tăng brightness
            v = cv2.min(v, 255)
            hsv_enhanced = cv2.merge([h, s, v])
            return cv2.cvtColor(hsv_enhanced, cv2.COLOR_HSV2BGR)
        
        elif method == 'contrast':
            # Tăng contrast
            alpha = 1.5  # Contrast control
            beta = 0     # Brightness control
            enhanced = cv2.convertScaleAbs(img, alpha=alpha, beta=beta)
            return enhanced
        
        elif method == 'combined':
            # Kết hợp nhiều phương pháp
            # 1. Denoise
            img = cv2.fastNlMeansDenoisingColored(img, None, 10, 10, 7, 21)
            # 2. CLAHE
            lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
            l, a, b = cv2.split(lab)
            clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
            l_enhanced = clahe.apply(l)
            lab_enhanced = cv2.merge([l_enhanced, a, b])
            img = cv2.cvtColor(lab_enhanced, cv2.COLOR_LAB2BGR)
            # 3. Sharpen
            gaussian = cv2.GaussianBlur(img, (0, 0), 1.5)
            sharpened = cv2.addWeighted(img, 1.5, gaussian, -0.5, 0)
            return sharpened
        
        return img
    
    def detect_with_fast_alpr(self, img, preprocess_method='default'):
        """Detect với Fast-ALPR sau khi preprocess"""
        processed_img = self.preprocess_image(img, preprocess_method)
        results = self.fast_alpr.detect(processed_img)
        return results
    
    def detect_with_easyocr(self, img):
        """Detect với EasyOCR (fallback)"""
        if not self.easyocr_reader:
            return []
        
        try:
            # EasyOCR detect text
            results = self.easyocr_reader.readtext(img)
            
            plates = []
            for (bbox, text, confidence) in results:
                # Lọc text có thể là biển số (chứa số và chữ)
                text_clean = text.strip().upper()
                if len(text_clean) >= 6 and any(c.isdigit() for c in text_clean) and any(c.isalpha() for c in text_clean):
                    # Convert bbox từ EasyOCR format sang (x1, y1, x2, y2)
                    points = np.array(bbox, dtype=np.int32)
                    x1 = int(points[:, 0].min())
                    y1 = int(points[:, 1].min())
                    x2 = int(points[:, 0].max())
                    y2 = int(points[:, 1].max())
                    
                    plates.append({
                        'bbox': (x1, y1, x2, y2),
                        'plate': text_clean,
                        'confidence': confidence,
                        'detection_conf': confidence,
                        'ocr_conf': confidence,
                        'method': 'easyocr'
                    })
            
            return plates
        except Exception as e:
            print(f"[EasyOCR] Error: {e}")
            return []
    
    def detect(self, img):
        """
        Detect biển số với nhiều phương pháp fallback
        
        Flow:
        1. Thử Fast-ALPR với ảnh gốc
        2. Nếu không có kết quả, thử Fast-ALPR với các preprocessing khác nhau
        3. Nếu vẫn không có, thử EasyOCR
        4. Ensemble kết quả từ tất cả các phương pháp
        """
        all_results = []
        
        # 1. Thử Fast-ALPR với ảnh gốc
        results = self.detect_with_fast_alpr(img, 'default')
        if results:
            for r in results:
                r['method'] = 'fast_alpr_default'
                all_results.append(r)
        
        # 2. Nếu không có kết quả, thử các preprocessing methods
        if not all_results:
            preprocess_methods = ['clahe', 'sharpen', 'denoise', 'bright', 'contrast', 'combined']
            
            for method in preprocess_methods:
                results = self.detect_with_fast_alpr(img, method)
                if results:
                    for r in results:
                        r['method'] = f'fast_alpr_{method}'
                        all_results.append(r)
                    # Nếu đã có kết quả tốt, có thể dừng sớm
                    if any(r.get('confidence', 0) > 0.7 for r in results):
                        break
        
        # 3. Nếu vẫn không có kết quả, thử EasyOCR
        if not all_results and self.easyocr_reader:
            print("[Enhanced] Fast-ALPR không đọc được, thử EasyOCR...")
            # Thử EasyOCR với ảnh đã preprocess
            for method in ['default', 'clahe', 'sharpen', 'combined']:
                processed_img = self.preprocess_image(img, method)
                results = self.detect_with_easyocr(processed_img)
                if results:
                    all_results.extend(results)
                    break
        
        # 4. Ensemble kết quả - chọn kết quả tốt nhất
        if all_results:
            # Nhóm theo biển số đã normalize
            # Import normalize và validate functions
            import re
            def normalize_plate(plate):
                """Normalize biển số: loại bỏ ký tự đặc biệt, khoảng trắng, chuyển thành chữ hoa"""
                if not plate:
                    return ""
                return plate.replace(" ", "").replace(".", "").replace("-", "").replace("_", "").upper()
            
            def is_valid_plate(plate):
                """Validate biển số Việt Nam: 2 số + 1 chữ cái + 5 số"""
                if not plate:
                    return False
                plate = normalize_plate(plate)
                pattern = r"^[0-9]{2}[A-Z][0-9]{5}$"
                return re.match(pattern, plate) is not None
            
            plate_groups = {}
            for r in all_results:
                plate_text = normalize_plate(r.get('plate', ''))
                if plate_text and is_valid_plate(plate_text):
                    if plate_text not in plate_groups:
                        plate_groups[plate_text] = []
                    plate_groups[plate_text].append(r)
            
            # Chọn biển số tốt nhất (confidence cao nhất)
            best_result = None
            best_score = 0
            
            for plate_text, group in plate_groups.items():
                # Tính điểm trung bình cho nhóm
                avg_conf = sum(r.get('confidence', 0) for r in group) / len(group)
                # Ưu tiên kết quả từ Fast-ALPR
                fast_alpr_count = sum(1 for r in group if 'fast_alpr' in r.get('method', ''))
                method_bonus = 0.1 if fast_alpr_count > 0 else 0
                
                score = avg_conf + method_bonus
                
                if score > best_score:
                    # Chọn result có confidence cao nhất trong nhóm
                    best_in_group = max(group, key=lambda x: x.get('confidence', 0))
                    best_result = best_in_group
                    best_result['plate'] = plate_text  # Đảm bảo đã normalize
                    best_score = score
            
            if best_result:
                print(f"[Enhanced] ✅ Đã đọc biển số: {best_result['plate']} (method: {best_result.get('method', 'unknown')}, conf: {best_result.get('confidence', 0):.2f})")
                return [best_result]
        
        return []

