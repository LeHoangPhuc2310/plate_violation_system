# 🚀 Hướng dẫn Deploy trên EC2 (Infrastructure có sẵn)

## Bước 1: Clone repository trên EC2

```bash
# SSH vào EC2
ssh -i your-key.pem ubuntu@your-ec2-ip

# Clone repository
git clone https://github.com/LeHoangPhuc2310/plate_violation_system.git
cd plate_violation_system
```

## Bước 2: Cấu hình

### Tạo file cấu hình từ template:

```bash
# Tạo file aws-config.json (nếu cần deploy mới)
cp aws-config.json.example aws-config.json
nano aws-config.json

# Tạo file existing-infra-config.json (nếu dùng EC2/RDS có sẵn)
cp existing-infra-config.json.example existing-infra-config.json
nano existing-infra-config.json

# Tạo file .env
cp env.template .env
nano .env
```

### Điền thông tin vào `.env`:

```bash
MYSQL_HOST=your-rds-endpoint.rds.amazonaws.com
MYSQL_USER=admin
MYSQL_PASSWORD=your-password
MYSQL_DB=plate_violation
SECRET_KEY=your-secret-key
TELEGRAM_TOKEN=your-telegram-bot-token
TELEGRAM_CHAT_ID=your-telegram-chat-id
```

## Bước 3: Deploy

### Option 1: Deploy tự động (Khuyến nghị)

```bash
# Chạy script deploy tự động
chmod +x deploy-ec2.sh
./deploy-ec2.sh
```

Script này sẽ:
- ✅ Cài đặt Docker và AWS CLI
- ✅ Đăng nhập vào ECR
- ✅ Pull Docker image từ ECR
- ✅ Tạo file .env
- ✅ Chạy container

### Option 2: Deploy thủ công

```bash
# Cài đặt Docker
sudo apt-get update
sudo apt-get install -y docker.io docker-compose
sudo systemctl start docker
sudo systemctl enable docker
sudo usermod -aG docker $USER

# Đăng xuất và đăng nhập lại
exit
# SSH lại vào EC2

# Cài đặt AWS CLI
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
unzip awscliv2.zip
sudo ./aws/install

# Đăng nhập ECR
aws ecr get-login-password --region ap-southeast-2 | docker login --username AWS --password-stdin 598250965573.dkr.ecr.ap-southeast-2.amazonaws.com

# Pull image
docker pull 598250965573.dkr.ecr.ap-southeast-2.amazonaws.com/plate_violation:latest

# Tạo file .env (nếu chưa có)
nano .env

# Chạy container
docker run -d \
  --name plate-violation-app \
  -p 5000:5000 \
  --env-file .env \
  --restart unless-stopped \
  598250965573.dkr.ecr.ap-southeast-2.amazonaws.com/plate_violation:latest
```

## Bước 4: Kiểm tra

```bash
# Xem logs
docker logs -f plate-violation-app

# Kiểm tra container đang chạy
docker ps

# Kiểm tra ứng dụng
curl http://localhost:5000
```

## Truy cập ứng dụng

Mở trình duyệt:
```
http://your-ec2-public-ip:5000
```

## Các lệnh hữu ích

```bash
# Xem logs
docker logs -f plate-violation-app

# Dừng container
docker stop plate-violation-app

# Khởi động lại
docker start plate-violation-app

# Restart
docker restart plate-violation-app

# Xóa container
docker rm -f plate-violation-app

# Xem stats
docker stats plate-violation-app
```

## Update code mới

```bash
# Pull code mới từ GitHub
git pull origin main

# Rebuild và restart container (nếu có thay đổi code)
docker stop plate-violation-app
docker rm plate-violation-app

# Pull image mới từ ECR (nếu đã push image mới)
docker pull 598250965573.dkr.ecr.ap-southeast-2.amazonaws.com/plate_violation:latest

# Chạy lại container
docker run -d \
  --name plate-violation-app \
  -p 5000:5000 \
  --env-file .env \
  --restart unless-stopped \
  598250965573.dkr.ecr.ap-southeast-2.amazonaws.com/plate_violation:latest
```

## Troubleshooting

### Lỗi: Cannot connect to MySQL
- Kiểm tra Security Group cho phép EC2 truy cập RDS port 3306
- Kiểm tra MySQL credentials trong `.env`
- Kiểm tra RDS endpoint đúng

### Lỗi: Permission denied khi chạy docker
```bash
sudo usermod -aG docker $USER
# Đăng xuất và đăng nhập lại
```

### Lỗi: Container không start
```bash
# Xem logs để biết lỗi
docker logs plate-violation-app

# Kiểm tra environment variables
docker exec plate-violation-app env
```

## Tài liệu tham khảo

- `QUICK_DEPLOY.md` - Hướng dẫn deploy nhanh
- `AWS_DEPLOY_GUIDE.md` - Hướng dẫn chi tiết AWS
- `DEPLOY_STATUS.md` - Trạng thái deploy

