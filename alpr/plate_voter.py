from typing import Dict, List, Optional
from collections import Counter
from .plate_validator import PlateValidator
from .plate_format_validator import PlateFormatValidator  # Stricter validation
from .plate_validation_state import PlateValidationState, PlateValidator as StateValidator, PlateImageValidator


class PlateVoter:

    def __init__(self, min_consensus: int = 2):
        self.min_consensus = min_consensus
        self._results: Dict[int, List] = {}

    def reset(self):
        self._results.clear()

    def vote(self, track_id: int, ocr_results: List, best_frames: List) -> Optional[Dict]:
        valid_results = []
        MIN_CONFIDENCE = 0.25  # Balance: không quá thấp (0.2) cũng không quá cao (0.3)
        
        for i, result in enumerate(ocr_results):
            if result and result.get('plate_text'):
                plate_text = result['plate_text']
                confidence = result.get('confidence', 0.0)
                plate_image = result.get('plate_image')
                # Get frame_id from result
                frame_id = result.get('frame_id')
                frame_type = result.get('frame_type', 'unknown')
                
                # Bỏ qua nếu confidence quá thấp
                if confidence < MIN_CONFIDENCE:
                    continue
                
                # Use PlateFormatValidator for STRICT Vietnam plate validation
                # Old PlateValidator had loose patterns that accepted invalid plates like "43574RR"
                is_valid, normalized, reason = PlateFormatValidator.validate(plate_text)
                if not is_valid:
                    # Reject invalid format - PlateFormatValidator already tries OCR corrections
                    print(f"[VOTER] [ERR] REJECT: Invalid plate format: '{plate_text}' | {reason}")
                    continue

                # Use normalized plate text
                plate_text = normalized

                # Check confidence after validation - tăng ngưỡng để tránh đoán bừa khi biển số mờ
                if confidence < 0.75:
                    print(f"[VOTER] [ERR] REJECT: Low confidence ({confidence:.2f} < 0.75) for '{plate_text}' - biển số quá mờ, không đoán bừa")
                    continue

                print(f"[VOTER] [OK] Valid plate: '{plate_text}' (conf={confidence:.2f}, frame_id={frame_id})")
                
                # QUAN TRỌNG: Chỉ chấp nhận nếu có plate_image
                if plate_image is None:
                    print(f"[VOTER] [WARN] No plate_image for plate '{plate_text}', skipping")
                    continue

                # Validate image quality (but don't reject, just record sharpness)
                is_valid_image, reason, sharpness = PlateImageValidator.validate_plate_image(plate_image)
                if not is_valid_image:
                    print(f"[VOTER] [WARN] Plate image quality issue for '{plate_text}': {reason} (sharpness={sharpness:.1f}) - Still including")
                    # Still add to valid_results but with low sharpness score

                # Find matching vehicle_image from best_frames
                vehicle_image = None
                if best_frames:
                    # Try to find matching frame_id in best_frames
                    if frame_id is not None:
                        for frame_data in best_frames:
                            frame_data_id = frame_data.get('frame_id') or frame_data.get('metadata', {}).get('frame_number')
                            if frame_data_id == frame_id:
                                vehicle_image = frame_data.get('vehicle_image')
                                break
                    # Fallback: use index if frame_id not found
                    if vehicle_image is None and i < len(best_frames):
                        vehicle_image = best_frames[i].get('vehicle_image')

                valid_results.append({
                    'plate_text': normalized,
                    'confidence': confidence,
                    'index': i,
                    'plate_image': plate_image,
                    'vehicle_image': vehicle_image,  # Include vehicle_image
                    'sharpness': sharpness,
                    'is_valid_image': is_valid_image,
                    'frame_id': frame_id,                     'frame_type': frame_type                 })

        if not valid_results:
            return None

        # Group candidates by frame_id
        # Đảm bảo plate_text, plate_image, và vehicle_image luôn từ CÙNG MỘT FRAME
        frames_dict = {}  # {frame_id: [candidates]}
        
        for r in valid_results:
            frame_id = r.get('frame_id')
            # Use frame_id if available, otherwise use a unique identifier
            if frame_id is None:
                # Fallback: use index as frame_id for candidates without frame tracking
                frame_id = f"unknown_{r['index']}"
            
            if frame_id not in frames_dict:
                frames_dict[frame_id] = []
            frames_dict[frame_id].append(r)

        print(f"[VOTER] [OK] Grouped {len(valid_results)} candidates into {len(frames_dict)} frames")

        # Score each frame and select ONE best frame
        best_frame_id = None
        best_frame_score = 0.0
        best_frame_candidates = None

        for frame_id, candidates in frames_dict.items():
            # Score frame based on:
            # 1. Vote count (how many times same plate_text appears)
            # 2. Average confidence
            # 3. Best sharpness
            plate_texts = [c['plate_text'] for c in candidates]
            counter = Counter(plate_texts)
            most_common = counter.most_common(1)
            
            if not most_common:
                continue
            
            best_plate_in_frame, vote_count = most_common[0]
            avg_confidence = sum(c['confidence'] for c in candidates) / len(candidates)
            max_sharpness = max(c.get('sharpness', 0.0) for c in candidates)
            
            # Combined score: vote_count * avg_confidence * (sharpness / 100)
            frame_score = vote_count * avg_confidence * (1 + max_sharpness / 1000.0)
            
            print(f"[VOTER] Frame {frame_id}: plate='{best_plate_in_frame}', votes={vote_count}, conf={avg_confidence:.2f}, sharp={max_sharpness:.0f}, score={frame_score:.2f}")
            
            if frame_score > best_frame_score:
                best_frame_score = frame_score
                best_frame_id = frame_id
                best_frame_candidates = candidates

        if best_frame_candidates is None:
            print(f"[VOTER] [ERR] No valid frame found")
            return None

        # Select best candidate from the best frame
        # Vote on plate_text within the best frame
        plate_texts = [c['plate_text'] for c in best_frame_candidates]
        counter = Counter(plate_texts)
        most_common = counter.most_common(1)
        
        if not most_common:
            return None
        
        best_plate_text, vote_count = most_common[0]

        # Find best candidate with best_plate_text in the best frame
        best_result = None
        best_conf = 0.0
        
        for c in best_frame_candidates:
            if c['plate_text'] == best_plate_text and c['confidence'] > best_conf:
                best_conf = c['confidence']
                best_result = c

        if best_result is None:
            # Fallback: use candidate with highest confidence
            best_result = max(best_frame_candidates, key=lambda x: x['confidence'])
            best_plate_text = best_result['plate_text']
            best_conf = best_result['confidence']
            vote_count = 1

        # Get plate_image and vehicle_image from the SAME candidate
        plate_image = best_result.get('plate_image')
        vehicle_image = best_result.get('vehicle_image')
        frame_id = best_result.get('frame_id')
        frame_type = best_result.get('frame_type', 'unknown')

        # Validate plate_image
        if plate_image is None:
            print(f"[VOTER] [ERR] No plate_image for plate '{best_plate_text}' in frame {frame_id}, rejecting")
            return None

        # Check plate_image is valid numpy array
        try:
            import numpy as np
            if isinstance(plate_image, np.ndarray):
                if plate_image.size == 0:
                    print(f"[VOTER] [ERR] Empty plate_image for plate '{best_plate_text}' in frame {frame_id}, rejecting")
                    return None
        except:
            pass

        # Determine validation state
        validation_state = StateValidator.determine_state(best_plate_text, plate_image, text_is_valid=True)

        # Get metrics
        sharpness = best_result.get('sharpness', 0.0)
        is_valid_image = best_result.get('is_valid_image', False)

        print(f"[VOTER] [OK] SELECTED FRAME {frame_id} (type={frame_type}): plate='{best_plate_text}' (votes={vote_count}/{len(best_frame_candidates)}, conf={best_conf:.2f}, sharpness={sharpness:.1f}, state={validation_state.value})")
        print(f"[VOTER] [OK] ALL IMAGES FROM SAME FRAME: plate_image={'YES' if plate_image is not None else 'NO'}, vehicle_image={'YES' if vehicle_image is not None else 'NO'}")

        return {
            'plate_text': best_plate_text,
            'confidence': best_conf,
            'vote_count': vote_count,
            'total_votes': len(best_frame_candidates),
            'plate_image': plate_image,
            'vehicle_image': vehicle_image,
            'validation_state': validation_state,
            'sharpness': sharpness,
            'frame_id': frame_id,  # Return frame_id
            'frame_type': frame_type  # Return frame_type
        }
