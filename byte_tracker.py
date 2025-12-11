# byte_tracker.py
"""
ByteTrack - Fast and accurate multi-object tracking with Kalman Filter
Optimized for vehicle tracking - NO MORE JITTERING!
"""
import numpy as np
from filterpy.kalman import KalmanFilter

class TrackState:
    New = 0
    Tracked = 1
    Lost = 2
    Removed = 3

class Track:
    def __init__(self, tlbr, score, cls, track_id, frame_id):
        self.tlbr = tlbr  # [x1, y1, x2, y2]
        self.score = score
        self.cls = cls
        self.track_id = track_id
        self.frame_id = frame_id
        self.state = TrackState.New
        self.is_activated = False
        self.tracklet_len = 0
        
        # KALMAN FILTER - FIX TRACKING BỊ LỆCH
        self.kf = KalmanFilter(dim_x=8, dim_z=4)
        
        # State: [x1, y1, x2, y2, vx1, vy1, vx2, vy2]
        self.kf.x[:4] = tlbr.reshape((4, 1))
        
        # State transition matrix (constant velocity model)
        self.kf.F = np.array([
            [1, 0, 0, 0, 1, 0, 0, 0],  # x1 = x1 + vx1
            [0, 1, 0, 0, 0, 1, 0, 0],  # y1 = y1 + vy1
            [0, 0, 1, 0, 0, 0, 1, 0],  # x2 = x2 + vx2
            [0, 0, 0, 1, 0, 0, 0, 1],  # y2 = y2 + vy2
            [0, 0, 0, 0, 1, 0, 0, 0],  # vx1 = vx1
            [0, 0, 0, 0, 0, 1, 0, 0],  # vy1 = vy1
            [0, 0, 0, 0, 0, 0, 1, 0],  # vx2 = vx2
            [0, 0, 0, 0, 0, 0, 0, 1],  # vy2 = vy2
        ])
        
        # Measurement matrix
        self.kf.H = np.array([
            [1, 0, 0, 0, 0, 0, 0, 0],
            [0, 1, 0, 0, 0, 0, 0, 0],
            [0, 0, 1, 0, 0, 0, 0, 0],
            [0, 0, 0, 1, 0, 0, 0, 0],
        ])
        
        # Measurement noise - giảm để tin tưởng detection hơn
        self.kf.R *= 0.8
        
        # Process noise - giảm để velocity update nhanh hơn, theo kịp xe
        self.kf.Q[-4:, -4:] *= 0.05  # Tăng từ 0.01 lên 0.05 để velocity update nhanh hơn
        self.kf.Q[:4, :4] *= 0.15    # Tăng từ 0.1 lên 0.15 để position update nhanh hơn
        
        # Initial covariance
        self.kf.P *= 10.0
        self.kf.P[-4:, -4:] *= 500.0  # Giảm từ 1000 xuống 500 để velocity ổn định nhanh hơn
    
    def predict(self):
        """Predict next position using Kalman Filter - Cải thiện để tracking mượt hơn"""
        self.kf.predict()
        predicted_tlbr = self.kf.x[:4].flatten()
        # Đảm bảo tọa độ hợp lệ
        if predicted_tlbr[2] > predicted_tlbr[0] and predicted_tlbr[3] > predicted_tlbr[1]:
            return predicted_tlbr
        else:
            # Fallback về tlbr hiện tại nếu prediction không hợp lệ
            return self.tlbr
    
    def update(self, new_tlbr):
        """Update track with new detection - ưu tiên detection để theo kịp xe"""
        # Update Kalman filter
        self.kf.update(new_tlbr.reshape((4, 1)))
        kalman_result = self.kf.x[:4].reshape((4,))
        
        # Nếu detection mới khác nhiều với prediction, dùng detection trực tiếp (theo kịp xe)
        predicted = self.predict()
        if np.linalg.norm(new_tlbr - predicted) > 30:  # Giảm từ 50 xuống 30 để phản ứng nhanh hơn
            # Dùng detection trực tiếp để theo kịp xe
            self.tlbr = new_tlbr
            # Cập nhật Kalman state để đồng bộ
            self.kf.x[:4] = new_tlbr.reshape((4, 1))
        else:
            # Dùng kết quả Kalman (mượt hơn)
            self.tlbr = kalman_result

class BYTETracker:
    def __init__(self, frame_rate=30, track_thresh=0.2, track_buffer=30, match_thresh=0.4):
        self.frame_rate = frame_rate
        self.track_thresh = track_thresh
        self.track_buffer = track_buffer
        self.match_thresh = match_thresh
        
        self.frame_id = 0
        self.track_id = 0
        self.tracks = []
        self.lost_tracks = []
        self.removed_tracks = []
        
    def update(self, detections, frame):
        """
        Update tracker with new detections
        Args:
            detections: numpy array of shape (N, 6) - [x1, y1, x2, y2, conf, cls]
            frame: current frame (not used but kept for compatibility)
        Returns:
            list of Track objects
        """
        self.frame_id += 1
        activated_tracks = []
        refined_tracks = []
        lost_tracks = []
        removed_tracks = []
        
        # Separate high and low confidence detections
        dets_high = detections[detections[:, 4] > self.track_thresh]
        dets_low = detections[detections[:, 4] <= self.track_thresh]
        
        # Update existing tracks
        unconfirmed = []
        tracked_tracks = []
        for track in self.tracks:
            if not track.is_activated:
                unconfirmed.append(track)
            else:
                tracked_tracks.append(track)
        
        # Initialize unmatched indices - FIX: Phải khởi tạo TRƯỚC
        u_track = []
        u_det = list(range(len(dets_high)))
        
        # Simple matching based on IoU
        if len(tracked_tracks) > 0 and len(dets_high) > 0:
            matches, u_track, u_det = self.associate(tracked_tracks, dets_high)
            
            for itracked, idet in matches:
                track = tracked_tracks[itracked]
                det = dets_high[idet]
                # Update với Kalman Filter - KHÔNG BỊ LỆCH
                track.update(det[:4])
                track.score = det[4]
                track.cls = int(det[5])
                track.tracklet_len += 1
                track.frame_id = self.frame_id  # Update frame_id
                activated_tracks.append(track)
            
            # Lost tracks - predict position để tracking mượt hơn
            for it in u_track:
                track = tracked_tracks[it]
                if track.state != TrackState.Lost:
                    track.state = TrackState.Lost
                    # Predict vị trí tiếp theo dựa trên velocity
                    track.tlbr = track.predict()
                    lost_tracks.append(track)
        else:
            # No existing tracks or no detections
            u_track = list(range(len(tracked_tracks)))
            u_det = list(range(len(dets_high)))
            # All existing tracks become lost
            for track in tracked_tracks:
                if track.state != TrackState.Lost:
                    track.state = TrackState.Lost
                    lost_tracks.append(track)
        
        # Create new tracks from unmatched detections
        for idet in u_det:
            det = dets_high[idet]
            self.track_id += 1
            track = Track(det[:4], det[4], int(det[5]), self.track_id, self.frame_id)
            track.is_activated = True
            track.state = TrackState.Tracked
            activated_tracks.append(track)
        
        # Update lost tracks
        for track in self.lost_tracks:
            if self.frame_id - track.frame_id > self.track_buffer:
                track.state = TrackState.Removed
                removed_tracks.append(track)
            else:
                lost_tracks.append(track)
        
        # Update tracks
        self.tracks = [t for t in self.tracks if t.state != TrackState.Removed]
        self.tracks.extend(activated_tracks)
        self.tracks.extend(lost_tracks)
        self.lost_tracks = [t for t in lost_tracks if t.state != TrackState.Removed]
        
        # Return active tracks
        output_tracks = [t for t in self.tracks if t.is_activated and t.state == TrackState.Tracked]
        return output_tracks
    
    def associate(self, tracks, detections):
        """Simple IoU-based association"""
        if len(tracks) == 0 or len(detections) == 0:
            return [], list(range(len(tracks))), list(range(len(detections)))
        
        # Calculate IoU matrix
        iou_matrix = np.zeros((len(tracks), len(detections)))
        for i, track in enumerate(tracks):
            for j, det in enumerate(detections):
                iou_matrix[i, j] = self.iou(track.tlbr, det[:4])
        
        # Greedy matching
        matches = []
        u_track = list(range(len(tracks)))
        u_det = list(range(len(detections)))
        
        # Sort by IoU descending
        indices = np.unravel_index(np.argsort(iou_matrix, axis=None)[::-1], iou_matrix.shape)
        
        for i, j in zip(indices[0], indices[1]):
            if iou_matrix[i, j] >= self.match_thresh and i in u_track and j in u_det:
                matches.append([i, j])
                u_track.remove(i)
                u_det.remove(j)
        
        return matches, u_track, u_det
    
    @staticmethod
    def iou(box1, box2):
        """Calculate IoU between two boxes"""
        x1 = max(box1[0], box2[0])
        y1 = max(box1[1], box2[1])
        x2 = min(box1[2], box2[2])
        y2 = min(box1[3], box2[3])
        
        if x2 < x1 or y2 < y1:
            return 0.0
        
        inter = (x2 - x1) * (y2 - y1)
        area1 = (box1[2] - box1[0]) * (box1[3] - box1[1])
        area2 = (box2[2] - box2[0]) * (box2[3] - box2[1])
        union = area1 + area2 - inter
        
        if union == 0:
            return 0.0
        
        return inter / union

