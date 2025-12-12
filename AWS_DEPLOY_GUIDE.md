# 🚀 Hướng dẫn Deploy lên AWS

## 📋 Yêu cầu

1. **AWS Account** - Đã đăng ký và có quyền truy cập
2. **AWS CLI** - Đã cài đặt và cấu hình (`aws configure`)
3. **Docker** - Đã cài đặt và hoạt động
4. **Docker Image** - Đã build thành công

## 🔧 Bước 1: Cài đặt và cấu hình AWS CLI

### Windows:
```powershell
# Tải và cài đặt AWS CLI
# https://aws.amazon.com/cli/

# Cấu hình credentials
aws configure
# Nhập:
# - AWS Access Key ID
# - AWS Secret Access Key
# - Default region: ap-southeast-1 (Singapore - gần Việt Nam)
# - Default output format: json
```

### Kiểm tra:
```powershell
aws --version
aws sts get-caller-identity
```

## 🐳 Bước 2: Build Docker Image

### Chạy build (khi Docker đã hoạt động):
```powershell
docker build -f Dockerfile.cpu -t plate-violation:latest .
```

**Lưu ý:** Build có thể mất 5-10 phút, cần kết nối internet ổn định.

## 📦 Bước 3: Push Image lên AWS ECR

### Option A: Dùng script tự động (Khuyến nghị)
```powershell
.\build-and-push-aws.ps1
```

### Option B: Chạy thủ công

#### 3.1. Tạo ECR Repository
```powershell
aws ecr create-repository --repository-name plate-violation-system --region ap-southeast-1
```

#### 3.2. Đăng nhập vào ECR
```powershell
# Lấy account ID
$accountId = aws sts get-caller-identity --query Account --output text

# Đăng nhập
aws ecr get-login-password --region ap-southeast-1 | docker login --username AWS --password-stdin $accountId.dkr.ecr.ap-southeast-1.amazonaws.com
```

#### 3.3. Tag và Push Image
```powershell
# Tag image
docker tag plate-violation:latest $accountId.dkr.ecr.ap-southeast-1.amazonaws.com/plate-violation-system:latest

# Push image
docker push $accountId.dkr.ecr.ap-southeast-1.amazonaws.com/plate-violation-system:latest
```

## 🖥️ Bước 4: Deploy lên EC2 (Khuyến nghị cho bắt đầu)

### 4.1. Launch EC2 Instance

1. Vào **EC2 Console** → **Launch Instance**
2. Chọn **Amazon Linux 2023** hoặc **Ubuntu 22.04**
3. Instance type: **t3.medium** trở lên (hoặc **g4dn.xlarge** nếu cần GPU)
4. Configure Security Group:
   - SSH (22) - từ IP của bạn
   - HTTP (80) - từ mọi nơi
   - Custom TCP (5000) - từ mọi nơi (cho Flask app)
5. Launch và tạo/tải key pair

### 4.2. SSH vào EC2 và cài đặt

```bash
# SSH vào EC2
ssh -i your-key.pem ec2-user@your-ec2-ip

# Cài đặt Docker
sudo yum update -y
sudo yum install docker -y
sudo systemctl start docker
sudo systemctl enable docker
sudo usermod -aG docker ec2-user

# Cài đặt Docker Compose (optional)
sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose

# Cài đặt AWS CLI
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
unzip awscliv2.zip
sudo ./aws/install

# Đăng nhập ECR
aws ecr get-login-password --region ap-southeast-1 | docker login --username AWS --password-stdin YOUR_ACCOUNT_ID.dkr.ecr.ap-southeast-1.amazonaws.com

# Pull và chạy container
docker pull YOUR_ACCOUNT_ID.dkr.ecr.ap-southeast-1.amazonaws.com/plate-violation-system:latest

# Tạo file .env
nano .env
# Điền thông tin MySQL, Telegram, etc.

# Chạy container
docker run -d \
  --name plate-violation-app \
  -p 5000:5000 \
  --env-file .env \
  YOUR_ACCOUNT_ID.dkr.ecr.ap-southeast-1.amazonaws.com/plate-violation-system:latest
```

### 4.3. Cài đặt MySQL trên EC2 (hoặc dùng RDS)

#### Option A: MySQL trên EC2
```bash
sudo yum install mysql-server -y
sudo systemctl start mysqld
sudo systemctl enable mysqld
sudo mysql_secure_installation

# Tạo database
mysql -u root -p
CREATE DATABASE plate_violation;
# ... tạo các bảng
```

#### Option B: RDS MySQL (Khuyến nghị)
1. Vào **RDS Console** → **Create Database**
2. Chọn **MySQL 8.0**
3. Template: **Free tier** hoặc **Production**
4. Configure:
   - DB instance identifier: `plate-violation-db`
   - Master username: `admin`
   - Master password: (tạo mật khẩu mạnh)
   - DB name: `plate_violation`
5. VPC: Chọn cùng VPC với EC2
6. Security Group: Cho phép EC2 security group truy cập port 3306

### 4.4. Cấu hình Nginx Reverse Proxy (Optional)

```bash
sudo yum install nginx -y

# Tạo config
sudo nano /etc/nginx/conf.d/plate-violation.conf
```

```nginx
server {
    listen 80;
    server_name your-domain.com;

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
sudo systemctl start nginx
sudo systemctl enable nginx
```

## ☁️ Bước 5: Deploy lên ECS (Advanced)

### 5.1. Tạo ECS Cluster
```powershell
aws ecs create-cluster --cluster-name plate-violation-cluster --region ap-southeast-1
```

### 5.2. Tạo Task Definition
Chỉnh sửa `task-definition.json` và chạy:
```powershell
aws ecs register-task-definition --cli-input-json file://task-definition.json --region ap-southeast-1
```

### 5.3. Tạo ECS Service
```powershell
aws ecs create-service \
  --cluster plate-violation-cluster \
  --service-name plate-violation-service \
  --task-definition plate-violation-task \
  --desired-count 1 \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[subnet-xxx],securityGroups=[sg-xxx],assignPublicIp=ENABLED}" \
  --region ap-southeast-1
```

## 🔐 Bước 6: Quản lý Secrets (Khuyến nghị)

### Tạo Secrets trong AWS Secrets Manager:
```powershell
# SECRET_KEY
aws secretsmanager create-secret \
  --name plate-violation/secret-key \
  --secret-string "your-secret-key-here" \
  --region ap-southeast-1

# TELEGRAM_TOKEN
aws secretsmanager create-secret \
  --name plate-violation/telegram-token \
  --secret-string "your-telegram-token" \
  --region ap-southeast-1
```

Sau đó cập nhật Task Definition để sử dụng secrets.

## 📊 Bước 7: Monitoring và Logs

### CloudWatch Logs
```powershell
# Tạo log group
aws logs create-log-group --log-group-name /ecs/plate-violation-task --region ap-southeast-1
```

### Xem logs
```powershell
# ECS logs
aws logs tail /ecs/plate-violation-task --follow --region ap-southeast-1

# EC2 logs (nếu dùng EC2)
docker logs -f plate-violation-app
```

## 🔄 Bước 8: Update và Redeploy

### Khi có code mới:
```powershell
# 1. Build lại image
docker build -f Dockerfile.cpu -t plate-violation:latest .

# 2. Push lên ECR
.\build-and-push-aws.ps1

# 3. Update ECS service (nếu dùng ECS)
aws ecs update-service --cluster plate-violation-cluster --service plate-violation-service --force-new-deployment --region ap-southeast-1

# 4. Hoặc pull và restart trên EC2
ssh ec2-user@your-ec2-ip
docker pull YOUR_ACCOUNT_ID.dkr.ecr.ap-southeast-1.amazonaws.com/plate-violation-system:latest
docker stop plate-violation-app
docker rm plate-violation-app
docker run -d --name plate-violation-app -p 5000:5000 --env-file .env YOUR_ACCOUNT_ID.dkr.ecr.ap-southeast-1.amazonaws.com/plate-violation-system:latest
```

## 💰 Ước tính chi phí

### EC2:
- **t3.medium**: ~$30/tháng
- **g4dn.xlarge** (GPU): ~$200/tháng

### RDS MySQL:
- **db.t3.micro** (Free tier): $0 (12 tháng đầu)
- **db.t3.small**: ~$15/tháng

### ECR:
- Storage: ~$0.10/GB/tháng
- Data transfer: ~$0.09/GB

### ECS Fargate:
- vCPU: ~$0.04/giờ
- Memory: ~$0.004/GB/giờ

## ✅ Checklist

- [ ] AWS CLI đã cài đặt và cấu hình
- [ ] Docker image đã build thành công
- [ ] ECR repository đã tạo
- [ ] Image đã push lên ECR
- [ ] EC2 instance hoặc ECS cluster đã tạo
- [ ] MySQL database đã setup (EC2 hoặc RDS)
- [ ] Security groups đã cấu hình đúng
- [ ] Environment variables đã được set
- [ ] Application đang chạy và accessible
- [ ] Logs đang được ghi vào CloudWatch

## 🆘 Troubleshooting

### Lỗi: Cannot connect to MySQL
- Kiểm tra Security Group cho phép EC2 truy cập RDS
- Kiểm tra MySQL user và password trong .env
- Kiểm tra MySQL đang chạy: `sudo systemctl status mysqld`

### Lỗi: ECR login failed
- Kiểm tra AWS credentials: `aws sts get-caller-identity`
- Kiểm tra IAM permissions cho ECR

### Lỗi: Container không start
- Xem logs: `docker logs plate-violation-app`
- Kiểm tra environment variables
- Kiểm tra port 5000 đã được expose

## 📞 Support

Xem thêm trong `README_AWS.md` hoặc tạo issue trên GitHub.

