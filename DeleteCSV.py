import csv

csv_file = 'data/violations.csv'

with open(csv_file, 'w', newline='', encoding='utf-8') as f:
    writer = csv.writer(f)
    writer.writerow(['plate','speed','limit','status','time','image'])
print("Đã xóa tất cả dữ liệu, chỉ giữ header CSV")
