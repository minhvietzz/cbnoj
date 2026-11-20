# CBNoj: Chuyên Bắc Ninh Online Judge

Trang chấm bài lập trình và thi trắc nghiệm của trường THPT chuyên Bắc Ninh, chạy tại <https://chuyenbacninh.io.vn>.

CBNoj là fork của [VNOJ](https://github.com/VNOI-Admin/OJ) (bản thân VNOJ là fork của [DMOJ](https://github.com/DMOJ/online-judge)), dựa trên commit upstream `bc50e417b`. Mã nguồn theo giấy phép [AGPL-3.0](LICENSE).

## Có gì khác so với VNOJ

- **Quiz / thi trắc nghiệm**: 4 loại câu (một đáp án, nhiều đáp án, trả lời ngắn, đúng/sai 4 ý), rút ngẫu nhiên N câu mỗi bài, giám sát khi thi (toàn màn hình, đếm vi phạm, tự nộp), công bố điểm theo thời điểm, xuất Excel.
- **Ngân hàng câu hỏi, luyện tập, khóa học**.
- **Chạy thử** ngay trên trang bài tập (không chấm điểm).
- **Giao diện "neo"** có chế độ sáng/tối, trang `/edit/profile/` thiết kế lại.
- **Cloudflare Turnstile** ở trang đăng nhập, **email gửi nền** qua celery, trang trạng thái máy chủ `/server-status/`.
- Bản dịch tiếng Việt bổ sung.

## Tài liệu

- `docs/HE-THONG.md`: tài liệu vận hành nội bộ (đường dẫn, dịch vụ, nhật ký). Không đưa lên repo công khai; nằm trên máy chủ.
- [`CLAUDE.md`](CLAUDE.md) và [`.claude/skills/`](.claude/skills): hướng dẫn và quy trình vận hành cho Claude (đăng quiz, đăng bài tập, tạo kỳ thi, sao lưu, deploy...).

## Cài đặt

Làm theo [tài liệu cài đặt VNOJ](https://vnoi-admin.github.io/vnoj-docs/#/site/installation), nhưng clone repo này thay vì repo của DMOJ. Một số điểm cần nhớ:

- Phải đặt `DMOJ_PROBLEM_DATA_ROOT` trong `dmoj/local_settings.py` (thư mục chứa dữ liệu test của các bài).
- Dùng cache `redis` hoặc `memcached` thay cho cache trong bộ nhớ mặc định, để judge và site đồng bộ cache.
- Bật quiz bằng `QUIZ_ENABLED = True`. Sau khi cập nhật code, chạy `manage.py migrate` (migration của CBNoj là `0244`–`0256`).
- Hỗ trợ `testlib.h`: chép [testlib.h](https://github.com/MikeMirzayanov/testlib/blob/master/testlib.h) vào đường dẫn include của `g++` trên máy judge.
- Cấu hình riêng của site (`dmoj/local_settings.py`, `uwsgi.ini`) chứa bí mật và **không** nằm trong repo.

## Đóng góp

Xem [contributing.md](contributing.md). Trước khi gửi thay đổi, kiểm tra code Python bằng [flake8](https://flake8.pycqa.org/en/latest/); code JS trong `websocket/` dùng `prettier`.

## Ghi công

Dựa trên công sức của đội ngũ [DMOJ](https://dmoj.ca) và [VNOJ](https://oj.vnoi.info).
