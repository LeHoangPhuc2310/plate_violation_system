# 🚀 Hướng dẫn Deploy Nhanh lên AWS

## Bước 1: Chuẩn bị

### 1.1. Cài đặt các công cụ cần thiết

- **Docker Desktop**: https://www.docker.com/products/docker-desktop
- **AWS CLI**: https://aws.amazon.com/cli/
- **AWS Tools for PowerShell** (tùy chọn): `Install-Module -Name AWS.Tools.ECR`

### 1.2. Cấu hình AWS

```powershell
# Cấu hình AWS credentials
aws configure

# Nhập thông tin:
# - AWS Access Key ID
# - AWS Secret Access Key  
# - Default region: ap-southeast-2 (hoặc region của bạn)
# - Default output format: json

# Kiểm tra đăng nhập
aws sts get-caller-identity
```

## Bước 2: Build và Push Docker Image

### Cách 1: Dùng script tự động (Khuyến nghị)

```powershell
# Chạy script deploy
.\deploy-to-aws.ps1
```

Script này sẽ:
- ✅ Kiểm tra Docker và AWS CLI
- ✅ Kiểm tra AWS credentials
- ✅ Tạo ECR repository (nếu chưa có)
- ✅ Đăng nhập vào ECR
- ✅ Build Docker image từ `Dockerfile.cpu`
- ✅ Tag và push image lên ECR

### Cách 2: Chạy thủ công

```powershell
# 1. Đăng nhập ECR
aws ecr get-login-password --region ap-southeast-2 | docker login --username AWS --password-stdin 598250965573.dkr.ecr.ap-southeast-2.amazonaws.com

# Hoặc dùng AWS Tools for PowerShell:
(Get-ECRLoginCommand).Password | docker login --username AWS --password-stdin 598250965573.dkr.ecr.ap-southeast-2.amazonaws.com

# 2. Build image
docker build -f Dockerfile.cpu -t plate_violation:latest .

# 3. Tag image
docker tag plate_violation:latest 598250965573.dkr.ecr.ap-southeast-2.amazonaws.com/plate_violation:latest

# 4. Push image
docker push 598250965573.dkr.ecr.ap-southeast-2.amazonaws.com/plate_violation:latest
```

## Bước 3: Deploy lên EC2

### 3.1. Tạo EC2 Instance

1. Vào **AWS Console** → **EC2** → **Launch Instance**
2. Chọn **Ubuntu 22.04 LTS** hoặc **Amazon Linux 2023**
3. Instance type: **t3.medium** trở lên (hoặc **g4dn.xlarge** nếu cần GPU)
4. Storage: **20GB+**
5. Security Group:
   - SSH (22) - từ IP của bạn
   - HTTP (80) - từ mọi nơi (0.0.0.0/0)
   - Custom TCP (5000) - từ mọi nơi (cho Flask app)
6. Launch và tải key pair (.pem file)

### 3.2. SSH vào EC2 và Setup

```bash
# SSH vào EC2 (Windows PowerShell)
ssh -i your-key.pem ubuntu@your-ec2-ip

# Hoặc dùng PuTTY (Windows)
# Convert .pem sang .ppk bằng PuTTYgen
```

```bash
# Cài đặt Docker
sudo apt-get update
sudo apt-get install -y docker.io docker-compose
sudo systemctl start docker
sudo systemctl enable docker
sudo usermod -aG docker $USER

# Đăng xuất và đăng nhập lại để áp dụng group changes
exit
# SSH lại vào EC2

# Cài đặt AWS CLI
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
unzip awscliv2.zip
sudo ./aws/install

# Cấu hình AWS (hoặc dùng IAM role)
aws configure
```

### 3.3. Pull và Chạy Container

```bash
# Đăng nhập ECR
aws ecr get-login-password --region ap-southeast-2 | docker login --username AWS --password-stdin 598250965573.dkr.ecr.ap-southeast-2.amazonaws.com

# Pull image
docker pull 598250965573.dkr.ecr.ap-southeast-2.amazonaws.com/plate_violation:latest

# Tạo file .env
nano .env
```

Điền thông tin vào `.env`:
```bash
MYSQL_HOST=your-rds-endpoint.rds.amazonaws.com
MYSQL_USER=admin
MYSQL_PASSWORD=your-password
MYSQL_DB=plate_violation
SECRET_KEY=your-secret-key
TELEGRAM_TOKEN=your-telegram-token
TELEGRAM_CHAT_ID=your-chat-id
```

```bash
# Chạy container
docker run -d \
  --name plate-violation-app \
  -p 5000:5000 \
  --env-file .env \
  --restart unless-stopped \
  598250965573.dkr.ecr.ap-southeast-2.amazonaws.com/plate_violation:latest

# Kiểm tra logs
docker logs -f plate-violation-app

# Kiểm tra container đang chạy
docker ps
```

### 3.4. Truy cập ứng dụng

Mở trình duyệt và truy cập:
```
http://your-ec2-public-ip:5000
```

## Bước 4: Setup MySQL Database (RDS)

### 4.1. Tạo RDS MySQL Instance

1. Vào **AWS Console** → **RDS** → **Create Database**
2. Chọn **MySQL 8.0**
3. Template: **Free tier** (hoặc **Production**)
4. Settings:
   - DB instance identifier: `plate-violation-db`
   - Master username: `admin`
   - Master password: (tạo mật khẩu mạnh)
   - DB name: `plate_violation`
5. Instance configuration: **db.t3.micro** (Free tier) hoặc **db.t3.small**
6. Storage: **20GB**
7. Connectivity:
   - VPC: Chọn cùng VPC với EC2
   - Public access: **Yes** (hoặc No nếu dùng VPC)
   - Security group: Tạo mới hoặc chọn existing
8. Create database

### 4.2. Cấu hình Security Group

1. Vào **RDS Security Group** → **Inbound rules**
2. Thêm rule:
   - Type: **MySQL/Aurora**
   - Port: **3306**
   - Source: **EC2 Security Group** (hoặc IP của EC2)

### 4.3. Tạo Database Schema

```bash
# Kết nối MySQL từ EC2
mysql -h your-rds-endpoint.rds.amazonaws.com -u admin -p

# Tạo database (nếu chưa có)
CREATE DATABASE IF NOT EXISTS plate_violation;
USE plate_violation;

# Tạo các bảng (xem schema trong code hoặc migrations)
# ...
```

## Bước 5: Cấu hình Nginx (Tùy chọn)

```bash
# Cài đặt Nginx
sudo apt-get install -y nginx

# Tạo config
sudo nano /etc/nginx/sites-available/plate-violation
```

```nginx
server {
    listen 80;
    server_name your-domain.com;  # Hoặc EC2 IP

    location / {
        proxy_pass http://localhost:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

```bash
# Enable site
sudo ln -s /etc/nginx/sites-available/plate-violation /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

## Bước 6: Update và Redeploy

Khi có code mới:

```powershell
# Trên máy local (Windows)
.\deploy-to-aws.ps1
```

```bash
# Trên EC2
docker pull 598250965573.dkr.ecr.ap-southeast-2.amazonaws.com/plate_violation:latest
docker stop plate-violation-app
docker rm plate-violation-app
docker run -d --name plate-violation-app -p 5000:5000 --env-file .env --restart unless-stopped 598250965573.dkr.ecr.ap-southeast-2.amazonaws.com/plate_violation:latest
```

## Troubleshooting

### Lỗi: Cannot connect to MySQL
- Kiểm tra Security Group cho phép EC2 truy cập RDS port 3306
- Kiểm tra MySQL credentials trong `.env`
- Kiểm tra RDS endpoint đúng

### Lỗi: ECR login failed
- Kiểm tra AWS credentials: `aws sts get-caller-identity`
- Kiểm tra IAM permissions cho ECR
- Kiểm tra region đúng: `ap-southeast-2`

### Lỗi: Container không start
- Xem logs: `docker logs plate-violation-app`
- Kiểm tra environment variables trong `.env`
- Kiểm tra port 5000 đã được expose

### Lỗi: Permission denied khi chạy docker
```bash
sudo usermod -aG docker $USER
# Đăng xuất và đăng nhập lại
```

## Chi phí ước tính

- **EC2 t3.medium**: ~$30/tháng
- **RDS db.t3.micro** (Free tier): $0 (12 tháng đầu)
- **ECR Storage**: ~$0.10/GB/tháng
- **Data Transfer**: ~$0.09/GB

**Tổng**: ~$30-50/tháng (với Free tier RDS)

## Hỗ trợ

Xem thêm:
- `AWS_DEPLOY_GUIDE.md` - Hướng dẫn chi tiết
- `README_AWS.md` - Tài liệu AWS
- `DOCKER_GUIDE.md` - Hướng dẫn Docker

