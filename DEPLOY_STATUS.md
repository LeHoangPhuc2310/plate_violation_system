# ✅ Trạng thái Deploy lên AWS

## 🎉 Đã hoàn thành

### ✅ Bước 1: Build và Push Docker Image lên ECR

- ✅ **Docker image đã được build thành công**
  - Image: `plate_violation:latest`
  - Dockerfile: `Dockerfile.cpu`
  - Build time: ~3 phút

- ✅ **Image đã được push lên AWS ECR**
  - Repository: `598250965573.dkr.ecr.ap-southeast-2.amazonaws.com/plate_violation`
  - Tag: `latest`
  - Region: `ap-southeast-2` (Sydney)

### 📦 Image URI
```
598250965573.dkr.ecr.ap-southeast-2.amazonaws.com/plate_violation:latest
```

### 🔗 ECR Console
https://console.aws.amazon.com/ecr/repositories/private/ap-southeast-2/plate_violation

---

## 📋 Bước tiếp theo: Deploy lên EC2

### Option 1: Deploy thủ công trên EC2

#### 1. Tạo EC2 Instance

1. Vào **AWS Console** → **EC2** → **Launch Instance**
2. Chọn **Ubuntu 22.04 LTS** hoặc **Amazon Linux 2023**
3. Instance type: **t3.medium** trở lên
4. Storage: **20GB+**
5. Security Group:
   - **SSH (22)** - từ IP của bạn
   - **HTTP (80)** - từ mọi nơi (0.0.0.0/0)
   - **Custom TCP (5000)** - từ mọi nơi (cho Flask app)
6. Launch và tải key pair (.pem file)

#### 2. SSH vào EC2

```bash
# Windows PowerShell
ssh -i your-key.pem ubuntu@your-ec2-ip
```

#### 3. Cài đặt Docker và AWS CLI

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

# Cấu hình AWS (hoặc dùng IAM role)
aws configure
```

#### 4. Deploy Container

```bash
# Copy script deploy-ec2.sh lên EC2 (hoặc tạo mới)
nano deploy-ec2.sh
# Paste nội dung từ file deploy-ec2.sh

chmod +x deploy-ec2.sh

# Tạo file .env
nano .env
```

Điền thông tin vào `.env`:
```bash
MYSQL_HOST=your-rds-endpoint.rds.amazonaws.com
MYSQL_USER=admin
MYSQL_PASSWORD=your-password
MYSQL_DB=plate_violation
SECRET_KEY=your-secret-key-here
TELEGRAM_TOKEN=your-telegram-bot-token
TELEGRAM_CHAT_ID=your-telegram-chat-id
```

```bash
# Chạy script deploy
./deploy-ec2.sh
```

#### 5. Truy cập ứng dụng

Mở trình duyệt:
```
http://your-ec2-public-ip:5000
```

---

### Option 2: Deploy lên ECS Fargate

Xem hướng dẫn trong `AWS_DEPLOY_GUIDE.md` phần "Bước 5: Deploy lên ECS"

---

## 🗄️ Setup MySQL Database (RDS)

### Tạo RDS MySQL Instance

1. Vào **AWS Console** → **RDS** → **Create Database**
2. Chọn **MySQL 8.0**
3. Template: **Free tier** (hoặc **Production**)
4. Settings:
   - DB instance identifier: `plate-violation-db`
   - Master username: `admin`
   - Master password: (tạo mật khẩu mạnh)
   - DB name: `plate_violation`
5. Instance configuration: **db.t3.micro** (Free tier)
6. Storage: **20GB**
7. Connectivity:
   - VPC: Chọn cùng VPC với EC2
   - Public access: **Yes** (hoặc No nếu dùng VPC)
   - Security group: Tạo mới
8. Create database

### Cấu hình Security Group

1. Vào **RDS Security Group** → **Inbound rules**
2. Thêm rule:
   - Type: **MySQL/Aurora**
   - Port: **3306**
   - Source: **EC2 Security Group** (hoặc IP của EC2)

### Tạo Database Schema

```bash
# Kết nối MySQL từ EC2
mysql -h your-rds-endpoint.rds.amazonaws.com -u admin -p

# Tạo database
CREATE DATABASE IF NOT EXISTS plate_violation;
USE plate_violation;

# Tạo các bảng (xem schema trong code)
```

---

## 🔄 Update và Redeploy

Khi có code mới:

### Trên máy local (Windows):
```powershell
# Build và push lại
.\deploy-to-aws.ps1
```

### Trên EC2:
```bash
# Pull image mới và restart container
./deploy-ec2.sh
```

Hoặc thủ công:
```bash
docker pull 598250965573.dkr.ecr.ap-southeast-2.amazonaws.com/plate_violation:latest
docker stop plate-violation-app
docker rm plate-violation-app
docker run -d --name plate-violation-app -p 5000:5000 --env-file .env --restart unless-stopped 598250965573.dkr.ecr.ap-southeast-2.amazonaws.com/plate_violation:latest
```

---

## 📊 Monitoring

### Xem logs container:
```bash
docker logs -f plate-violation-app
```

### Kiểm tra container status:
```bash
docker ps
docker stats plate-violation-app
```

---

## 💰 Chi phí ước tính

- **EC2 t3.medium**: ~$30/tháng
- **RDS db.t3.micro** (Free tier): $0 (12 tháng đầu)
- **ECR Storage**: ~$0.10/GB/tháng
- **Data Transfer**: ~$0.09/GB

**Tổng**: ~$30-50/tháng (với Free tier RDS)

---

## 🆘 Troubleshooting

### Lỗi: Cannot connect to MySQL
- Kiểm tra Security Group cho phép EC2 truy cập RDS port 3306
- Kiểm tra MySQL credentials trong `.env`
- Kiểm tra RDS endpoint đúng

### Lỗi: Container không start
- Xem logs: `docker logs plate-violation-app`
- Kiểm tra environment variables trong `.env`
- Kiểm tra port 5000 đã được expose

### Lỗi: Permission denied khi chạy docker
```bash
sudo usermod -aG docker $USER
# Đăng xuất và đăng nhập lại
```

---

## 📚 Tài liệu tham khảo

- `QUICK_DEPLOY.md` - Hướng dẫn deploy nhanh
- `AWS_DEPLOY_GUIDE.md` - Hướng dẫn chi tiết
- `README_AWS.md` - Tài liệu AWS

