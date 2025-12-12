# 🌐 Hướng dẫn Truy cập App từ Bên ngoài EC2

## ✅ App đã chạy thành công!

Logs cho thấy app đang hoạt động:
```
127.0.0.1 - - [12/Dec/2025 20:11:33] "GET /test HTTP/1.1" 200 -
127.0.0.1 - - [12/Dec/2025 20:11:44] "GET /health HTTP/1.1" 200 -
```

## 🔒 Vấn đề: Security Group chưa mở port 5000

Để truy cập từ máy tính của bạn, cần mở port 5000 trong Security Group.

### Cách 1: Dùng AWS Console (Khuyến nghị)

1. Vào **AWS Console** → **EC2** → **Instances**
2. Chọn EC2 instance của bạn
3. Click tab **Security** → Click vào **Security Group**
4. Click **Edit inbound rules**
5. Click **Add rule**:
   - **Type**: Custom TCP
   - **Port**: 5000
   - **Source**: My IP (hoặc 0.0.0.0/0 để cho phép từ mọi nơi)
6. Click **Save rules**

### Cách 2: Dùng AWS CLI

```bash
# Lấy Security Group ID
INSTANCE_ID=$(curl -s http://169.254.169.254/latest/meta-data/instance-id)
SG_ID=$(aws ec2 describe-instances --instance-ids $INSTANCE_ID --query 'Reservations[0].Instances[0].SecurityGroups[0].GroupId' --output text)

# Mở port 5000 từ mọi nơi (0.0.0.0/0)
aws ec2 authorize-security-group-ingress \
    --group-id $SG_ID \
    --protocol tcp \
    --port 5000 \
    --cidr 0.0.0.0/0 \
    --region ap-southeast-2

# Hoặc chỉ cho phép IP của bạn
# Thay YOUR_IP bằng IP thực tế của bạn
aws ec2 authorize-security-group-ingress \
    --group-id $SG_ID \
    --protocol tcp \
    --port 5000 \
    --cidr YOUR_IP/32 \
    --region ap-southeast-2
```

### Cách 3: Dùng script

```bash
chmod +x check-security-group.sh
./check-security-group.sh
```

## 🌐 Sau khi mở port, truy cập:

Từ trình duyệt trên máy tính của bạn:
```
http://172.31.30.168:5000/test
http://172.31.30.168:5000/health
http://172.31.30.168:5000
```

**Lưu ý**: Thay `172.31.30.168` bằng **Public IP** của EC2 instance (không phải Private IP).

Để lấy Public IP:
```bash
curl http://169.254.169.254/latest/meta-data/public-ipv4
```

Hoặc xem trong AWS Console → EC2 → Instances → Public IPv4 address

## 🔍 Kiểm tra kết nối

Sau khi mở Security Group, test từ máy tính của bạn:

```bash
# Test từ máy tính của bạn (không phải EC2)
curl http://EC2_PUBLIC_IP:5000/health

# Hoặc mở trình duyệt
# http://EC2_PUBLIC_IP:5000/test
```

## ⚠️ Lưu ý bảo mật

- **Không nên** mở port 5000 cho `0.0.0.0/0` trong production
- **Nên** chỉ cho phép IP của bạn hoặc dùng VPN
- **Nên** dùng Nginx reverse proxy với SSL/HTTPS

## 📝 Tóm tắt

1. ✅ App đã chạy thành công trên EC2
2. ✅ App đang phản hồi request (logs cho thấy 200 OK)
3. ⚠️ Cần mở Security Group port 5000 để truy cập từ bên ngoài
4. 🌐 Sau khi mở port, có thể truy cập từ browser

