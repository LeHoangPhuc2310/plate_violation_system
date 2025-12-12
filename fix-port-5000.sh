#!/bin/bash
# Script để fix lỗi port 5000 đang được sử dụng

echo "Checking what's using port 5000..."

# Kiểm tra process đang dùng port 5000
PID=$(lsof -ti:5000 2>/dev/null || netstat -tulpn 2>/dev/null | grep :5000 | awk '{print $7}' | cut -d'/' -f1 | head -1)

if [ -z "$PID" ]; then
    # Thử cách khác
    PID=$(fuser 5000/tcp 2>/dev/null | awk '{print $1}')
fi

if [ -n "$PID" ]; then
    echo "Found process using port 5000: PID $PID"
    ps aux | grep $PID | grep -v grep
    echo ""
    read -p "Do you want to kill this process? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        kill -9 $PID
        echo "Process killed"
        sleep 2
    fi
else
    echo "No process found using port 5000 directly"
fi

# Kiểm tra Docker container
echo ""
echo "Checking Docker containers..."
if command -v docker &> /dev/null; then
    CONTAINER=$(docker ps -q --filter "publish=5000")
    if [ -n "$CONTAINER" ]; then
        echo "Found Docker container using port 5000:"
        docker ps --filter "publish=5000"
        echo ""
        read -p "Do you want to stop this container? (y/n) " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            docker stop $CONTAINER
            echo "Container stopped"
        fi
    else
        echo "No Docker container using port 5000"
    fi
fi

# Kiểm tra lại
echo ""
echo "Checking port 5000 again..."
if lsof -ti:5000 >/dev/null 2>&1 || netstat -tulpn 2>/dev/null | grep -q :5000; then
    echo "⚠️  Port 5000 is still in use"
    echo "Try:"
    echo "  sudo lsof -i :5000"
    echo "  sudo kill -9 <PID>"
else
    echo "✅ Port 5000 is now free"
    echo "You can now run: python3 app.py"
fi

