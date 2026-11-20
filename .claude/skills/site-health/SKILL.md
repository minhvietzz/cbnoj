---
name: site-health
description: Kiểm tra sức khỏe CBNoj - trạng thái dịch vụ, tải máy, thời gian phản hồi, hàng đợi, lỗi gần đây, tìm nguyên nhân site chập chờn/chậm khi đông người. Chỉ đọc, không sửa. Dùng khi người dùng nói "site chậm", "chập chờn", "xem log", "kiểm tra hệ thống", "sao lỗi 502".
---

# Kiểm tra sức khỏe CBNoj (chỉ đọc)

Đọc `docs/HE-THONG.md` mục 4, 6, 13 để biết cấu hình hiện tại. Không sửa gì, không restart. Không in `local_settings.py`.
Giờ trong log nginx/uwsgi là **UTC**; giờ Việt Nam = UTC+7. Hỏi người dùng "lúc mấy giờ VN" rồi đổi.

## Bước 1 - Tổng quan (một lệnh)
```bash
supervisorctl status; uptime; free -m | head -2; df -h / | tail -1
systemctl is-active nginx mariadb redis-server ai-tutor
redis-cli ping; mysql -N -e "show global status like 'Threads_connected'; show global status like 'Max_used_connections'; show global status like 'Slow_queries'"
```
Dấu hiệu xấu: dịch vụ không `RUNNING`, tải > số nhân (4), RAM `available` < 1 GB, đĩa > 85%.

## Bước 2 - Lỗi nginx và uwsgi
```bash
tail -n 200 /var/log/nginx/error.log | grep -v "open() failed" | tail -20      # "open() failed" là nhiễu vô hại
awk '$9 ~ /^5/' /var/log/nginx/access.log | tail -20                            # 5xx
grep -ci "listen queue" /var/log/cbnoj/site.stderr.log                          # hàng chờ đầy
grep -ci "harakiri" /var/log/cbnoj/site.stderr.log
dmesg 2>/dev/null | grep -i "out of memory" | tail -3
```

## Bước 3 - Đo thời gian phản hồi theo khung giờ
Từ 2026-11-13 access.log có `rt=` (tổng) và `urt=` (uwsgi). Ví dụ p50/p90/p99 trong một khung giờ (UTC) ngày hôm nay:
```bash
LC_ALL=C awk -v from="18/Nov/2026:13:00" -v to="18/Nov/2026:14:00" '
  { t=substr($4,2,17); if (t>=from && t<=to) { match($0,/rt=[0-9.]+/); print substr($0,RSTART+3,RLENGTH-3) } }' \
  /var/log/nginx/access.log | sort -n | awk '{a[NR]=$1} END{print "n="NR, "p50="a[int(NR*.5)], "p90="a[int(NR*.9)], "p99="a[int(NR*.99)], "max="a[NR]}'
```
(đổi ngày/giờ). Liệt kê yêu cầu chậm nhất: lọc `rt>3` và `awk '{print $7}' | sort | uniq -c | sort -rn`. Với log uwsgi cũ dùng dòng `generated N bytes in X msecs` trong `/var/log/cbnoj/site.stderr.log`.

## Bước 4 - Các nghi phạm đã biết
- Đăng ký hàng loạt: email nay chạy nền; nếu vẫn chậm kiểm tra `tail /var/log/cbnoj/celery.stderr.log` xem email có kẹt/thử lại.
- Đăng nhập đồng loạt (băm mật khẩu ~0,5 s mỗi lượt).
- "Chạy thử" `POST /problem/<mã>/run` (~3,4 s/lượt); đếm: `grep -c "/run" /var/log/nginx/access.log`.
- Thi quiz đông người: nhịp tim 15 s/người (`/attempt/<id>/heartbeat/`) và tự lưu.
- Chấm bài tồn đọng: xem trang `/server-status/` (cần quyền) hoặc `mysql -N -e "select status,count(*) from dmoj.judge_submission where date > now() - interval 1 hour group by status"`.
- Việc định kỳ không chạy (celery beat, `finalize_quiz_attempts`): xem mục 6 của tài liệu.

## Bước 5 - Kết luận
Báo ngắn gọn bằng tiếng Việt: có chập chờn thật không (kèm số liệu), nguyên nhân khả dĩ nhất, đề xuất sửa (không tự sửa). Nếu người dùng đồng ý sửa → dùng skill `deploy-change`. Chẩn đoán không đổi hệ thống thì **không cần** ghi nhật ký; nhưng nếu phát hiện điều mới về hệ thống, cập nhật mục 13 của tài liệu.
