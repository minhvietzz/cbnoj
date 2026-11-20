---
name: backup
description: Sao lưu và khôi phục CBNoj - dump cơ sở dữ liệu, gói cấu hình và phần tùy biến chưa commit, dữ liệu bài tập, file tải lên; liệt kê/kiểm tra bản sao lưu; hướng dẫn khôi phục. Dùng khi người dùng nói "sao lưu", "backup", "khôi phục", "trước khi sửa lớn".
---

# Sao lưu và khôi phục

Đọc `docs/HE-THONG.md` mục 12. Hiện **không có sao lưu tự động**, và toàn bộ phần tùy biến CBNoj **chưa commit vào git** - đây là rủi ro lớn nhất. Bản sao lưu nằm ngoài thư mục site, thuộc root, quyền 700 (có thể chứa dữ liệu học sinh và cấu hình bí mật).

## Sao lưu đầy đủ (an toàn khi site đang chạy)
```bash
D=/home/vnojsite/backups/$(date +%Y%m%d-%H%M)-<nhãn>; mkdir -p $D && chmod 700 $D
# 1. CSDL (nhất quán, không khóa bảng)
mysqldump --single-transaction --routines dmoj | gzip > $D/dmoj.sql.gz
# 2. Cấu hình + phần tùy biến (loại bỏ node_modules, __pycache__, ảnh build lại được)
tar czf $D/site-code.tar.gz --exclude=node_modules --exclude=__pycache__ --exclude=sass_processed -C /home/vnojsite site
tar czf $D/config.tar.gz /etc/supervisor/conf.d /etc/nginx/nginx.conf /etc/nginx/conf.d /etc/nginx/snippets /home/vnojsite/judge-conf /home/vnojsite/runner 2>/dev/null
# 3. Dữ liệu bài tập và file người dùng tải lên
tar czf $D/problems.tar.gz -C /home/vnojsite problems
tar czf $D/media.tar.gz -C /home/vnojsite media
ls -lh $D; gzip -t $D/dmoj.sql.gz && echo "dump OK"
```
`site-code.tar.gz` đã gồm `local_settings.py`, `uwsgi.ini`, `django.mo` và mọi phần chưa commit; **coi cả thư mục sao lưu là bí mật** (không gửi qua chat, không đưa lên nơi công cộng).
Sao lưu nhanh trước khi sửa: chỉ cần dòng 1 (dump DB) và `cp -a` đúng các file sắp sửa vào `/root/backup-<nhãn>-<ngày>/`.

## Kiểm tra bản sao lưu
`gzip -t`, kích thước hợp lý (DB hiện ~vài MB), `tar tzf ... | head`. Một bản sao lưu chưa từng thử khôi phục chưa chắc dùng được: lần đầu hãy thử `gunzip -c dmoj.sql.gz | head -50` và đếm dòng `CREATE TABLE`.

## Dọn dẹp
Giữ vài bản gần nhất; xóa bản cũ **chỉ khi người dùng đồng ý**.

## Khôi phục (luôn hỏi người dùng trước, nói rõ sẽ ghi đè gì)
- **File cấu hình/code**: giải nén ra thư mục tạm, so sánh (`diff -r`), chép lại đúng file cần, `chown cbnoj:cbnoj`, restart dịch vụ liên quan (skill `deploy-change`).
- **CSDL**: sẽ ghi đè mọi dữ liệu hiện tại. Trước tiên dump trạng thái hiện tại thành một bản mới, **dừng site** (`supervisorctl stop site celery bridged`), rồi `gunzip -c dmoj.sql.gz | mysql dmoj`, khởi động lại. Không làm khi có kỳ thi.
- Khôi phục từng bảng (ví dụ chỉ `judge_quiz*`) an toàn hơn: trích riêng bảng từ dump rồi nạp vào DB tạm để so sánh trước.

## Đề xuất cải thiện (chỉ khi người dùng đồng ý)
Cron hằng đêm chạy các lệnh trên + giữ 7 bản; commit phần tùy biến vào một nhánh git riêng (`runuser -u cbnoj -- git ...`) hoặc đẩy lên repo riêng tư.

## Kết thúc
Báo đường dẫn thư mục sao lưu, dung lượng, kết quả kiểm tra. Ghi một dòng vào mục 15 và cập nhật mục 12 của `docs/HE-THONG.md` nếu có bản sao lưu đáng nhớ.
