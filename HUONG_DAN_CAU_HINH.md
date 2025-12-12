# 📋 Hướng dẫn cấu hình AWS để Deploy Tự động

## 🎯 Thông tin cần thiết

Để script tự động deploy hoạt động, bạn cần cung cấp các thông tin sau trong file `aws-config.json`:

### 1. ✅ Thông tin đã có sẵn (không cần thay đổi)
- `region`: `ap-southeast-2` ✅
- `accountId`: `598250965573` ✅
- `ecrRepository`: `plate_violation` ✅

### 2. 🔧 Thông tin cần cấu hình

#### A. EC2 Configuration

**a) Key Pair Name** (BẮT BUỘC)
```json
"keyPairName": "your-key-pair-name"
```

**Cách lấy:**
1. Vào **AWS Console** → **EC2** → **Key Pairs**
2. Nếu chưa có, click **Create key pair**
3. Tên: `plate-violation-key` (hoặc tên bạn muốn)
4. Type: **RSA**
5. Format: **.pem** (cho Linux/Mac) hoặc **.ppk** (cho Windows PuTTY)
6. Click **Create key pair** và tải file về máy
7. Copy tên key pair vào `aws-config.json`

**b) VPC ID và Subnet ID** (TÙY CHỌN - script sẽ tự động lấy nếu không có)

Nếu muốn chỉ định cụ thể:
1. Vào **AWS Console** → **VPC** → **Your VPCs**
2. Copy **VPC ID** (ví dụ: `vpc-0123456789abcdef0`)
3. Vào **Subnets**, chọn subnet trong VPC đó
4. Copy **Subnet ID** (ví dụ: `subnet-0123456789abcdef0`)

**c) Instance Type** (TÙY CHỌN)
```json
"instanceType": "t3.medium"  // hoặc t3.small, t3.large, etc.
```

**d) AMI ID** (TÙY CHỌN - script sẽ tự động tìm Ubuntu 22.04)

---

#### B. RDS Configuration

**a) Master Password** (BẮT BUỘC)
```json
"masterPassword": "CHANGE-THIS-PASSWORD"
```
⚠️ **QUAN TRỌNG**: Đổi mật khẩu này thành mật khẩu mạnh!

**b) Database Settings** (TÙY CHỌN)
- `instanceClass`: `db.t3.micro` (Free tier) hoặc `db.t3.small`
- `allocatedStorage`: `20` (GB)
- `publiclyAccessible`: `true` (để EC2 có thể kết nối)

---

#### C. Application Configuration

**a) Secret Key** (BẮT BUỘC)
```json
"secretKey": "CHANGE-THIS-SECRET-KEY"
```
⚠️ Tạo một chuỗi ngẫu nhiên mạnh (ít nhất 32 ký tự)

**b) Telegram Bot** (TÙY CHỌN - có thể để trống nếu không dùng)
```json
"telegramToken": "YOUR-TELEGRAM-BOT-TOKEN",
"telegramChatId": "YOUR-TELEGRAM-CHAT-ID"
```

**Cách lấy Telegram Token:**
1. Mở Telegram, tìm **@BotFather**
2. Gửi lệnh `/newbot`
3. Làm theo hướng dẫn để tạo bot
4. Copy token được cung cấp

**Cách lấy Chat ID:**
1. Tìm bot **@userinfobot** trên Telegram
2. Gửi `/start`
3. Bot sẽ trả về Chat ID của bạn

---

## 📝 Các bước cấu hình

### Bước 1: Mở file `aws-config.json`

```powershell
notepad aws-config.json
```

### Bước 2: Điền thông tin

Thay thế các giá trị sau:
- `"keyPairName": "your-key-pair-name"` → Tên key pair của bạn
- `"masterPassword": "CHANGE-THIS-PASSWORD"` → Mật khẩu MySQL mạnh
- `"secretKey": "CHANGE-THIS-SECRET-KEY"` → Secret key ngẫu nhiên
- `"telegramToken": "YOUR-TELEGRAM-BOT-TOKEN"` → Token bot Telegram (nếu có)
- `"telegramChatId": "YOUR-TELEGRAM-CHAT-ID"` → Chat ID Telegram (nếu có)

### Bước 3: Lưu file

### Bước 4: Chạy script deploy

```powershell
.\auto-deploy-aws.ps1
```

---

## 🔍 Cách lấy thông tin chi tiết

### 1. Lấy VPC ID và Subnet ID

```powershell
# Liệt kê tất cả VPCs
aws ec2 describe-vpcs --region ap-southeast-2 --query "Vpcs[*].{VpcId:VpcId,Name:Tags[?Key=='Name'].Value|[0],CidrBlock:CidrBlock}" --output table

# Liệt kê Subnets trong VPC
aws ec2 describe-subnets --region ap-southeast-2 --filters "Name=vpc-id,Values=vpc-xxxxx" --query "Subnets[*].{SubnetId:SubnetId,AvailabilityZone:AvailabilityZone,CidrBlock:CidrBlock}" --output table
```

### 2. Lấy Key Pair Names

```powershell
aws ec2 describe-key-pairs --region ap-southeast-2 --query "KeyPairs[*].KeyName" --output table
```

### 3. Lấy AMI ID cho Ubuntu 22.04

```powershell
aws ec2 describe-images --region ap-southeast-2 --owners 099720109477 --filters "Name=name,Values=ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*" "Name=state,Values=available" --query "Images | sort_by(@, &CreationDate) | [-1].{ImageId:ImageId,Name:Name,CreationDate:CreationDate}" --output table
```

---

## ⚠️ Lưu ý quan trọng

1. **Key Pair**: Phải tạo và tải về trước khi deploy
2. **Mật khẩu**: Sử dụng mật khẩu mạnh cho RDS và Secret Key
3. **Chi phí**: EC2 và RDS sẽ tính phí theo giờ
4. **Security Groups**: Script sẽ tự động tạo và cấu hình
5. **Thời gian**: 
   - EC2 khởi động: ~2-3 phút
   - RDS khởi động: ~5-10 phút

---

## 🆘 Troubleshooting

### Lỗi: Key Pair không tồn tại
- Kiểm tra tên key pair trong AWS Console
- Đảm bảo key pair ở đúng region (ap-southeast-2)

### Lỗi: VPC không tồn tại
- Kiểm tra VPC ID trong AWS Console
- Hoặc để trống để script tự động lấy VPC mặc định

### Lỗi: Không đủ quyền
- Kiểm tra IAM user có các quyền:
  - EC2: Full access hoặc Create/Describe instances
  - RDS: Full access hoặc Create/Describe DB instances
  - ECR: Full access
  - VPC: Describe VPCs, Subnets, Security Groups

---

## 📞 Hỗ trợ

Sau khi cấu hình xong, chạy:
```powershell
.\auto-deploy-aws.ps1
```

Script sẽ tự động:
1. ✅ Tạo Security Group
2. ✅ Tạo EC2 Instance
3. ✅ Tạo RDS Database
4. ✅ Deploy container từ ECR
5. ✅ Cấu hình tự động

