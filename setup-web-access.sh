#!/bin/bash
# Script setup để truy cập app từ web

echo "=========================================="
echo "Web Access Setup"
echo "=========================================="

# Lấy thông tin
PUBLIC_IP=$(curl -s http://169.254.169.254/latest/meta-data/public-ipv4)
PRIVATE_IP=$(curl -s http://169.254.169.254/latest/meta-data/local-ipv4)
INSTANCE_ID=$(curl -s http://169.254.169.254/latest/meta-data/instance-id)

echo "Instance ID: $INSTANCE_ID"
echo "Private IP: $PRIVATE_IP"
echo "Public IP: $PUBLIC_IP"
echo ""

# Kiểm tra Security Group
echo "=========================================="
echo "Checking Security Group..."
echo "=========================================="

SG_ID=$(aws ec2 describe-instances --instance-ids $INSTANCE_ID --query 'Reservations[0].Instances[0].SecurityGroups[0].GroupId' --output text --region ap-southeast-2 2>/dev/null)

if [ -n "$SG_ID" ]; then
    echo "Security Group ID: $SG_ID"
    echo ""
    echo "Checking port 5000 rules:"
    aws ec2 describe-security-groups --group-ids $SG_ID --query 'SecurityGroups[0].IpPermissions[?FromPort==`5000`]' --output table --region ap-southeast-2
    
    PORT_5000_RULE=$(aws ec2 describe-security-groups --group-ids $SG_ID --query 'SecurityGroups[0].IpPermissions[?FromPort==`5000`]' --output text --region ap-southeast-2)
    
    if [ -z "$PORT_5000_RULE" ]; then
        echo ""
        echo "⚠️  Port 5000 is NOT open in Security Group!"
        echo "Opening port 5000..."
        aws ec2 authorize-security-group-ingress \
            --group-id $SG_ID \
            --protocol tcp \
            --port 5000 \
            --cidr 0.0.0.0/0 \
            --region ap-southeast-2 2>&1
        
        if [ $? -eq 0 ]; then
            echo "✅ Port 5000 opened successfully!"
        else
            echo "⚠️  Error opening port (may already exist)"
        fi
    else
        echo "✅ Port 5000 is already open"
    fi
else
    echo "⚠️  Could not get Security Group ID"
fi

echo ""
echo "=========================================="
echo "Access URLs"
echo "=========================================="
if [ -n "$PUBLIC_IP" ] && [ "$PUBLIC_IP" != "" ]; then
    echo "✅ Public IP found: $PUBLIC_IP"
    echo ""
    echo "From your browser, access:"
    echo "  http://$PUBLIC_IP:5000/test"
    echo "  http://$PUBLIC_IP:5000/health"
    echo "  http://$PUBLIC_IP:5000"
    echo ""
    echo "Testing public access..."
    curl -s --connect-timeout 5 http://$PUBLIC_IP:5000/test 2>&1 | head -1
    if [ $? -eq 0 ]; then
        echo "✅ Public access works!"
    else
        echo "⚠️  Cannot access from outside (may need to wait a few seconds)"
    fi
else
    echo "⚠️  No Public IP found - instance may not have public IP"
    echo "Check AWS Console → EC2 → Instances → Your instance"
    echo "Make sure 'Auto-assign Public IP' is enabled"
fi

echo ""
echo "=========================================="
echo "Troubleshooting"
echo "=========================================="
echo "If you cannot access from browser:"
echo "1. Make sure app is running: python3 app.py"
echo "2. Check Security Group allows port 5000"
echo "3. Use Public IP (not Private IP 172.31.30.168)"
echo "4. Wait 1-2 minutes after opening Security Group"
echo "5. Check firewall on your computer"

