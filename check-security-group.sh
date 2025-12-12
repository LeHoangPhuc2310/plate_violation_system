#!/bin/bash
# Script kiểm tra Security Group

echo "Checking EC2 Security Group configuration..."
echo ""

# Lấy instance ID
INSTANCE_ID=$(curl -s http://169.254.169.254/latest/meta-data/instance-id)
echo "Instance ID: $INSTANCE_ID"

# Lấy Security Group ID
SG_ID=$(aws ec2 describe-instances --instance-ids $INSTANCE_ID --query 'Reservations[0].Instances[0].SecurityGroups[0].GroupId' --output text 2>/dev/null)

if [ -n "$SG_ID" ]; then
    echo "Security Group ID: $SG_ID"
    echo ""
    echo "Current Security Group rules:"
    aws ec2 describe-security-groups --group-ids $SG_ID --query 'SecurityGroups[0].IpPermissions[*].{Port:FromPort,Protocol:IpProtocol,Source:IpRanges[0].CidrIp}' --output table
    echo ""
    echo "To allow access from anywhere, run:"
    echo "  aws ec2 authorize-security-group-ingress --group-id $SG_ID --protocol tcp --port 5000 --cidr 0.0.0.0/0"
else
    echo "Could not get Security Group ID. Make sure AWS CLI is configured."
fi

