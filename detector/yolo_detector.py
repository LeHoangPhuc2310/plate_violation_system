import cv2
import numpy as np
import threading
import torch
from ultralytics import YOLO
from utils.logger import get_logger

logger = get_logger(__name__)


class YOLODetector:

    VEHICLE_CLASSES = {
        2: 'car',
        3: 'motorcycle',
        5: 'bus',
        7: 'truck'
    }

    def __init__(self, model_path='yolo11m.pt', device='cuda', conf_thresh=0.5):
        self.model = YOLO(model_path)
        self.device = device
        self.conf_thresh = conf_thresh
        self.cuda_lock = threading.Lock() if device == 'cuda' else None
        logger.info(f"YOLOv11m loaded on {device}")

    def detect(self, frame):
        if self.cuda_lock:
            with self.cuda_lock:
                if self.device == 'cuda' and torch.cuda.is_available():
                    torch.cuda.synchronize()

                results = self.model.predict(
                    frame,
                    device=self.device,
                    conf=self.conf_thresh,
                    classes=list(self.VEHICLE_CLASSES.keys()),
                    verbose=False,
                    iou=0.5,
                    stream=False
                )

                if self.device == 'cuda' and torch.cuda.is_available():
                    torch.cuda.synchronize()
        else:
            results = self.model.predict(
                frame,
                device=self.device,
                conf=self.conf_thresh,
                classes=list(self.VEHICLE_CLASSES.keys()),
                verbose=False,
                iou=0.5
            )

        detections = []
        for result in results:
            if result.boxes is None:
                continue

            boxes = result.boxes.xyxy.cpu().numpy()
            classes = result.boxes.cls.cpu().numpy().astype(int)
            confs = result.boxes.conf.cpu().numpy()

            for bbox, cls, conf in zip(boxes, classes, confs):
                detections.append({
                    'bbox': bbox.tolist(),
                    'class': self.VEHICLE_CLASSES.get(cls, 'unknown'),
                    'conf': float(conf)
                })

        detections = self._apply_nms(detections, iou_threshold=0.5)
        detections = self._filter_small_bboxes(detections)

        return detections

    def _filter_small_bboxes(self, detections):
        if not detections:
            return detections

        filtered = []
        for det in detections:
            bbox = det['bbox']
            x1, y1, x2, y2 = bbox
            width = x2 - x1
            height = y2 - y1
            area = width * height

            if width < 30 or height < 30 or area < 900:
                continue

            filtered.append(det)

        return filtered

    def _apply_nms(self, detections, iou_threshold=0.4):
        if len(detections) <= 1:
            return detections

        boxes = np.array([d['bbox'] for d in detections])
        scores = np.array([d['conf'] for d in detections])

        iou_matrix = self._iou_batch(boxes, boxes)

        keep = []
        suppressed = set()

        sorted_indices = np.argsort(scores)[::-1]

        for i in sorted_indices:
            if i in suppressed:
                continue

            keep.append(i)

            for j in sorted_indices:
                if i != j and j not in suppressed:
                    if iou_matrix[i, j] > iou_threshold:
                        suppressed.add(j)

        return [detections[i] for i in sorted(keep)]

    @staticmethod
    def _iou_batch(bb_test, bb_gt):
        bb_gt = np.expand_dims(bb_gt, 0)
        bb_test = np.expand_dims(bb_test, 1)

        xx1 = np.maximum(bb_test[..., 0], bb_gt[..., 0])
        yy1 = np.maximum(bb_test[..., 1], bb_gt[..., 1])
        xx2 = np.minimum(bb_test[..., 2], bb_gt[..., 2])
        yy2 = np.minimum(bb_test[..., 3], bb_gt[..., 3])

        w = np.maximum(0., xx2 - xx1)
        h = np.maximum(0., yy2 - yy1)
        wh = w * h

        area_test = (bb_test[..., 2] - bb_test[..., 0]) * (bb_test[..., 3] - bb_test[..., 1])
        area_gt = (bb_gt[..., 2] - bb_gt[..., 0]) * (bb_gt[..., 3] - bb_gt[..., 1])

        iou = wh / (area_test + area_gt - wh + 1e-6)
        return iou

    def draw_detections(self, frame, detections, draw_bbox=True):
        if not draw_bbox:
            return frame

        annotated = frame.copy()

        for det in detections:
            x1, y1, x2, y2 = map(int, det['bbox'])
            cls = det.get('class', 'vehicle')
            conf = det.get('conf', 0)
            track_id = det.get('track_id')
            speed = det.get('speed')

            color = (0, 0, 255) if det.get('violation') else (0, 255, 0)

            cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)

            label_parts = []
            if track_id is not None:
                label_parts.append(f"ID:{track_id}")
            if speed is not None and speed > 0:
                # Hiển thị tốc độ đã được tính (xe đã đi qua LINE1 và LINE2)
                label_parts.append(f"{speed:.1f}km/h")
            elif track_id is not None:
                # Hiển thị "---km/h" khi tốc độ chưa được tính (xe chưa đi qua LINE1 và LINE2)
                label_parts.append("---km/h")

            label = " | ".join(label_parts)

            (w, h), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 2)
            cv2.rectangle(annotated, (x1, y1-20), (x1+w+10, y1), color, -1)
            cv2.putText(annotated, label, (x1+5, y1-5),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255,255,255), 2)

        return annotated
