# 🐳 Hướng dẫn chạy ứng dụng với Docker

## 📋 Yêu cầu

- Docker Desktop đã cài đặt và đang chạy
- MySQL đã cài đặt (có thể chạy trong Docker hoặc local)
- Telegram Bot Token (nếu muốn dùng tính năng thông báo)

## 🚀 Các bước chạy Docker

### Bước 1: Tạo file `.env`

Tạo file `.env` từ `.env.example`:

```bash
# Trên Windows PowerShell
Copy-Item .env.example .env

# Hoặc trên Linux/Mac
cp .env.example .env
```

Sau đó mở file `.env` và điền thông tin:

```env
MYSQL_HOST=host.docker.internal  # Nếu MySQL chạy trên Windows/Mac
# Hoặc
MYSQL_HOST=172.17.0.1            # Nếu MySQL chạy trên Linux

MYSQL_USER=root
MYSQL_PASSWORD=your-password
MYSQL_DB=plate_violation

SECRET_KEY=your-secret-key-here
TELEGRAM_TOKEN=your-telegram-bot-token
TELEGRAM_CHAT_ID=your-chat-id
```

### Bước 2: Chọn Dockerfile phù hợp

#### Option A: Có GPU NVIDIA (Dockerfile - mặc định)
```bash
docker build -t plate-violation:latest .
```

#### Option B: Chỉ có CPU (Dockerfile.cpu)
```bash
docker build -f Dockerfile.cpu -t plate-violation:latest .
```

### Bước 3: Chạy MySQL trong Docker (nếu chưa có)

Nếu bạn chưa có MySQL, có thể chạy MySQL trong Docker:

```bash
docker run -d \
  --name mysql-plate \
  -e MYSQL_ROOT_PASSWORD=your-password \
  -e MYSQL_DATABASE=plate_violation \
  -p 3306:3306 \
  mysql:8.0
```

Sau đó cập nhật `.env`:
```env
MYSQL_HOST=mysql-plate  # Tên container MySQL
```

### Bước 4: Tạo database và tables

Kết nối vào MySQL và tạo database:

```bash
# Nếu MySQL chạy trong Docker
docker exec -it mysql-plate mysql -uroot -p

# Hoặc nếu MySQL chạy local
mysql -uroot -p
```

Trong MySQL console:
```sql
CREATE DATABASE IF NOT EXISTS plate_violation;
USE plate_violation;

-- Tạo bảng violations
CREATE TABLE IF NOT EXISTS violations (
    id INT AUTO_INCREMENT PRIMARY KEY,
    plate VARCHAR(20) NOT NULL,
    vehicle_class VARCHAR(50),
    speed FLOAT,
    speed_limit FLOAT DEFAULT 60.0,
    image VARCHAR(255),
    plate_image VARCHAR(255),
    video VARCHAR(255),
    time DATETIME DEFAULT CURRENT_TIMESTAMP,
    status VARCHAR(20) DEFAULT 'pending'
);

-- Tạo bảng vehicle_owner
CREATE TABLE IF NOT EXISTS vehicle_owner (
    plate VARCHAR(20) PRIMARY KEY,
    owner_name VARCHAR(255),
    address TEXT,
    phone VARCHAR(20)
);
```

### Bước 5: Chạy ứng dụng trong Docker

#### Nếu MySQL chạy trong Docker (cùng network):

```bash
# Tạo network
docker network create plate-network

# Chạy MySQL (nếu chưa chạy)
docker run -d \
  --name mysql-plate \
  --network plate-network \
  -e MYSQL_ROOT_PASSWORD=your-password \
  -e MYSQL_DATABASE=plate_violation \
  mysql:8.0

# Chạy ứng dụng
docker run -d \
  --name plate-violation-app \
  --network plate-network \
  -p 5000:5000 \
  --env-file .env \
  -v ${PWD}/uploads:/app/uploads \
  -v ${PWD}/static:/app/static \
  plate-violation:latest
```

#### Nếu MySQL chạy trên host (Windows/Mac):

```bash
docker run -d \
  --name plate-violation-app \
  -p 5000:5000 \
  --env-file .env \
  --add-host=host.docker.internal:host-gateway \
  -v ${PWD}/uploads:/app/uploads \
  -v ${PWD}/static:/app/static \
  plate-violation:latest
```

**Lưu ý trên Windows PowerShell:**
```powershell
docker run -d `
  --name plate-violation-app `
  -p 5000:5000 `
  --env-file .env `
  --add-host=host.docker.internal:host-gateway `
  -v ${PWD}/uploads:/app/uploads `
  -v ${PWD}/static:/app/static `
  plate-violation:latest
```

### Bước 6: Kiểm tra logs

```bash
docker logs -f plate-violation-app
```

### Bước 7: Truy cập ứng dụng

Mở trình duyệt và truy cập:
- **http://localhost:5000**

## 🔧 Các lệnh Docker hữu ích

### Xem logs
```bash
docker logs plate-violation-app
docker logs -f plate-violation-app  # Theo dõi real-time
```

### Dừng container
```bash
docker stop plate-violation-app
```

### Khởi động lại container
```bash
docker start plate-violation-app
```

### Xóa container
```bash
docker stop plate-violation-app
docker rm plate-violation-app
```

### Rebuild image (sau khi sửa code)
```bash
docker stop plate-violation-app
docker rm plate-violation-app
docker build -f Dockerfile.cpu -t plate-violation:latest .
docker run -d --name plate-violation-app -p 5000:5000 --env-file .env plate-violation:latest
```

### Vào trong container
```bash
docker exec -it plate-violation-app bash
```

### Xem các container đang chạy
```bash
docker ps
```

### Xem tất cả containers (kể cả đã dừng)
```bash
docker ps -a
```

## 🐛 Xử lý lỗi

### Lỗi: Cannot connect to MySQL

**Giải pháp:**
1. Kiểm tra MySQL đang chạy:
   ```bash
   docker ps | grep mysql
   ```

2. Kiểm tra `MYSQL_HOST` trong `.env`:
   - Nếu MySQL trong Docker: dùng tên container hoặc IP
   - Nếu MySQL trên host: dùng `host.docker.internal` (Windows/Mac) hoặc `172.17.0.1` (Linux)

3. Kiểm tra network:
   ```bash
   docker network ls
   docker network inspect plate-network
   ```

### Lỗi: Port 5000 already in use

**Giải pháp:**
Đổi port trong lệnh docker run:
```bash
docker run -d -p 8080:5000 ...  # Dùng port 8080 thay vì 5000
```

### Lỗi: CUDA/GPU not found

**Giải pháp:**
Dùng `Dockerfile.cpu` thay vì `Dockerfile`:
```bash
docker build -f Dockerfile.cpu -t plate-violation:latest .
```

## 📝 Docker Compose (Tùy chọn)

Tạo file `docker-compose.yml` để chạy cả MySQL và ứng dụng:

```yaml
version: '3.8'

services:
  mysql:
    image: mysql:8.0
    container_name: mysql-plate
    environment:
      MYSQL_ROOT_PASSWORD: your-password
      MYSQL_DATABASE: plate_violation
    ports:
      - "3306:3306"
    volumes:
      - mysql_data:/var/lib/mysql

  app:
    build:
      context: .
      dockerfile: Dockerfile.cpu
    container_name: plate-violation-app
    ports:
      - "5000:5000"
    env_file:
      - .env
    volumes:
      - ./uploads:/app/uploads
      - ./static:/app/static
    depends_on:
      - mysql

volumes:
  mysql_data:
```

Chạy với Docker Compose:
```bash
docker-compose up -d
```

Xem logs:
```bash
docker-compose logs -f
```

## ✅ Checklist trước khi chạy

- [ ] Docker Desktop đang chạy
- [ ] File `.env` đã được tạo và điền đầy đủ
- [ ] MySQL đã được cài đặt và chạy
- [ ] Database `plate_violation` đã được tạo
- [ ] Các bảng `violations` và `vehicle_owner` đã được tạo
- [ ] Telegram Bot Token (nếu muốn dùng tính năng thông báo)

## 🎉 Hoàn thành!

Sau khi hoàn thành các bước trên, ứng dụng sẽ chạy tại **http://localhost:5000**

