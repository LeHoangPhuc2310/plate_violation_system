# 📊 Phân tích Thread trong Hệ thống

## 🎯 Tổng quan

Hệ thống sử dụng **Multi-threading Architecture** để xử lý real-time video và phát hiện vi phạm.

---

## 📋 Danh sách Thread

### 🔴 **Thread chính (Core Threads) - 7 Threads**

Các thread này chạy liên tục khi có video đang được xử lý:

| # | Thread Name | Function | Mục đích | Queue Input | Queue Output | Status |
|---|------------|----------|----------|-------------|--------------|--------|
| 1 | **video_stream_thread** | `video_thread()` | Đọc frame từ video và push vào queues | - | `detection_queue`, `stream_queue_clean`, `alpr_proactive_queue` | ✅ Core |
| 2 | **detection_worker_thread** | `detection_worker()` | YOLO detection + OC-SORT tracking + Speed calculation | `detection_queue` | `alpr_realtime_queue` | ✅ Core |
| 3 | **alpr_proactive_thread** | `alpr_proactive_worker()` | ALPR proactive detection (background) | `alpr_proactive_queue` | Cache | ✅ Core |
| 4 | **alpr_realtime_thread** | `alpr_realtime_worker()` | ALPR realtime detection (khi có violation) | `alpr_realtime_queue` | `best_frame_queue` | ✅ Core |
| 5 | **best_frame_thread** | `best_frame_selector_worker()` | Chọn frame tốt nhất từ buffer | `best_frame_queue` | `violation_queue` | ✅ Core |
| 6 | **violation_worker_thread** | `violation_worker()` | Lưu DB, ảnh, video vi phạm | `violation_queue` | `telegram_queue` | ✅ Core |
| 7 | **telegram_worker_thread_obj** | `telegram_worker()` | Gửi thông báo Telegram | `telegram_queue` | - | ✅ Core |

### 🟡 **Thread hỗ trợ (Support Threads) - 2 Threads**

Các thread này chạy khi cần thiết:

| # | Thread Name | Function | Mục đích | Khi nào chạy | Status |
|---|------------|----------|----------|-------------|--------|
| 8 | **db_test_thread** | `test_db_connection_async()` | Test database connection | Khi app khởi động | ✅ Support |
| 9 | **telegram_worker_thread** | `telegram_worker()` | Telegram worker (alternative) | Khi `start_telegram_worker()` được gọi | ⚠️ Duplicate với #7 |

### 🟢 **Thread tạm thời (Temporary Threads) - 2 Threads**

Các thread này chạy một lần và tự kết thúc:

| # | Thread Name | Function | Mục đích | Khi nào chạy | Status |
|---|------------|----------|----------|-------------|--------|
| 10 | **stop_thread** | `stop_current_video()` | Dừng video hiện tại | Khi upload video mới | 🔄 Temporary |
| 11 | **process_thread** | `process_video_async()` | Xử lý video upload async | Khi upload video | 🔄 Temporary |

### ⚠️ **Thread không sử dụng (Deprecated)**

| # | Thread Name | Function | Mục đích | Status |
|---|------------|----------|----------|--------|
| 12 | **alpr_worker_thread_obj** | `alpr_worker_thread()` | ALPR worker (old) | ❌ Deprecated (không được gọi trong `start_video_thread()`) |

---

## 🔄 Flow Diagram

```
┌─────────────────────────────────────────────────────────────┐
│  🎬 THREAD 1: video_thread()                                 │
│  - Đọc frame từ video                                        │
│  - Push vào detection_queue                                  │
│  - Push vào stream_queue_clean (cho web stream)             │
│  - Push vào alpr_proactive_queue                            │
└──────────────┬──────────────────────────────────────────────┘
               │ detection_queue
               ▼
┌─────────────────────────────────────────────────────────────┐
│  🔍 THREAD 2: detection_worker()                           │
│  - YOLOv11: Detect vehicles                                 │
│  - OC-SORT: Track objects                                   │
│  - SpeedTracker: Calculate speed                           │
│  - Detect violations (> speed_limit)                        │
└──────────────┬──────────────────────────────────────────────┘
               │ alpr_realtime_queue (khi có violation)
               ▼
┌─────────────────────────────────────────────────────────────┐
│  🔤 THREAD 4: alpr_realtime_worker()                        │
│  - FastALPR: Detect license plates                          │
│  - Validate plate format                                    │
└──────────────┬──────────────────────────────────────────────┘
               │ best_frame_queue
               ▼
┌─────────────────────────────────────────────────────────────┐
│  🖼️ THREAD 5: best_frame_selector_worker()                  │
│  - Select best quality frame                                │
│  - Aggregate plate detections                               │
│  - Add violation timestamp & frame number                   │
└──────────────┬──────────────────────────────────────────────┘
               │ violation_queue
               ▼
┌─────────────────────────────────────────────────────────────┐
│  💾 THREAD 6: violation_worker()                            │
│  - Save to MySQL database                                   │
│  - Create violation videos (FFmpeg/OpenCV)                 │
│  - Save vehicle & plate images                              │
│  - Anti-duplicate check (5s cooldown)                       │
└──────────────┬──────────────────────────────────────────────┘
               │ telegram_queue
               ▼
┌─────────────────────────────────────────────────────────────┐
│  📱 THREAD 7: telegram_worker()                             │
│  - Send notifications to Telegram                          │
│  - Update violation status                                  │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│  🔤 THREAD 3: alpr_proactive_worker() (Parallel)            │
│  - Background ALPR detection                               │
│  - Cache results                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 📊 Thống kê

### Tổng số Thread

- **Core Threads (chạy liên tục):** 7 threads
- **Support Threads:** 2 threads
- **Temporary Threads:** 2 threads
- **Deprecated Threads:** 1 thread

### **Tổng cộng: 12 thread definitions**

### Threads thực tế chạy đồng thời

- **Khi app khởi động:** 1 thread (db_test_thread)
- **Khi có video đang xử lý:** 7-8 threads (7 core + 1 support)
- **Khi upload video mới:** +2 threads tạm thời (stop_thread, process_thread)

**Maximum concurrent threads: ~10 threads**

---

## 🔍 Chi tiết từng Thread

### 1. video_thread() - Thread 1

**File:** `app.py:2535`

**Mục đích:**
- Đọc frame từ video file hoặc camera
- Push frame vào `detection_queue` để xử lý
- Push frame vào `stream_queue_clean` để stream lên web
- Push frame vào `alpr_proactive_queue` để ALPR proactive

**Queue Output:**
- `detection_queue`
- `stream_queue_clean`
- `alpr_proactive_queue`

**Status:** ✅ Core Thread

---

### 2. detection_worker() - Thread 2

**File:** `app.py:1517`

**Mục đích:**
- Nhận frame từ `detection_queue`
- YOLOv11: Detect vehicles
- OC-SORT/ByteTrack: Track objects
- SpeedTracker: Calculate speed
- Detect violations (speed > speed_limit)
- Push vào `alpr_realtime_queue` khi có violation

**Queue Input:** `detection_queue`
**Queue Output:** `alpr_realtime_queue`

**Status:** ✅ Core Thread

---

### 3. alpr_proactive_worker() - Thread 3

**File:** `app.py:1727`

**Mục đích:**
- Background ALPR detection
- Cache kết quả vào `alpr_proactive_cache`
- Chạy song song với detection worker

**Queue Input:** `alpr_proactive_queue`
**Queue Output:** Cache (alpr_proactive_cache)

**Status:** ✅ Core Thread

---

### 4. alpr_realtime_worker() - Thread 4

**File:** `app.py:1789`

**Mục đích:**
- ALPR detection khi có violation
- FastALPR: Detect license plates
- Validate plate format (Vietnamese)
- Push vào `best_frame_queue`

**Queue Input:** `alpr_realtime_queue`
**Queue Output:** `best_frame_queue`

**Status:** ✅ Core Thread

---

### 5. best_frame_selector_worker() - Thread 5

**File:** `app.py:1888`

**Mục đích:**
- Nhận data từ `best_frame_queue`
- Chọn frame tốt nhất từ buffer (dựa trên blur, size, position)
- Aggregate plate detections
- Add violation timestamp & frame number
- Push vào `violation_queue`

**Queue Input:** `best_frame_queue`
**Queue Output:** `violation_queue`

**Status:** ✅ Core Thread

---

### 6. violation_worker() - Thread 6

**File:** `app.py:1956`

**Mục đích:**
- Nhận violation data từ `violation_queue`
- Save to MySQL database
- Create violation videos (FFmpeg/OpenCV fallback)
- Save vehicle & plate images
- Anti-duplicate check (5s cooldown)
- Push vào `telegram_queue`

**Queue Input:** `violation_queue`
**Queue Output:** `telegram_queue`

**Status:** ✅ Core Thread

---

### 7. telegram_worker() - Thread 7

**File:** `app.py:450`

**Mục đích:**
- Nhận violation data từ `telegram_queue`
- Send notifications to Telegram
- Update violation status trong database

**Queue Input:** `telegram_queue`
**Queue Output:** -

**Status:** ✅ Core Thread

---

### 8. test_db_connection_async() - Thread 8

**File:** `app.py:87`

**Mục đích:**
- Test database connection khi app khởi động
- Chạy một lần và tự kết thúc

**Status:** ✅ Support Thread

---

### 9. telegram_worker_thread - Thread 9

**File:** `app.py:506`

**Mục đích:**
- Alternative Telegram worker
- Có thể duplicate với Thread 7

**Status:** ⚠️ Duplicate

---

### 10. stop_current_video() - Thread 10

**File:** `app.py:3227`

**Mục đích:**
- Dừng video hiện tại khi upload video mới
- Chạy async để không block upload

**Status:** 🔄 Temporary Thread

---

### 11. process_video_async() - Thread 11

**File:** `app.py:3370`

**Mục đích:**
- Xử lý video upload async
- Set current_video_path và khởi động video thread

**Status:** 🔄 Temporary Thread

---

### 12. alpr_worker_thread() - Thread 12 (Deprecated)

**File:** `app.py:2632`

**Mục đích:**
- Old ALPR worker (không được sử dụng nữa)
- Đã được thay thế bởi `alpr_realtime_worker()` và `alpr_proactive_worker()`

**Status:** ❌ Deprecated

---

## 🎯 Kết luận

### Thread Architecture

Hệ thống sử dụng **7 Core Threads** chạy liên tục khi có video đang được xử lý:

1. **Video Thread** - Đọc video
2. **Detection Worker** - Detect & Track
3. **ALPR Proactive** - Background ALPR
4. **ALPR Realtime** - Realtime ALPR
5. **Best Frame Selector** - Chọn frame tốt nhất
6. **Violation Worker** - Lưu DB & files
7. **Telegram Worker** - Gửi thông báo

### Thread Flow

```
Video → Detection → ALPR → Best Frame → Violation → Telegram
         ↓
    ALPR Proactive (parallel)
```

### Performance

- **Concurrent threads:** 7-10 threads (tùy thời điểm)
- **Thread type:** Daemon threads (tự động dừng khi app dừng)
- **Queue-based:** Sử dụng queue để giao tiếp giữa threads
- **Non-blocking:** Tất cả threads chạy async, không block main thread

---

**📝 Ghi chú:** README.md nói "6-thread architecture" nhưng thực tế có **7 core threads** (bao gồm cả ALPR Proactive worker).

