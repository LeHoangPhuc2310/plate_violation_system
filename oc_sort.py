# oc_sort.py
"""
OC-SORT: Observation-Centric SORT
Better than ByteTrack for smooth tracking with better occlusion handling
"""
import numpy as np
from filterpy.kalman import KalmanFilter
from scipy.optimize import linear_sum_assignment

class TrackState:
    New = 0
    Tracked = 1
    Lost = 2
    Removed = 3

class OCTrack:
    """Track with Kalman Filter and velocity smoothing"""
    
    def __init__(self, tlbr, score, cls, track_id, frame_id):
        self.tlbr = tlbr.astype(np.float32)
        self.score = score
        self.cls = cls
        self.track_id = track_id
        self.frame_id = frame_id
        self.state = TrackState.New
        self.is_activated = False
        self.tracklet_len = 0
        self.time_since_update = 0
        
        # Kalman Filter - 7D state: [x, y, a, h, vx, vy, va]
        # x, y: center, a: aspect ratio, h: height
        self.kf = KalmanFilter(dim_x=7, dim_z=4)
        
        # Convert tlbr to [x, y, a, h]
        x1, y1, x2, y2 = tlbr
        w = x2 - x1
        h = y2 - y1
        x = x1 + w / 2
        y = y1 + h / 2
        a = w / (h + 1e-6)
        
        self.kf.x[:4] = np.array([[x], [y], [a], [h]])
        
        # State transition matrix
        self.kf.F = np.array([
            [1, 0, 0, 0, 1, 0, 0],  # x = x + vx
            [0, 1, 0, 0, 0, 1, 0],  # y = y + vy
            [0, 0, 1, 0, 0, 0, 1],  # a = a + va
            [0, 0, 0, 1, 0, 0, 0],  # h = h
            [0, 0, 0, 0, 1, 0, 0],  # vx = vx
            [0, 0, 0, 0, 0, 1, 0],  # vy = vy
            [0, 0, 0, 0, 0, 0, 1],  # va = va
        ])
        
        # Measurement matrix [x, y, a, h]
        self.kf.H = np.array([
            [1, 0, 0, 0, 0, 0, 0],
            [0, 1, 0, 0, 0, 0, 0],
            [0, 0, 1, 0, 0, 0, 0],
            [0, 0, 0, 1, 0, 0, 0],
        ])
        
        # Measurement noise - cân bằng để tracking mượt
        self.kf.R[0:2, 0:2] *= 0.8  # Position
        self.kf.R[2:, 2:] *= 10.0  # Aspect ratio and height
        
        # Process noise - cân bằng
        self.kf.Q[-1, -1] *= 0.01  # va
        self.kf.Q[4:6, 4:6] *= 0.01  # vx, vy
        self.kf.Q[0:4, 0:4] *= 0.15  # Position
        
        # Initial covariance
        self.kf.P[4:, 4:] *= 1000.0  # High uncertainty for velocities
        self.kf.P[0:4, 0:4] *= 8.0  # Position covariance
    
    def predict(self):
        """Predict next state - Cải thiện để tracking mượt hơn"""
        self.kf.predict()
        self.time_since_update += 1
        
        # Convert back to tlbr
        x, y, a, h = self.kf.x[:4].flatten()
        w = a * h
        # Đảm bảo w và h hợp lệ
        w = max(1, w)
        h = max(1, h)
        x1 = x - w / 2
        y1 = y - h / 2
        x2 = x + w / 2
        y2 = y + h / 2
        
        return np.array([x1, y1, x2, y2], dtype=np.float32)
    
    def update(self, tlbr, score):
        """Update with new detection - Cải thiện để tracking mượt hơn"""
        # Convert tlbr to [x, y, a, h]
        x1, y1, x2, y2 = tlbr
        w = x2 - x1
        h = y2 - y1
        x = x1 + w / 2
        y = y1 + h / 2
        a = w / (h + 1e-6)
        
        measurement = np.array([[x], [y], [a], [h]])
        self.kf.update(measurement)
        
        # Update attributes
        self.score = score
        self.time_since_update = 0
        self.tracklet_len += 1
        
        # Get updated tlbr - dùng Kalman prediction để mượt hơn
        x, y, a, h = self.kf.x[:4].flatten()
        w = a * h
        # Đảm bảo w và h hợp lệ
        w = max(1, w)
        h = max(1, h)
        self.tlbr = np.array([x - w/2, y - h/2, x + w/2, y + h/2], dtype=np.float32)

class OCSort:
    """OC-SORT tracker - Better than ByteTrack"""
    
    def __init__(self, det_thresh=0.2, max_age=30, min_hits=3, iou_threshold=0.3):
        self.det_thresh = det_thresh
        self.max_age = max_age
        self.min_hits = min_hits
        # TỐI ƯU: Tăng IoU threshold để matching chính xác hơn
        self.iou_threshold = iou_threshold
        
        self.frame_count = 0
        self.track_id_count = 0
        self.tracks = []
    
    def update(self, detections, frame=None):
        """
        Update tracks with new detections
        Args:
            detections: numpy array (N, 6) [x1, y1, x2, y2, score, class]
        Returns:
            list of OCTrack objects
        """
        self.frame_count += 1
        
        # Get predicted locations from existing tracks
        trks = np.zeros((len(self.tracks), 5))
        to_del = []
        for t, track in enumerate(self.tracks):
            pos = track.predict()
            trks[t] = np.append(pos, track.score)
            if np.any(np.isnan(pos)):
                to_del.append(t)
        
        # Remove invalid tracks
        for t in reversed(to_del):
            self.tracks.pop(t)
        
        # Filter detections by confidence
        dets = detections[detections[:, 4] >= self.det_thresh]
        
        # Association using Hungarian algorithm
        matched, unmatched_dets, unmatched_trks = self.associate_detections_to_trackers(
            dets, trks, self.iou_threshold
        )
        
        # Update matched tracks
        for m in matched:
            track_idx, det_idx = m
            self.tracks[track_idx].update(dets[det_idx, :4], dets[det_idx, 4])
            self.tracks[track_idx].cls = int(dets[det_idx, 5])
            self.tracks[track_idx].frame_id = self.frame_count
            self.tracks[track_idx].is_activated = True
            self.tracks[track_idx].state = TrackState.Tracked
        
        # Create new tracks for unmatched detections
        for i in unmatched_dets:
            self.track_id_count += 1
            track = OCTrack(
                dets[i, :4],
                dets[i, 4],
                int(dets[i, 5]),
                self.track_id_count,
                self.frame_count
            )
            self.tracks.append(track)
        
        # Remove dead tracks
        i = len(self.tracks)
        for track in reversed(self.tracks):
            i -= 1
            # Remove if lost for too long
            if track.time_since_update > self.max_age:
                self.tracks.pop(i)
        
        # Return active tracks (min_hits check)
        ret = []
        for track in self.tracks:
            if track.tracklet_len >= self.min_hits or self.frame_count <= self.min_hits:
                if track.time_since_update < 1:
                    ret.append(track)
        
        return ret
    
    def associate_detections_to_trackers(self, detections, trackers, iou_threshold=0.3):
        """
        Assigns detections to tracked object using Hungarian algorithm
        Returns: matched, unmatched_detections, unmatched_trackers
        """
        if len(trackers) == 0:
            return np.empty((0, 2), dtype=int), np.arange(len(detections)), np.empty(0, dtype=int)
        
        if len(detections) == 0:
            return np.empty((0, 2), dtype=int), np.empty(0, dtype=int), np.arange(len(trackers))
        
        # Compute IoU matrix
        iou_matrix = self.iou_batch(detections[:, :4], trackers[:, :4])
        
        # Use Hungarian algorithm
        if min(iou_matrix.shape) > 0:
            # Convert to cost matrix (1 - IoU)
            cost_matrix = 1 - iou_matrix
            row_ind, col_ind = linear_sum_assignment(cost_matrix)
            matched_indices = np.stack([row_ind, col_ind], axis=1)
        else:
            matched_indices = np.empty((0, 2), dtype=int)
        
        # Filter matches by IoU threshold - Đơn giản và hiệu quả
        matches = []
        for m in matched_indices:
            if iou_matrix[m[0], m[1]] >= iou_threshold:
                matches.append([m[1], m[0]])  # [track_idx, det_idx]
        
        matches = np.array(matches) if len(matches) > 0 else np.empty((0, 2), dtype=int)
        
        # Get unmatched detections and trackers
        unmatched_detections = []
        for d in range(len(detections)):
            if len(matches) == 0 or d not in matches[:, 1]:
                unmatched_detections.append(d)
        
        unmatched_trackers = []
        for t in range(len(trackers)):
            if len(matches) == 0 or t not in matches[:, 0]:
                unmatched_trackers.append(t)
        
        return matches, np.array(unmatched_detections), np.array(unmatched_trackers)
    
    @staticmethod
    def iou_batch(bboxes1, bboxes2):
        """Compute IoU between two sets of bboxes"""
        bboxes2 = np.expand_dims(bboxes2, 0)
        bboxes1 = np.expand_dims(bboxes1, 1)
        
        xx1 = np.maximum(bboxes1[..., 0], bboxes2[..., 0])
        yy1 = np.maximum(bboxes1[..., 1], bboxes2[..., 1])
        xx2 = np.minimum(bboxes1[..., 2], bboxes2[..., 2])
        yy2 = np.minimum(bboxes1[..., 3], bboxes2[..., 3])
        
        w = np.maximum(0., xx2 - xx1)
        h = np.maximum(0., yy2 - yy1)
        
        wh = w * h
        o = wh / ((bboxes1[..., 2] - bboxes1[..., 0]) * (bboxes1[..., 3] - bboxes1[..., 1]) +
                  (bboxes2[..., 2] - bboxes2[..., 0]) * (bboxes2[..., 3] - bboxes2[..., 1]) - wh)
        
        return o

