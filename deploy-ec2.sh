#!/bin/bash
# Script để deploy container từ ECR lên EC2
# Chạy script này trên EC2 instance sau khi đã SSH vào

set -e

echo "🚀 Deploy Plate Violation System lên EC2"
echo "========================================"
echo ""

# Cấu hình
ACCOUNT_ID="598250965573"
REGION="ap-southeast-2"
REPO_NAME="plate_violation"
IMAGE_URI="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com/${REPO_NAME}:latest"
CONTAINER_NAME="plate-violation-app"

# Kiểm tra Docker
if ! command -v docker &> /dev/null; then
    echo "❌ Docker chưa được cài đặt!"
    echo "Cài đặt Docker:"
    echo "  sudo apt-get update"
    echo "  sudo apt-get install -y docker.io docker-compose"
    echo "  sudo systemctl start docker"
    echo "  sudo systemctl enable docker"
    echo "  sudo usermod -aG docker \$USER"
    exit 1
fi

echo "✅ Docker đã được cài đặt"
echo ""

# Kiểm tra AWS CLI
if ! command -v aws &> /dev/null; then
    echo "❌ AWS CLI chưa được cài đặt!"
    echo "Cài đặt AWS CLI:"
    echo "  curl \"https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip\" -o \"awscliv2.zip\""
    echo "  unzip awscliv2.zip"
    echo "  sudo ./aws/install"
    exit 1
fi

echo "✅ AWS CLI đã được cài đặt"
echo ""

# Đăng nhập ECR
echo "🔑 Đăng nhập vào ECR..."
aws ecr get-login-password --region $REGION | docker login --username AWS --password-stdin ${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com

if [ $? -ne 0 ]; then
    echo "❌ Không thể đăng nhập ECR!"
    echo "Kiểm tra AWS credentials: aws configure"
    exit 1
fi

echo "✅ Đã đăng nhập ECR thành công"
echo ""

# Dừng container cũ (nếu có)
if [ "$(docker ps -aq -f name=$CONTAINER_NAME)" ]; then
    echo "🛑 Dừng container cũ..."
    docker stop $CONTAINER_NAME 2>/dev/null || true
    docker rm $CONTAINER_NAME 2>/dev/null || true
    echo "✅ Đã dừng container cũ"
    echo ""
fi

# Pull image mới nhất
echo "📥 Đang pull image mới nhất từ ECR..."
docker pull $IMAGE_URI

if [ $? -ne 0 ]; then
    echo "❌ Không thể pull image!"
    exit 1
fi

echo "✅ Đã pull image thành công"
echo ""

# Kiểm tra file .env
if [ ! -f .env ]; then
    echo "⚠️  File .env không tồn tại!"
    echo "Tạo file .env với nội dung:"
    echo ""
    echo "MYSQL_HOST=your-rds-endpoint.rds.amazonaws.com"
    echo "MYSQL_USER=admin"
    echo "MYSQL_PASSWORD=your-password"
    echo "MYSQL_DB=plate_violation"
    echo "SECRET_KEY=your-secret-key"
    echo "TELEGRAM_TOKEN=your-telegram-token"
    echo "TELEGRAM_CHAT_ID=your-chat-id"
    echo ""
    echo "Sau đó chạy lại script này."
    exit 1
fi

echo "✅ File .env đã tồn tại"
echo ""

# Chạy container
echo "🚀 Đang khởi động container..."
docker run -d \
  --name $CONTAINER_NAME \
  -p 5000:5000 \
  --env-file .env \
  --restart unless-stopped \
  $IMAGE_URI

if [ $? -ne 0 ]; then
    echo "❌ Không thể khởi động container!"
    exit 1
fi

echo "✅ Container đã được khởi động"
echo ""

# Kiểm tra container
echo "📊 Kiểm tra container..."
sleep 3
docker ps -f name=$CONTAINER_NAME

echo ""
echo "========================================"
echo "✅ DEPLOY THÀNH CÔNG!"
echo "========================================"
echo ""
echo "📦 Container: $CONTAINER_NAME"
echo "🌐 Application: http://$(curl -s ifconfig.me):5000"
echo ""
echo "📝 Các lệnh hữu ích:"
echo "   Xem logs:        docker logs -f $CONTAINER_NAME"
echo "   Dừng container:  docker stop $CONTAINER_NAME"
echo "   Khởi động lại:   docker start $CONTAINER_NAME"
echo "   Xóa container:   docker rm -f $CONTAINER_NAME"
echo ""

