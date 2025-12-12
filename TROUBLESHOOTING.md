# 🔧 Troubleshooting Guide

## Lỗi: Port 5000 đang được sử dụng

### Nguyên nhân
- Container Docker đang chạy trên port 5000
- Process Python khác đang chạy
- Service khác đang dùng port 5000

### Giải pháp

#### 1. Kiểm tra và dừng Docker container

```bash
# Xem container đang chạy
docker ps

# Dừng container plate-violation-app
docker stop plate-violation-app

# Hoặc xóa container
docker rm -f plate-violation-app
```

#### 2. Kiểm tra process đang dùng port 5000

```bash
# Cách 1: Dùng lsof
sudo lsof -i :5000

# Cách 2: Dùng netstat
sudo netstat -tulpn | grep :5000

# Cách 3: Dùng fuser
sudo fuser 5000/tcp
```

#### 3. Dừng process

```bash
# Tìm PID từ lệnh trên, sau đó:
sudo kill -9 <PID>
```

#### 4. Dùng script tự động

```bash
chmod +x fix-port-5000.sh
./fix-port-5000.sh
```

#### 5. Hoặc đổi port trong app.py

Sửa file `app.py`:
```python
if __name__ == '__main__':
    port = int(os.getenv('PORT', 5001))  # Đổi sang port 5001
    app.run(host='0.0.0.0', port=port, debug=True)
```

---

## Lỗi: Cannot connect to MySQL

### Nguyên nhân
- Security Group chưa cho phép EC2 truy cập RDS
- MySQL credentials sai
- RDS endpoint sai

### Giải pháp

#### 1. Kiểm tra Security Group

```bash
# Trong AWS Console:
# - Vào RDS → Security Groups
# - Thêm Inbound Rule: MySQL/Aurora (3306)
# - Source: EC2 Security Group hoặc IP của EC2
```

#### 2. Kiểm tra MySQL credentials

```bash
# Test kết nối từ EC2
mysql -h your-rds-endpoint.rds.amazonaws.com -u admin -p

# Nếu kết nối được, kiểm tra database
SHOW DATABASES;
USE plate_violation;
SHOW TABLES;
```

#### 3. Kiểm tra file .env

```bash
cat .env | grep MYSQL
```

Đảm bảo:
- `MYSQL_HOST` đúng RDS endpoint
- `MYSQL_USER` đúng username
- `MYSQL_PASSWORD` đúng password
- `MYSQL_DB` đúng database name

---

## Lỗi: Docker permission denied

### Giải pháp

```bash
# Thêm user vào docker group
sudo usermod -aG docker $USER

# Đăng xuất và đăng nhập lại
exit
# SSH lại vào EC2

# Hoặc dùng sudo
sudo docker ps
```

---

## Lỗi: ECR login failed

### Giải pháp

```bash
# Kiểm tra AWS credentials
aws sts get-caller-identity

# Nếu chưa có, cấu hình:
aws configure

# Đăng nhập ECR
aws ecr get-login-password --region ap-southeast-2 | docker login --username AWS --password-stdin 598250965573.dkr.ecr.ap-southeast-2.amazonaws.com
```

---

## Lỗi: Container không start

### Giải pháp

```bash
# Xem logs để biết lỗi
docker logs plate-violation-app

# Xem logs real-time
docker logs -f plate-violation-app

# Kiểm tra environment variables
docker exec plate-violation-app env

# Kiểm tra container status
docker ps -a
```

---

## Lỗi: Module not found

### Giải pháp

```bash
# Cài đặt lại dependencies
pip install -r requirements.txt

# Hoặc trong container
docker exec -it plate-violation-app pip install -r requirements.txt
```

---

## Lỗi: GPU not available

### Giải pháp

Nếu không có GPU, sử dụng Dockerfile.cpu:

```bash
# Build với CPU version
docker build -f Dockerfile.cpu -t plate_violation:latest .
```

Hoặc trong code, thêm fallback cho CPU.

---

## Lỗi: Out of memory

### Giải pháp

```bash
# Kiểm tra memory
free -h

# Xóa images/containers không dùng
docker system prune -a

# Tăng swap (nếu cần)
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
```

---

## Các lệnh hữu ích

```bash
# Xem tất cả containers
docker ps -a

# Xem logs
docker logs -f plate-violation-app

# Vào trong container
docker exec -it plate-violation-app bash

# Restart container
docker restart plate-violation-app

# Xem resource usage
docker stats plate-violation-app

# Xem port mapping
docker port plate-violation-app
```

---

## Liên hệ

Nếu vẫn gặp vấn đề, xem:
- `EC2_DEPLOY.md` - Hướng dẫn deploy EC2
- `AWS_DEPLOY_GUIDE.md` - Hướng dẫn AWS chi tiết
- `QUICK_DEPLOY.md` - Hướng dẫn deploy nhanh

