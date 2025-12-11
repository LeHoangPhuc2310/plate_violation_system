#!/bin/bash
# Script deploy tự động lên AWS EC2

set -e

echo "🚀 Bắt đầu deploy lên AWS EC2..."

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Check .env file
if [ ! -f .env ]; then
    echo -e "${RED}❌ File .env không tồn tại!${NC}"
    echo "Tạo file .env từ .env.example và điền thông tin:"
    echo "cp .env.example .env"
    exit 1
fi

# Load environment variables
export $(cat .env | grep -v '^#' | xargs)

# Check required variables
if [ -z "$MYSQL_HOST" ] || [ -z "$MYSQL_USER" ] || [ -z "$MYSQL_PASSWORD" ]; then
    echo -e "${RED}❌ Thiếu thông tin database trong .env!${NC}"
    exit 1
fi

echo -e "${GREEN}✅ Environment variables loaded${NC}"

# Install dependencies
echo -e "${YELLOW}📦 Installing dependencies...${NC}"
pip3 install -r requirements.txt

# Create directories
echo -e "${YELLOW}📁 Creating directories...${NC}"
mkdir -p static/uploads static/plate_images static/violation_videos uploads

# Test database connection
echo -e "${YELLOW}🔌 Testing database connection...${NC}"
python3 -c "
import os
from flask import Flask
from flask_mysqldb import MySQL

app = Flask(__name__)
app.config['MYSQL_HOST'] = os.getenv('MYSQL_HOST')
app.config['MYSQL_USER'] = os.getenv('MYSQL_USER')
app.config['MYSQL_PASSWORD'] = os.getenv('MYSQL_PASSWORD')
app.config['MYSQL_DB'] = os.getenv('MYSQL_DB')

mysql = MySQL(app)

try:
    with app.app_context():
        conn = mysql.connection
        if conn:
            print('✅ Database connection successful!')
        else:
            print('❌ Database connection failed!')
            exit(1)
except Exception as e:
    print(f'❌ Database error: {e}')
    exit(1)
"

if [ $? -ne 0 ]; then
    echo -e "${RED}❌ Database connection failed!${NC}"
    exit 1
fi

# Restart service (if using systemd)
if systemctl is-active --quiet plate-violation; then
    echo -e "${YELLOW}🔄 Restarting service...${NC}"
    sudo systemctl restart plate-violation
    echo -e "${GREEN}✅ Service restarted${NC}"
else
    echo -e "${YELLOW}⚠️  Service not running. Start manually:${NC}"
    echo "sudo systemctl start plate-violation"
fi

echo -e "${GREEN}✅ Deploy completed successfully!${NC}"
echo -e "${GREEN}🌐 Application should be running on http://$(hostname -I | awk '{print $1}'):5000${NC}"

