-- =====================================================
-- MIGRATION: Fill vehicle_owner table with fake data
-- Date: 2026-01-26
-- Purpose: Fill missing owner information with Vietnamese fake data
-- =====================================================

-- Tạo dữ liệu giả cho các biển số từ bảng violations
-- Sử dụng tên người Việt Nam, địa chỉ và số điện thoại giả

-- Bước 1: Insert các biển số mới chưa có trong vehicle_owner
INSERT INTO vehicle_owner (plate, owner_name, address, phone)
SELECT DISTINCT 
    v.plate,
    -- Tạo tên dựa trên biển số (sử dụng hash để nhất quán)
    CONCAT(
        ELT(1 + (CRC32(v.plate) % 30), 
            'Nguyễn', 'Trần', 'Lê', 'Phạm', 'Hoàng', 'Phan', 'Vũ', 'Võ', 'Đặng', 'Bùi',
            'Đỗ', 'Hồ', 'Ngô', 'Dương', 'Lý', 'Đinh', 'Lương', 'Tôn', 'Trịnh', 'Đào',
            'Mai', 'Tạ', 'Lâm', 'Phùng', 'Vương', 'Tăng', 'Hà', 'Lưu', 'Cao', 'Trương'
        ),
        ' ',
        IF((CRC32(v.plate) % 2) = 0, 
            CONCAT('Thị ', ELT(1 + ((CRC32(v.plate) / 2) % 10), 'Anh', 'Bình', 'Chi', 'Dung', 'Hạnh', 'Hoa', 'Lan', 'Mai', 'Nga', 'Oanh')),
            CONCAT('Văn ', ELT(1 + ((CRC32(v.plate) / 2) % 10), 'Anh', 'Bình', 'Cường', 'Dũng', 'Hùng', 'Khang', 'Long', 'Nam', 'Phong', 'Quân'))
        )
    ) as owner_name,
    -- Tạo địa chỉ dựa trên mã tỉnh (2 số đầu)
    CASE 
        WHEN LEFT(v.plate, 2) = '10' THEN CONCAT('Hà Nội - ', ELT(1 + (CRC32(v.plate) % 9), 'Ba Đình', 'Hoàn Kiếm', 'Tây Hồ', 'Long Biên', 'Cầu Giấy', 'Đống Đa', 'Hai Bà Trưng', 'Hoàng Mai', 'Thanh Xuân'))
        WHEN LEFT(v.plate, 2) = '11' THEN CONCAT('Cao Bằng - ', ELT(1 + (CRC32(v.plate) % 3), 'Thành phố Cao Bằng', 'Bảo Lạc', 'Bảo Lâm'))
        WHEN LEFT(v.plate, 2) = '12' THEN CONCAT('Lào Cai - ', ELT(1 + (CRC32(v.plate) % 3), 'Thành phố Lào Cai', 'Bát Xát', 'Sa Pa'))
        WHEN LEFT(v.plate, 2) = '29' THEN CONCAT('Hà Nam - ', ELT(1 + (CRC32(v.plate) % 3), 'Thành phố Phủ Lý', 'Duy Tiên', 'Kim Bảng'))
        WHEN LEFT(v.plate, 2) = '30' THEN CONCAT('Nam Định - ', ELT(1 + (CRC32(v.plate) % 4), 'Thành phố Nam Định', 'Mỹ Lộc', 'Vụ Bản', 'Ý Yên'))
        WHEN LEFT(v.plate, 2) = '51' THEN CONCAT('Khánh Hòa - ', ELT(1 + (CRC32(v.plate) % 3), 'Thành phố Nha Trang', 'Cam Ranh', 'Diên Khánh'))
        WHEN LEFT(v.plate, 2) = '62' THEN CONCAT('Đồng Nai - ', ELT(1 + (CRC32(v.plate) % 7), 'Thành phố Biên Hòa', 'Long Thành', 'Nhơn Trạch', 'Tân Phú', 'Vĩnh Cửu', 'Xuân Lộc', 'Trảng Bom'))
        WHEN LEFT(v.plate, 2) = '64' THEN CONCAT('TP.HCM - ', ELT(1 + (CRC32(v.plate) % 19), 'Quận 1', 'Quận 2', 'Quận 3', 'Quận 4', 'Quận 5', 'Quận 6', 'Quận 7', 'Quận 8', 'Quận 9', 'Quận 10', 'Quận 11', 'Quận 12', 'Quận Bình Thạnh', 'Quận Tân Bình', 'Quận Tân Phú', 'Quận Phú Nhuận', 'Quận Gò Vấp', 'Quận Bình Tân', 'Quận Thủ Đức'))
        WHEN LEFT(v.plate, 2) = '92' THEN CONCAT('Cần Thơ - ', ELT(1 + (CRC32(v.plate) % 4), 'Quận Ninh Kiều', 'Quận Ô Môn', 'Quận Bình Thủy', 'Quận Cái Răng'))
        ELSE CONCAT('TP.HCM - Quận ', 1 + (CRC32(v.plate) % 19))
    END as address,
    -- Tạo số điện thoại Việt Nam (10 số, bắt đầu bằng 0)
    CONCAT(
        '0',
        ELT(1 + (CRC32(v.plate) % 18), '90', '91', '92', '93', '94', '95', '96', '97', '98', '99', '32', '33', '34', '35', '36', '37', '38', '39'),
        LPAD(ABS(CRC32(v.plate)) % 100000000, 8, '0')
    ) as phone
FROM violations v
WHERE v.plate IS NOT NULL 
  AND v.plate != '' 
  AND UPPER(TRIM(v.plate)) NOT IN ('N/A', 'NULL', 'UNKNOWN', 'NONE', 'NAN')
  AND NOT EXISTS (
      SELECT 1 FROM vehicle_owner vo WHERE vo.plate = v.plate
  )
ON DUPLICATE KEY UPDATE plate = plate;

-- Bước 2: Cập nhật các bản ghi đã có nhưng thiếu thông tin
UPDATE vehicle_owner vo
INNER JOIN violations v ON vo.plate = v.plate
SET 
    vo.owner_name = CASE 
        WHEN vo.owner_name IS NULL OR vo.owner_name = '' THEN
            CONCAT(
                ELT(1 + (CRC32(v.plate) % 30), 
                    'Nguyễn', 'Trần', 'Lê', 'Phạm', 'Hoàng', 'Phan', 'Vũ', 'Võ', 'Đặng', 'Bùi',
                    'Đỗ', 'Hồ', 'Ngô', 'Dương', 'Lý', 'Đinh', 'Lương', 'Tôn', 'Trịnh', 'Đào',
                    'Mai', 'Tạ', 'Lâm', 'Phùng', 'Vương', 'Tăng', 'Hà', 'Lưu', 'Cao', 'Trương'
                ),
                ' ',
                IF((CRC32(v.plate) % 2) = 0, 
                    CONCAT('Thị ', ELT(1 + ((CRC32(v.plate) / 2) % 10), 'Anh', 'Bình', 'Chi', 'Dung', 'Hạnh', 'Hoa', 'Lan', 'Mai', 'Nga', 'Oanh')),
                    CONCAT('Văn ', ELT(1 + ((CRC32(v.plate) / 2) % 10), 'Anh', 'Bình', 'Cường', 'Dũng', 'Hùng', 'Khang', 'Long', 'Nam', 'Phong', 'Quân'))
                )
            )
        ELSE vo.owner_name
    END,
    vo.address = CASE 
        WHEN vo.address IS NULL OR vo.address = '' THEN
            CASE 
                WHEN LEFT(v.plate, 2) = '10' THEN CONCAT('Hà Nội - ', ELT(1 + (CRC32(v.plate) % 9), 'Ba Đình', 'Hoàn Kiếm', 'Tây Hồ', 'Long Biên', 'Cầu Giấy', 'Đống Đa', 'Hai Bà Trưng', 'Hoàng Mai', 'Thanh Xuân'))
                WHEN LEFT(v.plate, 2) = '11' THEN CONCAT('Cao Bằng - ', ELT(1 + (CRC32(v.plate) % 3), 'Thành phố Cao Bằng', 'Bảo Lạc', 'Bảo Lâm'))
                WHEN LEFT(v.plate, 2) = '29' THEN CONCAT('Hà Nam - ', ELT(1 + (CRC32(v.plate) % 3), 'Thành phố Phủ Lý', 'Duy Tiên', 'Kim Bảng'))
                WHEN LEFT(v.plate, 2) = '30' THEN CONCAT('Nam Định - ', ELT(1 + (CRC32(v.plate) % 4), 'Thành phố Nam Định', 'Mỹ Lộc', 'Vụ Bản', 'Ý Yên'))
                WHEN LEFT(v.plate, 2) = '62' THEN CONCAT('Đồng Nai - ', ELT(1 + (CRC32(v.plate) % 7), 'Thành phố Biên Hòa', 'Long Thành', 'Nhơn Trạch', 'Tân Phú', 'Vĩnh Cửu', 'Xuân Lộc', 'Trảng Bom'))
                WHEN LEFT(v.plate, 2) = '64' THEN CONCAT('TP.HCM - ', ELT(1 + (CRC32(v.plate) % 19), 'Quận 1', 'Quận 2', 'Quận 3', 'Quận 4', 'Quận 5', 'Quận 6', 'Quận 7', 'Quận 8', 'Quận 9', 'Quận 10', 'Quận 11', 'Quận 12', 'Quận Bình Thạnh', 'Quận Tân Bình', 'Quận Tân Phú', 'Quận Phú Nhuận', 'Quận Gò Vấp', 'Quận Bình Tân', 'Quận Thủ Đức'))
                ELSE CONCAT('TP.HCM - Quận ', 1 + (CRC32(v.plate) % 19))
            END
        ELSE vo.address
    END,
    vo.phone = CASE 
        WHEN vo.phone IS NULL OR vo.phone = '' THEN
            CONCAT(
                '0',
                ELT(1 + (CRC32(v.plate) % 18), '90', '91', '92', '93', '94', '95', '96', '97', '98', '99', '32', '33', '34', '35', '36', '37', '38', '39'),
                LPAD(ABS(CRC32(v.plate)) % 100000000, 8, '0')
            )
        ELSE vo.phone
    END
WHERE v.plate IS NOT NULL 
  AND v.plate != '' 
  AND UPPER(TRIM(v.plate)) NOT IN ('N/A', 'NULL', 'UNKNOWN', 'NONE', 'NAN')
  AND (vo.owner_name IS NULL OR vo.owner_name = '' OR vo.address IS NULL OR vo.address = '' OR vo.phone IS NULL OR vo.phone = '');
