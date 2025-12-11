# Hướng dẫn Deploy lên AWS

## Tổng quan

Hệ thống nhận diện biển số và tính toán tốc độ có thể được deploy lên AWS bằng nhiều cách:
1. **AWS EC2** - Máy ảo với GPU (khuyến nghị cho AI/ML)
2. **AWS ECS/Fargate** - Container service
3. **AWS Elastic Beanstalk** - Platform as a Service

## Yêu cầu

- AWS Account
- GPU instance (g3.4xlarge hoặc lớn hơn) cho YOLO và AI models
- RDS MySQL database
- S3 bucket (tùy chọn, cho file storage)

## Bước 1: Chuẩn bị Database (RDS MySQL)

1. Tạo RDS MySQL instance:
   - Vào AWS Console → RDS → Create database
   - Chọn MySQL 8.0
   - Instance class: db.t3.medium (hoặc lớn hơn)
   - Storage: 20GB+
   - Public access: Yes (hoặc dùng VPC)
   - Security group: Mở port 3306

2. Tạo database và user:
```sql
CREATE DATABASE plate_violation;
CREATE USER 'admin'@'%' IDENTIFIED BY 'your-password';
GRANT ALL PRIVILEGES ON plate_violation.* TO 'admin'@'%';
FLUSH PRIVILEGES;
```

3. Import schema (nếu có file SQL)

## Bước 2: Deploy trên EC2 (Khuyến nghị)

### 2.1. Launch EC2 Instance

1. Chọn AMI: **Deep Learning AMI (Ubuntu)** hoặc **Ubuntu 22.04**
2. Instance type: **g4dn.xlarge** hoặc **g3.4xlarge** (có GPU)
3. Storage: 50GB+ (SSD)
4. Security Group: Mở ports 22 (SSH), 5000 (Flask), 80, 443 (HTTP/HTTPS)

### 2.2. Setup trên EC2

```bash
# SSH vào instance
ssh -i your-key.pem ubuntu@your-ec2-ip

# Update system
sudo apt-get update
sudo apt-get upgrade -y

# Install CUDA và cuDNN (nếu chưa có)
# Deep Learning AMI đã có sẵn

# Install Python dependencies
sudo apt-get install -y python3-pip python3-dev libmysqlclient-dev

# Clone repository
git clone your-repo-url
cd plate_violation_system

# Install Python packages
pip3 install -r requirements.txt

# Tạo file .env
nano .env
# Copy nội dung từ .env.example và điền thông tin

# Download YOLO models (nếu chưa có)
# Models sẽ tự động download khi chạy lần đầu
```

### 2.3. Chạy với systemd (Production)

Tạo file `/etc/systemd/system/plate-violation.service`:

```ini
[Unit]
Description=Plate Violation System
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/plate_violation_system
Environment="PATH=/home/ubuntu/.local/bin:/usr/local/bin:/usr/bin:/bin"
EnvironmentFile=/home/ubuntu/plate_violation_system/.env
ExecStart=/usr/bin/python3 /home/ubuntu/plate_violation_system/app.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
# Enable và start service
sudo systemctl daemon-reload
sudo systemctl enable plate-violation
sudo systemctl start plate-violation
sudo systemctl status plate-violation
```

### 2.4. Setup Nginx (Reverse Proxy)

```bash
sudo apt-get install -y nginx

# Tạo config
sudo nano /etc/nginx/sites-available/plate-violation
```

Nội dung config:

```nginx
server {
    listen 80;
    server_name your-domain.com;

    client_max_body_size 500M;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;
        proxy_connect_timeout 75s;
    }

    location /static {
        alias /home/ubuntu/plate_violation_system/static;
        expires 30d;
        add_header Cache-Control "public, immutable";
    }
}
```

```bash
# Enable site
sudo ln -s /etc/nginx/sites-available/plate-violation /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

## Bước 3: Deploy với Docker (ECS/Fargate)

### 3.1. Build Docker Image

```bash
# Build image
docker build -t plate-violation-system .

# Test locally
docker run -p 5000:5000 --env-file .env plate-violation-system
```

### 3.2. Push lên ECR

```bash
# Login to ECR
aws ecr get-login-password --region ap-southeast-1 | docker login --username AWS --password-stdin your-account-id.dkr.ecr.ap-southeast-1.amazonaws.com

# Create repository
aws ecr create-repository --repository-name plate-violation-system --region ap-southeast-1

# Tag và push
docker tag plate-violation-system:latest your-account-id.dkr.ecr.ap-southeast-1.amazonaws.com/plate-violation-system:latest
docker push your-account-id.dkr.ecr.ap-southeast-1.amazonaws.com/plate-violation-system:latest
```

### 3.3. Tạo ECS Task Definition

1. Vào ECS Console → Task Definitions → Create new
2. Chọn Fargate (hoặc EC2 nếu có GPU)
3. CPU: 4 vCPU, Memory: 8GB (hoặc 16GB cho GPU)
4. Container: Sử dụng image từ ECR
5. Environment variables: Thêm từ .env
6. Port mapping: 5000

### 3.4. Tạo ECS Service

1. Tạo Cluster
2. Tạo Service với Task Definition vừa tạo
3. Load Balancer: Application Load Balancer
4. Health check: `/` endpoint

## Bước 4: Cấu hình Security

1. **Security Groups**:
   - RDS: Chỉ cho phép từ EC2/ECS security group
   - EC2/ECS: Mở port 5000, 80, 443

2. **IAM Roles**:
   - EC2: Role với quyền truy cập RDS, S3 (nếu dùng)

3. **SSL/TLS**:
   - Dùng AWS Certificate Manager (ACM)
   - Setup HTTPS với Nginx hoặc ALB

## Bước 5: Monitoring và Logging

1. **CloudWatch**:
   - Logs: `/var/log/plate-violation/`
   - Metrics: CPU, Memory, GPU utilization

2. **Alarms**:
   - CPU > 80%
   - Memory > 90%
   - Application errors

## Troubleshooting

### Lỗi GPU không detect:
```bash
# Kiểm tra CUDA
nvidia-smi

# Kiểm tra PyTorch
python3 -c "import torch; print(torch.cuda.is_available())"
```

### Lỗi kết nối Database:
- Kiểm tra Security Group
- Kiểm tra RDS endpoint
- Kiểm tra credentials trong .env

### Lỗi Out of Memory:
- Tăng instance size
- Giảm DETECTION_SCALE trong code
- Giảm batch size

## Cost Optimization

1. **Reserved Instances**: Giảm 30-50% cost
2. **Spot Instances**: Cho development/testing
3. **Auto Scaling**: Scale down khi không dùng
4. **S3 Lifecycle**: Archive old files

## Backup

1. **Database**: RDS automated backups
2. **Files**: Backup static/uploads, static/plate_images
3. **Models**: Backup yolo11n.pt, models/

## Liên hệ

Nếu có vấn đề, kiểm tra logs:
```bash
sudo journalctl -u plate-violation -f
# hoặc
docker logs container-name
```

