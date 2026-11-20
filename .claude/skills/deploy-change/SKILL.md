---
name: deploy-change
description: Quy trình sửa code/cấu hình/giao diện/bản dịch CBNoj và đưa lên chạy an toàn - sao lưu, migration, build giao diện, biên dịch ngôn ngữ, restart đúng dịch vụ, kiểm tra, cách hoàn tác, ghi nhật ký. Dùng cho mọi thay đổi trên máy chủ ("sửa", "thêm tính năng", "đổi giao diện", "áp dụng cấu hình").
---

# Sửa và triển khai thay đổi trên CBNoj

Trang chạy thật cho người dùng thật. Đọc `CLAUDE.md` và mục liên quan trong `docs/HE-THONG.md` trước.

## 0. Trước khi làm
1. **Có kỳ thi đang chạy không?** (cần trước mọi lần restart)
   ```bash
   cd /home/vnojsite/site
   mysql -N -e "select 'contest',\`key\`,end_time from dmoj.judge_contest where start_time<=now() and end_time>=now()
                union all select 'quiz',slug,end_time from dmoj.judge_quiz where mode='exam' and (start_time is null or start_time<=now()) and (end_time is null or end_time>=now()) and is_public=1
                union all select 'attempt-dang-lam',quiz_id,started from dmoj.judge_quizattempt where finished is null"
   ```
   (`now()` trong DB là UTC.) Có kết quả → **hỏi người dùng** trước khi restart `site`; có thể sửa file trước và restart sau.
2. **Sao lưu** thứ sắp sửa vào `/root/backup-<nhãn>-<YYYYMMDD>/` (`cp -a`), và dump DB nếu có migration/sửa dữ liệu hàng loạt (skill `backup`).
3. Nói với người dùng kế hoạch ngắn: sửa gì, cần restart gì, rủi ro.

## 1. Sửa
- Dùng Edit trên file. Giữ phong cách code hiện có. Không đụng `git checkout/reset/clean/stash` (phần tùy biến chưa commit).
- Sau khi tạo file mới: `chown cbnoj:cbnoj <file>`.
- Kiểm tra cú pháp: `/home/vnojsite/bin/python manage.py check` (cảnh báo "silenced" là bình thường).

## 2. Theo loại thay đổi
| Loại | Việc cần làm |
|---|---|
| Python (views/models/utils) | `check` → `supervisorctl restart site` (thêm `celery` nếu đụng `judge/tasks/` hoặc email) |
| Template Jinja2 | `supervisorctl restart site` |
| Model đổi cột/bảng | viết migration tay `judge/migrations/0257_*.py` (số tiếp theo, `dependencies` = migration cuối), **dump DB trước**, `manage.py migrate`, restart `site` |
| SCSS / JS / ảnh | `./make_style.sh` → `manage.py collectstatic --noinput` → `chown -R cbnoj:cbnoj /home/vnojsite/static` → restart `site` |
| Bản dịch | sửa `locale/vi/LC_MESSAGES/django.po` → `msgfmt -o django.mo django.po` (lỗi `msgfmt: fatal` = sửa dòng `.po` lỗi) → restart `site` |
| `uwsgi.ini`, `local_settings.py` | sao lưu → sửa → `check` → restart `site` (+`celery`) |
| nginx | sao lưu → sửa → `nginx -t` → `systemctl reload nginx` |
| supervisor | sửa file → `supervisorctl reread && supervisorctl update` |
| Runner/judge | `supervisorctl restart runner|judge1|judge2` (judge: restart từng cái, không cả hai cùng lúc khi đang chấm) |

## 3. Kiểm tra sau khi áp dụng
```bash
supervisorctl status site celery
for i in 1 2 3; do curl -s -o /dev/null -w "%{http_code} %{time_total}s\n" https://chuyenbacninh.io.vn/; done
tail -n 30 /var/log/cbnoj/site.stderr.log | grep -i "error\|traceback" | tail
```
- Gọi thử chính trang/tính năng vừa sửa (Django test Client với user tạm, hoặc `curl`). Nói rõ nếu **chưa** nhìn giao diện bằng mắt.
- Lần đầu sau restart có thể chậm ~2 s (khởi động nguội) - đó là bình thường.

## 4. Hoàn tác
Ghi sẵn cách quay lại (đường dẫn bản sao lưu, lệnh `cp`, `migrate judge 0256` để lùi migration nếu có thể).

## 5. Ghi nhật ký (bắt buộc)
Thêm dòng vào mục 15 của `docs/HE-THONG.md` (kèm cách hoàn tác), sửa các mục khác nếu sự thật đã đổi, cập nhật "Cập nhật lần cuối".
