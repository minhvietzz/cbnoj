# CBNoj: Chuyên Bắc Ninh Online Judge

Trang chấm bài lập trình và thi trắc nghiệm của trường THPT chuyên Bắc Ninh, chạy tại <https://chuyenbacninh.io.vn>.

CBNoj là fork của [VNOJ](https://github.com/VNOI-Admin/OJ) (bản thân VNOJ là fork của [DMOJ](https://github.com/DMOJ/online-judge)), dựa trên commit upstream `bc50e417b`. Mã nguồn theo giấy phép [AGPL-3.0](LICENSE).

## Điểm nổi bật

### Giáo viên đăng bài bằng trợ lý AI (MCP)
Máy chủ [MCP](https://modelcontextprotocol.io) tích hợp sẵn tại `/mcp`: giáo viên kết nối Gemini hoặc Claude, đăng nhập bằng OAuth 2.1 (PKCE), rồi chỉ cần nói chuyện để:
- đăng **quiz** từ đề có sẵn (xem trước, cấu hình giờ thi, giám sát, rút câu, xem kết quả);
- đăng **bài viết**, mặc định ở dạng nháp;
- đăng **bài code**: tạo đề, đặt test, **sinh test tự động** bằng các khối dựng sẵn (cây, đồ thị, hoán vị, ma trận...) rồi **nộp thử lời giải mẫu** để judge thật chấm xác nhận.

Mọi nội dung tạo ra mặc định riêng tư, quyền kiểm tra như trên web, có giới hạn tốc độ và nhật ký kiểm toán. Mã ở `judge/mcp/`.

### Thi trắc nghiệm
- 4 loại câu: một đáp án, nhiều đáp án, trả lời ngắn, đúng/sai 4 ý.
- Rút ngẫu nhiên N câu mỗi bài, **sinh nhiều mã đề** (xáo câu và đáp án, bản in và đáp án), tạo đề theo ma trận từ **ngân hàng câu hỏi**.
- Giám sát khi thi (toàn màn hình, đếm vi phạm, tự nộp), watermark chống chụp màn hình, công bố điểm theo thời điểm.
- Phân tích câu hỏi (độ khó, độ phân biệt), xuất Excel/CSV.

### Lớp học và khóa học
- **Lớp** và **môn** trong tổ chức, vai trò học sinh/trợ giảng/giáo viên/chủ nhiệm, bảng điểm và xếp hạng của lớp, thông báo.
- **Khóa học** gồm các bài học, mỗi bài có lý thuyết, bài tập code và quiz; có điều kiện mở khóa bài sau. Khóa học thuộc về tổ chức.
- **Giao bài** cho lớp, có hạn nộp: một số bài tập, một quiz, hoặc cả một bài học; tiến độ tính tự động.

### Chấm bài và kỳ thi lập trình
- **Phát hiện bài giống nhau** ngay trong kỳ thi (so sánh cấu trúc code, chạy trên máy chủ, không gửi mã ra ngoài).
- **Chạy thử** ngay trên trang đề bài (không chấm điểm).
- **Gợi ý lỗi biên dịch bằng tiếng Việt**, kể cả khi chọn nhầm ngôn ngữ.
- Vá lỗ hổng đọc dữ liệu test của trình chấm (race giữa các luồng) bằng AppArmor.

### Giao diện và vận hành
- Giao diện "giấy ấm" (sáng/tối), nhãn Giáo viên/Quản trị bên cạnh tên người dùng, hồ sơ thiết kế lại.
- Cloudflare Turnstile ở trang đăng nhập, email gửi nền qua celery, trang trạng thái máy chủ `/server-status/`.
- Sao lưu tự động hằng đêm, bản dịch tiếng Việt bổ sung.

## Tài liệu

- `docs/HE-THONG.md`: tài liệu vận hành nội bộ (đường dẫn, dịch vụ, nhật ký). Không đưa lên repo công khai; nằm trên máy chủ.
- [`CLAUDE.md`](CLAUDE.md) và [`.claude/skills/`](.claude/skills): hướng dẫn và quy trình vận hành cho Claude (đăng quiz, đăng bài tập, tạo kỳ thi, sao lưu, deploy...).

## Cài đặt

Làm theo [tài liệu cài đặt VNOJ](https://vnoi-admin.github.io/vnoj-docs/#/site/installation), nhưng clone repo này thay vì repo của DMOJ. Một số điểm cần nhớ:

- Phải đặt `DMOJ_PROBLEM_DATA_ROOT` trong `dmoj/local_settings.py` (thư mục chứa dữ liệu test của các bài).
- Dùng cache `redis` hoặc `memcached` thay cho cache trong bộ nhớ mặc định, để judge và site đồng bộ cache.
- Bật quiz bằng `QUIZ_ENABLED = True`. Sau khi cập nhật code, chạy `manage.py migrate` (migration của CBNoj là `0244`–`0259`).
- Hỗ trợ `testlib.h`: chép [testlib.h](https://github.com/MikeMirzayanov/testlib/blob/master/testlib.h) vào đường dẫn include của `g++` trên máy judge.
- Cấu hình riêng của site (`dmoj/local_settings.py`, `uwsgi.ini`) chứa bí mật và **không** nằm trong repo.

## Đóng góp

Xem [contributing.md](contributing.md). Trước khi gửi thay đổi, kiểm tra code Python bằng [flake8](https://flake8.pycqa.org/en/latest/); code JS trong `websocket/` dùng `prettier`.

## Ghi công

Dựa trên công sức của đội ngũ [DMOJ](https://dmoj.ca) và [VNOJ](https://oj.vnoi.info).
