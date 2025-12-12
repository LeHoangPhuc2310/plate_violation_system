#!/bin/bash
# Script lấy thông tin Public IP và test kết nối

echo "=========================================="
echo "EC2 Instance Information"
echo "=========================================="

# Lấy Public IP
PUBLIC_IP=$(curl -s http://169.254.169.254/latest/meta-data/public-ipv4)
PRIVATE_IP=$(curl -s http://169.254.169.254/latest/meta-data/local-ipv4)
INSTANCE_ID=$(curl -s http://169.254.169.254/latest/meta-data/instance-id)

echo "Instance ID: $INSTANCE_ID"
echo "Public IP: $PUBLIC_IP"
echo "Private IP: $PRIVATE_IP"
echo ""

echo "=========================================="
echo "Application URLs"
echo "=========================================="
echo "Test endpoint: http://$PUBLIC_IP:5000/test"
echo "Health check: http://$PUBLIC_IP:5000/health"
echo "Home page: http://$PUBLIC_IP:5000"
echo ""

echo "=========================================="
echo "Testing local connection"
echo "=========================================="
echo "Testing /test endpoint..."
curl -s http://localhost:5000/test | head -1
echo ""
echo "Testing /health endpoint..."
curl -s http://localhost:5000/health
echo ""

echo "=========================================="
echo "Next Steps"
echo "=========================================="
echo "1. Open browser on your computer"
echo "2. Go to: http://$PUBLIC_IP:5000/test"
echo "3. If it doesn't work, check:"
echo "   - Security Group allows port 5000 from your IP"
echo "   - App is running: python3 app.py"
echo "   - Firewall on EC2 (if any)"

