import numpy as np
from collections import defaultdict
from filterpy.kalman import KalmanFilter


class KalmanBoxTracker:

    count = 0

    def __init__(self, bbox):
        self.kf = KalmanFilter(dim_x=7, dim_z=4)

        self.kf.F = np.array([
            [1, 0, 0, 0, 1, 0, 0],
            [0, 1, 0, 0, 0, 1, 0],
            [0, 0, 1, 0, 0, 0, 1],
            [0, 0, 0, 1, 0, 0, 0],
            [0, 0, 0, 0, 1, 0, 0],
            [0, 0, 0, 0, 0, 1, 0],
            [0, 0, 0, 0, 0, 0, 1]
        ])

        self.kf.H = np.array([
            [1, 0, 0, 0, 0, 0, 0],
            [0, 1, 0, 0, 0, 0, 0],
            [0, 0, 1, 0, 0, 0, 0],
            [0, 0, 0, 1, 0, 0, 0]
        ])

        self.kf.R[2:, 2:] *= 10.
        self.kf.P[4:, 4:] *= 1000.
        self.kf.P *= 10.
        self.kf.Q[-1, -1] *= 0.01
        self.kf.Q[4:, 4:] *= 0.01

        self.kf.x[:4] = self._bbox_to_z(bbox)

        self.time_since_update = 0
        self.id = KalmanBoxTracker.count
        KalmanBoxTracker.count += 1
        self.history = []
        self.hits = 0
        self.hit_streak = 0
        self.age = 0

    def _bbox_to_z(self, bbox):
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
        x = bbox[0] + w / 2.
        y = bbox[1] + h / 2.
        s = w * h
        r = w / float(h) if h > 0 else 1
        return np.array([[x], [y], [s], [r]])

    def _z_to_bbox(self, z):
        w = np.sqrt(z[2] * z[3])
        h = z[2] / w if w > 0 else 0
        return np.array([
            z[0] - w / 2.,
            z[1] - h / 2.,
            z[0] + w / 2.,
            z[1] + h / 2.
        ]).flatten()

    def update(self, bbox):
        self.time_since_update = 0
        self.history = []
        self.hits += 1
        self.hit_streak += 1
        self.kf.update(self._bbox_to_z(bbox))

    def predict(self):
        if self.kf.x[6] + self.kf.x[2] <= 0:
            self.kf.x[6] *= 0.0
        self.kf.predict()
        self.age += 1
        if self.time_since_update > 0:
            self.hit_streak = 0
        self.time_since_update += 1
        self.history.append(self._z_to_bbox(self.kf.x))
        return self.history[-1]

    def get_state(self):
        return self._z_to_bbox(self.kf.x)


class ByteTracker:

    def __init__(self, max_age=30, min_hits=3, iou_threshold=0.3):
        self.max_age = max_age
        self.min_hits = min_hits
        self.iou_threshold = iou_threshold
        self.trackers = []
        self.frame_count = 0
        print(f"[TRACKER] ByteTrack initialized (max_age={max_age}, min_hits={min_hits})")
    
    def reset(self):
        """Reset tracker state for new video"""
        # Reset track ID counter
        KalmanBoxTracker.count = 0
        self.trackers = []
        self.frame_count = 0
        print(f"[TRACKER] Reset: cleared {len(self.trackers)} trackers, track ID counter reset")

    def update(self, detections):
        self.frame_count += 1

        for t in self.trackers:
            t.predict()

        if len(self.trackers) == 0:
            trk_bboxes = np.empty((0, 4))
        else:
            trk_bboxes = np.array([t.get_state() for t in self.trackers])

        if len(detections) == 0:
            det_bboxes = np.empty((0, 4))
        else:
            det_bboxes = np.array([d['bbox'] for d in detections])

        matched, unmatched_dets, unmatched_trks = self._associate(
            det_bboxes, trk_bboxes, self.iou_threshold
        )

        for d, t in matched:
            self.trackers[t].update(det_bboxes[d])

        for d in unmatched_dets:
            trk = KalmanBoxTracker(det_bboxes[d])
            self.trackers.append(trk)

        self.trackers = [t for t in self.trackers
                        if t.time_since_update <= self.max_age]

        results = []
        for i, det in enumerate(detections):
            track_id = None
            for d, t in matched:
                if d == i and t < len(self.trackers) and t >= 0:
                    track_id = self.trackers[t].id
                    break

            if track_id is None:
                for trk in self.trackers:
                    if trk.hits == 1 and trk.time_since_update == 0:
                        try:
                            bbox_match = np.allclose(trk.get_state()[:4], det['bbox'], atol=10)
                            if bbox_match:
                                track_id = trk.id
                                break
                        except:
                            pass

            if track_id is not None:
                det_copy = det.copy()
                det_copy['track_id'] = track_id
                results.append(det_copy)

        return results

    def _associate(self, det_bboxes, trk_bboxes, iou_threshold):
        if len(trk_bboxes) == 0:
            return np.empty((0, 2), dtype=int), np.arange(len(det_bboxes)), np.empty((0,), dtype=int)

        if len(det_bboxes) == 0:
            return np.empty((0, 2), dtype=int), np.empty((0,), dtype=int), np.arange(len(trk_bboxes))

        iou_matrix = self._iou_batch(det_bboxes, trk_bboxes)

        from scipy.optimize import linear_sum_assignment
        row_indices, col_indices = linear_sum_assignment(-iou_matrix)

        matched = []
        unmatched_dets = list(range(len(det_bboxes)))
        unmatched_trks = list(range(len(trk_bboxes)))

        for r, c in zip(row_indices, col_indices):
            if iou_matrix[r, c] >= iou_threshold:
                matched.append((r, c))
                if r in unmatched_dets:
                    unmatched_dets.remove(r)
                if c in unmatched_trks:
                    unmatched_trks.remove(c)

        return np.array(matched), np.array(unmatched_dets), np.array(unmatched_trks)

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
