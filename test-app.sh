#!/bin/bash
# Script test app đang chạy

echo "Testing Flask app..."

# Test health endpoint
echo ""
echo "1. Testing /health endpoint:"
curl -s http://localhost:5000/health || echo "Failed to connect"

echo ""
echo ""
echo "2. Testing / endpoint:"
curl -s -I http://localhost:5000/ | head -1 || echo "Failed to connect"

echo ""
echo ""
echo "3. Checking if port 5000 is listening:"
netstat -tuln | grep :5000 || ss -tuln | grep :5000

echo ""
echo ""
echo "4. Checking Flask process:"
ps aux | grep "python3 app.py" | grep -v grep

