# CBNoj — hướng dẫn cho Claude (và người) làm việc trên hệ thống này

CBNoj = trang chấm bài + thi trắc nghiệm của trường chuyên Bắc Ninh (https://chuyenbacninh.io.vn), fork của VNOJ/DMOJ, chạy trên chính máy chủ này. Người quản trị nói **tiếng Việt**: trả lời bằng tiếng Việt, ngắn gọn, nói rõ điều gì đã kiểm tra và điều gì chưa.

## Đọc trước khi làm
1. **`docs/HE-THONG.md`** — tài liệu đầy đủ (kiến trúc, dịch vụ, đường dẫn, quiz, giao diện, sao lưu, nhật ký). Đọc ít nhất mục 1–6 và mục liên quan tới việc sắp làm.
2. Kế hoạch dự án đang làm: `docs/DU-AN-CAI-TAO.md` (Lớp, Môn, mã đề, giao diện mới) và `docs/DU-AN-TRAC-NGHIEM.md`; ghi chú trạng thái dự án nằm trong bộ nhớ (`cbnoj-class-project`).
3. Skill trong `.claude/skills/` — quy trình từng việc (đăng quiz, đăng bài tập, tạo kỳ thi, kiểm tra sức khỏe, deploy, sao lưu…). Có skill khớp thì dùng skill.

## QUY TẮC BẮT BUỘC: giữ tài liệu luôn đúng
Sau **mỗi** thay đổi thật (code, cấu hình, dịch vụ, dữ liệu quan trọng như tạo quiz/kỳ thi/bài tập, đổi giao diện, sự cố và cách xử lý):
1. Thêm một dòng vào mục **"15. Nhật ký thay đổi"** của `docs/HE-THONG.md`, mới nhất ở trên cùng: `- YYYY-MM-DD — [loại] Việc đã làm. File/dịch vụ liên quan. Cách hoàn tác.`
2. Nếu thay đổi làm sai câu nào ở các mục khác, **sửa câu đó** (đổi số, đường dẫn, danh sách quiz…).
3. Cập nhật dòng "Cập nhật lần cuối" ở đầu tài liệu.
Việc này là một phần của "xong việc", không phải tùy chọn. Chỉ đọc/chẩn đoán thì không cần ghi.

## Cách chạy lệnh
- Django: `cd /home/vnojsite/site && /home/vnojsite/bin/python manage.py <lệnh>` (python hệ thống thiếu MySQLdb; `judge-venv` chỉ cho judge).
- Dịch vụ: `supervisorctl status|restart site|celery|celerybeat|bridged|wsevent|judge1|judge2|runner`; nginx `nginx -t && systemctl reload nginx`.
- Git phải chạy bằng chủ repo: `runuser -u cbnoj -- git ...`.
- DB: `mysql -e "..."` (root, qua socket), database `dmoj`.
- File tạm/script thử nghiệm để trong thư mục scratchpad của phiên, không để trong site.
- Sau khi tạo/sửa file trong `/home/vnojsite/site`, giữ quyền sở hữu `cbnoj:cbnoj` (`chown -R cbnoj:cbnoj <file>`).

## Cấm và phải hỏi trước
- **Không bao giờ** in, ghi vào chat/tài liệu/log: mật khẩu, khóa API, token, nội dung `dmoj/local_settings.py`, `/home/vnojsite/admin_password.txt`, `/home/vnojsite/db_password.txt`, `judge-conf/runner.key`. Chỉ nói "nằm ở file X". Khi cần xem cấu hình hãy che giá trị (`sed -E 's/(PASSWORD|SECRET|KEY|TOKEN)[^=]*=.*/\1=<ẩn>/'`).
- **Hỏi người quản trị trước khi:** restart dịch vụ, xóa dữ liệu (quiz, bài, user, lượt làm), gửi email/tin nhắn, sửa nginx/MariaDB/Redis, đổi quyền người dùng, đăng nội dung công khai.
- **Không restart `site` khi đang có kỳ thi** (contest đang chạy hoặc quiz `mode=exam` đang ở pha running) trừ khi người quản trị đồng ý rõ ràng.
- **AI Tutor** (`/opt/ai-tutor`, cổng 8765) tách biệt hoàn toàn: không đụng nginx/MariaDB/Redis/`/home/vnojsite` vì nó.
- Trước thay đổi lớn (migration, sửa cấu hình, sửa nhiều file): sao lưu file/DB trước (xem skill `backup`). Đã có sao lưu tự động hằng đêm 03:00 VN (mục 12 tài liệu), nhưng vẫn sao lưu ngay trước khi migrate.
- Git: phần tùy biến đã commit/push lên repo riêng từ 2026-11-20 (mục 1 và 8 tài liệu), nhưng công việc mới vẫn có thể **chưa commit** (kiểm tra `runuser -u cbnoj -- git status --short`). Không chạy `git checkout/reset/clean/stash` và không commit/push khi người quản trị chưa yêu cầu.
- Migration: **không restart `site` trước khi migrate** (model mới thiếu cột làm các trang lỗi 500). Test phải chạy trên bản sao DB tạm, không `manage.py test` trong thư mục site.

## Kiểm thử
`manage.py test` không chạy được (DB không có quyền tạo `test_dmoj`). Kiểm thử bằng Django test Client + `force_login` trên user tạm (có `Profile`), xong xóa user tạm. Với giao diện: chụp/duyệt trang thật nếu có công cụ, nếu không thì nói rõ là chưa nhìn bằng mắt.
