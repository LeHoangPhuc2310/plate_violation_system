#!/bin/bash

# ====================================================================
# DEPLOY SCRIPT - PLATE VIOLATION SYSTEM TO AWS EC2
# ====================================================================

# EC2 Configuration
EC2_IP="13.236.147.147"
EC2_USER="ec2-user"  # hoặc ssm-user tùy AMI
KEY_FILE="your-key.pem"  # Thay bằng path tới key file của bạn
REMOTE_DIR="/home/ec2-user/plate_project"

echo "🚀 Deploying Plate Violation System to EC2..."

# ====================================================================
# STEP 1: Upload code to EC2
# ====================================================================
echo ""
echo "📦 Step 1: Uploading code to EC2..."

# Tạo thư mục trên EC2
ssh -i "$KEY_FILE" "$EC2_USER@$EC2_IP" "mkdir -p $REMOTE_DIR"

# Upload files (exclude unnecessary files)
rsync -avz --progress \
  --exclude '.git' \
  --exclude '__pycache__' \
  --exclude '*.pyc' \
  --exclude 'venv' \
  --exclude 'plate_env' \
  --exclude 'models' \
  --exclude 'static/uploads/*' \
  --exclude 'static/violation_videos/*' \
  --exclude 'violations/*' \
  --exclude '.vscode' \
  --exclude '.claude' \
  --exclude 'node_modules' \
  -e "ssh -i $KEY_FILE" \
  ./ "$EC2_USER@$EC2_IP:$REMOTE_DIR/"

echo "✅ Code uploaded successfully!"

# ====================================================================
# STEP 2: Install dependencies
# ====================================================================
echo ""
echo "📚 Step 2: Installing Python dependencies..."

ssh -i "$KEY_FILE" "$EC2_USER@$EC2_IP" << 'ENDSSH'
cd /home/ec2-user/plate_project

# Check Python version
python3 --version

# Install pip if not exists
if ! command -v pip3 &> /dev/null; then
    echo "Installing pip..."
    sudo yum install python3-pip -y
fi

# Install dependencies
pip3 install --user -r requirements.txt

echo "✅ Dependencies installed!"
ENDSSH

# ====================================================================
# STEP 3: Setup environment
# ====================================================================
echo ""
echo "🔧 Step 3: Setting up environment..."

ssh -i "$KEY_FILE" "$EC2_USER@$EC2_IP" << 'ENDSSH'
cd /home/ec2-user/plate_project

# Create .env if not exists
if [ ! -f .env ]; then
    cat > .env << 'EOF'
# Database Configuration
MYSQL_HOST=database-1.c5s02mk0i88r.ap-southeast-2.rds.amazonaws.com
MYSQL_USER=plate_user
MYSQL_PASSWORD=094841175saZ?
MYSQL_DB=plate_violation

# Flask Configuration
HOST=0.0.0.0
PORT=5000
FLASK_DEBUG=False
SECRET_KEY=your-secret-key-123

# Telegram Configuration (Optional)
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
EOF
    echo "✅ Created .env file"
fi

# Create directories
mkdir -p static/uploads
mkdir -p static/violation_videos
mkdir -p violations

echo "✅ Environment setup complete!"
ENDSSH

# ====================================================================
# STEP 4: Stop old app and start new one
# ====================================================================
echo ""
echo "🔄 Step 4: Restarting application..."

ssh -i "$KEY_FILE" "$EC2_USER@$EC2_IP" << 'ENDSSH'
cd /home/ec2-user/plate_project

# Kill old processes
echo "Stopping old app..."
pkill -f "python.*app.py" || true
sleep 2

# Start new app
echo "Starting new app..."
nohup python3 app.py > app.log 2>&1 &
NEW_PID=$!

echo "✅ App started with PID: $NEW_PID"

# Wait for app to start
sleep 5

# Check if app is running
if ps -p $NEW_PID > /dev/null; then
   echo "✅ App is running!"
   echo ""
   echo "📊 Last 20 lines of log:"
   tail -20 app.log
else
   echo "❌ App failed to start!"
   echo ""
   echo "📊 Error log:"
   tail -50 app.log
   exit 1
fi
ENDSSH

# ====================================================================
# STEP 5: Verify deployment
# ====================================================================
echo ""
echo "🔍 Step 5: Verifying deployment..."

# Test HTTP connection
echo "Testing connection to http://$EC2_IP:5000"
sleep 3

if curl -s -o /dev/null -w "%{http_code}" http://$EC2_IP:5000 | grep -q "200\|302"; then
    echo "✅ App is responding!"
else
    echo "⚠️  App may not be ready yet. Check manually at: http://$EC2_IP:5000"
fi

# ====================================================================
# DEPLOYMENT COMPLETE
# ====================================================================
echo ""
echo "=========================================="
echo "🎉 DEPLOYMENT COMPLETE!"
echo "=========================================="
echo ""
echo "Access your app at:"
echo "🌐 http://$EC2_IP:5000"
echo ""
echo "Check logs:"
echo "ssh -i $KEY_FILE $EC2_USER@$EC2_IP 'tail -f /home/ec2-user/plate_project/app.log'"
echo ""
echo "Stop app:"
echo "ssh -i $KEY_FILE $EC2_USER@$EC2_IP 'pkill -f \"python.*app.py\"'"
echo ""
echo "=========================================="
