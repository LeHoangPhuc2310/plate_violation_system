# 🚀 Hướng Dẫn Deploy Lên GitHub và AWS Cloud

## 📋 Mục lục
1. [Push lên GitHub](#1-push-lên-github)
2. [Deploy lên AWS EC2](#2-deploy-lên-aws-ec2)
3. [Cấu hình Domain và SSL](#3-cấu-hình-domain-và-ssl)

---

## 1. Push lên GitHub

### Bước 1: Kiểm tra Git status

```bash
git status
```

### Bước 2: Add tất cả files

```bash
git add .
```

### Bước 3: Commit changes

```bash
git commit -m "feat: Add 6-thread architecture, Docker support, and professional UI"
```

### Bước 4: Push lên GitHub

```bash
git push origin main
```

Hoặc nếu branch là `master`:

```bash
git push origin master
```

### Bước 5: Verify trên GitHub

Truy cập: https://github.com/LeHoangPhuc2310/plate_violation_system

---

## 2. Deploy lên AWS EC2

### Bước 1: Launch EC2 Instance

1. Đăng nhập AWS Console
2. Chọn **EC2** → **Launch Instance**
3. Cấu hình:
   - **Name:** plate-violation-system
   - **AMI:** Ubuntu Server 22.04 LTS
   - **Instance Type:** t3.medium (2 vCPU, 4GB RAM)
   - **Key Pair:** Tạo mới hoặc chọn existing
   - **Security Group:**
     - SSH (22) - Your IP
     - HTTP (80) - 0.0.0.0/0
     - HTTPS (443) - 0.0.0.0/0
     - Custom TCP (5000) - 0.0.0.0/0

### Bước 2: Connect to EC2

```bash
ssh -i your-key.pem ubuntu@your-ec2-public-ip
```

### Bước 3: Install Docker

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# Install Docker Compose
sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose

# Add user to docker group
sudo usermod -aG docker $USER
newgrp docker

# Verify installation
docker --version
docker-compose --version
```

### Bước 4: Clone Repository

```bash
git clone https://github.com/LeHoangPhuc2310/plate_violation_system.git
cd plate_violation_system
```

### Bước 5: Configure Environment

```bash
# Copy environment template
cp env.template .env

# Edit environment variables
nano .env
```

Cập nhật các biến:
```env
DB_HOST=mysql
DB_USER=admin
DB_PASSWORD=your_secure_password
DB_NAME=plate_violation
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
```

### Bước 6: Deploy with Docker Compose

```bash
# Build and start services
docker-compose up -d

# View logs
docker-compose logs -f app

# Check status
docker-compose ps
```

### Bước 7: Access Application

Truy cập: **http://your-ec2-public-ip:5000**

---

## 3. Cấu hình Domain và SSL

### Bước 1: Point Domain to EC2

1. Mua domain (Namecheap, GoDaddy, etc.)
2. Tạo A Record:
   - **Type:** A
   - **Name:** @ (hoặc subdomain)
   - **Value:** EC2 Public IP
   - **TTL:** 300

### Bước 2: Install Nginx

```bash
sudo apt install nginx -y
```

### Bước 3: Configure Nginx

```bash
sudo nano /etc/nginx/sites-available/plate-violation
```

Thêm cấu hình:

```nginx
server {
    listen 80;
    server_name your-domain.com www.your-domain.com;

    location / {
        proxy_pass http://localhost:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Enable site:

```bash
sudo ln -s /etc/nginx/sites-available/plate-violation /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

### Bước 4: Install SSL with Let's Encrypt

```bash
# Install Certbot
sudo apt install certbot python3-certbot-nginx -y

# Get SSL certificate
sudo certbot --nginx -d your-domain.com -d www.your-domain.com

# Auto-renewal
sudo certbot renew --dry-run
```

### Bước 5: Access with HTTPS

Truy cập: **https://your-domain.com**

---

## 🔧 Troubleshooting

### Docker container không start

```bash
# Check logs
docker-compose logs app

# Restart services
docker-compose restart

# Rebuild
docker-compose down
docker-compose up -d --build
```

### Port 5000 đã được sử dụng

```bash
# Find process using port 5000
sudo lsof -i :5000

# Kill process
sudo kill -9 <PID>
```

### MySQL connection error

```bash
# Check MySQL container
docker-compose logs mysql

# Restart MySQL
docker-compose restart mysql
```

---

## 📊 Monitoring

### View logs

```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f app
docker-compose logs -f mysql
```

### Check resource usage

```bash
# Docker stats
docker stats

# System resources
htop
```

---

## 🛑 Stop Services

```bash
# Stop all services
docker-compose down

# Stop and remove volumes
docker-compose down -v
```

---

## 📞 Support

Nếu gặp vấn đề, liên hệ:
- Email: lehoangphuc2310@gmail.com
- GitHub Issues: https://github.com/LeHoangPhuc2310/plate_violation_system/issues

