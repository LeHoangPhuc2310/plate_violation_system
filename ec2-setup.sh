#!/bin/bash
# Script setup tự động cho AWS EC2 instance

set -e

echo "🔧 Setting up AWS EC2 instance for Plate Violation System..."

# Update system
sudo apt-get update
sudo apt-get upgrade -y

# Install basic dependencies
sudo apt-get install -y \
    python3.10 \
    python3-pip \
    python3-dev \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    libmysqlclient-dev \
    pkg-config \
    nginx \
    git

# Install Python packages
pip3 install --upgrade pip
pip3 install -r requirements.txt

# Create systemd service
sudo tee /etc/systemd/system/plate-violation.service > /dev/null <<EOF
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
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# Setup Nginx
sudo tee /etc/nginx/sites-available/plate-violation > /dev/null <<EOF
server {
    listen 80;
    server_name _;

    client_max_body_size 500M;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 300s;
        proxy_connect_timeout 75s;
    }

    location /static {
        alias /home/ubuntu/plate_violation_system/static;
        expires 30d;
        add_header Cache-Control "public, immutable";
    }
}
EOF

# Enable Nginx site
sudo ln -sf /etc/nginx/sites-available/plate-violation /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl restart nginx

echo "✅ Setup completed!"
echo "📝 Next steps:"
echo "1. Create .env file with your configuration"
echo "2. Enable service: sudo systemctl enable plate-violation"
echo "3. Start service: sudo systemctl start plate-violation"
echo "4. Check status: sudo systemctl status plate-violation"

