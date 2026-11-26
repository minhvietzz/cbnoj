# Hướng dẫn giáo viên: đăng quiz, bài viết, bài code lên CBNoj bằng Gemini

Với cách này bạn nhắn cho Gemini bằng tiếng Việt, ví dụ "đăng đề này lên CBNoj", và Gemini tự thao tác trên trang https://chuyenbacninh.io.vn bằng tài khoản của bạn. Bạn không phải chép từng câu vào trang web.

Mọi thứ Gemini tạo ra đều ở chế độ **riêng tư / bản nháp**. Chỉ bạn thấy cho đến khi bạn tự bấm công khai trên web.

## Bạn cần có
- **Tài khoản CBNoj có quyền giáo viên.** Nếu chưa có, nhờ quản trị viên cấp. Tài khoản học sinh không dùng được.
- **Tài khoản Google cá nhân** (đuôi @gmail.com). Theo trang trợ giúp của Google, tính năng "máy chủ MCP tùy chỉnh" của Gemini có thể không bật cho tài khoản Google Workspace của trường.
- Gemini bản có mục kết nối máy chủ MCP. Nếu bạn không thấy mục này trong Gemini thì chưa dùng được. Đây là điều kiện từ phía Google, không phải lỗi của CBNoj.

## Kết nối (làm một lần, khoảng 2 phút)
1. Mở Gemini, vào **Cài đặt**, tìm mục kết nối ứng dụng (Trình kết nối) và chọn **Kết nối với máy chủ MCP / Thêm máy chủ MCP**. Tên menu có thể khác một chút tùy phiên bản.
2. Điền:
   - **Tên:** `CBNoj` (tùy bạn).
   - **URL máy chủ:** `https://chuyenbacninh.io.vn/mcp`
   - Để trống ô Client ID / Client Secret (nếu có). Không cần điền.
3. Bấm kết nối. Gemini mở trang đăng nhập của CBNoj. Hãy **đăng nhập bằng tài khoản CBNoj của bạn**.
4. Trang "Cho phép Gemini truy cập tài khoản CBNoj" hiện ra. Đọc rồi bấm **Cho phép**.
5. Gemini báo kết nối thành công. Mở một cuộc trò chuyện mới và gõ: `Dùng CBNoj, cho tôi biết tôi là ai và được làm gì`. Gemini sẽ gọi `whoami` và nêu tên tài khoản cùng các quyền của bạn.

Không cần nhập lại sau đó. Phiên đăng nhập tự gia hạn. Nếu một lúc nào đó Gemini báo hết hạn, chỉ cần kết nối lại bằng bước 3 và 4.

**Muốn ngắt kết nối:** xóa kết nối trong Cài đặt của Gemini. Quản trị viên cũng có thể thu hồi quyền của bạn bất cứ lúc nào.

## Gemini làm được gì
| Việc | Gemini dùng tool | Ghi chú |
|---|---|---|
| Xem mình có quyền gì | `whoami` | Luôn nên gọi đầu tiên |
| Đăng quiz trắc nghiệm | `quiz_format_help`, `quiz_preview`, `quiz_create` | Xem trước rồi mới lưu |
| Cấu hình bài thi (giờ mở/đóng, giám sát, rút N câu...) | `quiz_configure` | Giờ theo giờ Việt Nam |
| Xem quiz của mình, xem kết quả | `quiz_list_mine`, `quiz_results` | Chỉ quiz do bạn quản lý |
| Đăng bài viết / thông báo | `blog_create`, `blog_update`, `blog_list_mine` | Mặc định là bản nháp |
| Đăng bài code có test | `problem_create`, `problem_set_tests`, `problem_update` | Bài riêng tư |
| Kiểm tra test bằng lời giải mẫu | `problem_submit_check`, `problem_check_result` | Chấm bằng máy chấm thật |

Bạn không cần nhớ tên tool. Chỉ cần nói việc bạn muốn làm.

## Mẫu câu lệnh

**Đăng quiz từ đề có sẵn** (dán nội dung đề vào khung chat, hoặc đính kèm ảnh/PDF để Gemini đọc):
> Dùng CBNoj, đăng đề này thành quiz tên "Kiểm tra 15 phút Chương 1 - Tin học 10". Thời gian làm bài 15 phút, xáo thứ tự câu hỏi. Hãy xem trước và cho tôi kiểm tra rồi mới lưu.

**Đặt quiz thành bài thi:**
> Đặt quiz "Kiểm tra 15 phút Chương 1" thành bài thi: chỉ được làm 1 lần, giám sát nghiêm, mở lúc 20:00 ngày 02/12/2026 và đóng lúc 20:30 cùng ngày, rút ngẫu nhiên 20 câu mỗi bài.

**Đăng bài viết:**
> Viết bản nháp bài thông báo "Lịch thi học kỳ I" với nội dung sau: ... Cho tôi xem link bản nháp, tôi sẽ tự đăng.

**Đăng bài code có test:**
> Tạo bài code mã `tong_hai_so`, tên "Tổng hai số", giới hạn 1 giây và 256 MB. Đề: nhập hai số nguyên a, b, in ra a + b. Thêm 5 test, gồm cả số âm và số lớn. Sau đó nộp thử lời giải Python này để kiểm tra chấm đúng: ...

**Xem kết quả:**
> Cho tôi xem kết quả quiz "Kiểm tra 15 phút Chương 1": điểm trung bình và những câu sai nhiều nhất.

## Nhờ Gemini sinh test cho bài code (tùy chọn)
Với bài đơn giản (nhập mảng, chuỗi, cây, đồ thị, nhiều bộ test...) bạn có thể nhờ Gemini sinh test ngẫu nhiên. Bạn **không cần gửi mã sinh test**: Gemini chọn kiểu dữ liệu và tham số, CBNoj tự sinh input rồi chạy **lời giải mẫu** của bạn để lấy output.
> Tạo bài "Tổng mảng" mã `tongmang`: dòng 1 là n (1 ≤ n ≤ 100000), dòng 2 là n số nguyên trong [-10^9, 10^9], in tổng. Sinh test: 4 test nhỏ (n từ 1 đến 6, 40 điểm) và 4 test lớn (n = 100000, 60 điểm). Đây là lời giải mẫu C++ (dán vào) và đây là lời giải vét cạn Python (dán vào) để so sánh.

Lưu ý:
- Nên đưa thêm **lời giải vét cạn** đơn giản: nếu hai lời giải cho kết quả khác nhau ở các test nhỏ thì hệ thống **không lưu test nào** và báo test lệch.
- Lời giải mẫu phải đúng và đủ nhanh (giới hạn thời gian của bài, tối đa 5 giây). Hiện chạy được C, C++, Python, Pascal, Java.
- Tối đa 30 test mỗi lần, tối đa 5 lần sinh mỗi giờ; mỗi test tối đa vài trăm nghìn số/cạnh và 4 MB.
- Bài không mô tả được bằng các kiểu có sẵn (cần đảm bảo có nghiệm, cấu trúc đặc biệt, nhiều đáp án đúng cần checker riêng) thì Gemini sẽ báo "không sinh được" và bạn tải test tay ở trang `test_data`.
- Nếu máy chấm đang bận, hệ thống từ chối và bạn thử lại sau vài phút.
- Sinh xong, hãy nhờ Gemini "nộp thử lời giải mẫu" để xác nhận chấm đúng, và liếc qua vài test trước khi công khai bài.

## Cú pháp đề trắc nghiệm
Nếu bạn dán đề thô, Gemini tự chuyển sang cú pháp CBNoj. Nếu muốn tự viết, cú pháp cơ bản như sau (Gemini cũng có thể in lại bản đầy đủ qua `quiz_format_help`):
```
[qus] Thủ đô của Việt Nam là gì?
[ans] Hà Nội
[ans] Huế
[ans] Đà Nẵng
[exp] Hà Nội là thủ đô của Việt Nam.
```
Đáp án đúng được đánh dấu theo cú pháp mà `quiz_format_help` mô tả. Ngoài chọn một đáp án, hệ thống còn có nhiều đáp án, trả lời ngắn và đúng/sai 4 ý. Tự luận chưa hỗ trợ.

## Giới hạn cần biết
- **Gemini có thể không nhận được file.** Nếu Gemini không đọc được file bạn đính kèm, hãy dán nội dung dạng chữ vào khung chat. Với đề dạng ảnh hoặc PDF scan, Gemini phải tự đọc rồi gõ lại. **Luôn xem phần xem trước** (số câu, đáp án Gemini hiểu) trước khi cho lưu, vì Gemini có thể đọc nhầm đáp án hoặc công thức.
- **Quiz không tự công khai.** Muốn mọi người thấy, bạn vào trang quiz và quản lý trên web.
- **Bài code: test dạng chữ, tối đa khoảng 50 test và 800 KB.** Test lớn hơn hoặc có file zip sẵn thì tải trực tiếp ở trang `https://chuyenbacninh.io.vn/problem/<mã bài>/test_data`.
- **Bài code cần thêm quyền:** tạo bài cần cả quyền tạo bài lẫn quyền sửa bài của mình. Nếu Gemini báo thiếu quyền, nhờ quản trị viên cấp. Tạo bài trong một tổ chức thì mã bài phải bắt đầu bằng `<mã tổ chức>_`.
- **Bài viết cá nhân** cần bạn đã giải đủ số bài theo quy định của trang (mặc định 10 bài) như khi đăng trên web. Bài viết của tổ chức thì bạn phải là quản trị tổ chức.
- Giới hạn 60 lệnh mỗi phút cho mỗi tài khoản. Gemini không chạm tới giới hạn khi dùng bình thường.
- Gemini không xóa được bài, không đổi quyền, không đăng công khai hàng loạt.

## Lỗi thường gặp
| Hiện tượng | Nguyên nhân và cách xử lý |
|---|---|
| Không thấy mục thêm máy chủ MCP trong Gemini | Tính năng chưa bật cho tài khoản/vùng của bạn. Thử tài khoản Google cá nhân, hoặc hỏi lại sau. |
| Máy chủ từ chối URL chuyển hướng của Google | Báo quản trị viên: cấu hình `MCP_ALLOWED_REDIRECT_PREFIXES` chưa có địa chỉ chuyển hướng mới của Google. |
| Báo 403 / "tài khoản không có quyền giáo viên" | Tài khoản của bạn chưa được cấp quyền. Nhờ quản trị viên cấp. |
| Báo "không có quyền" khi tạo bài code / bài viết | Thiếu quyền riêng của chức năng đó (xem mục Giới hạn). |
| "Bạn đã gửi quá nhiều yêu cầu" | Chờ 1 phút rồi nhắn tiếp. |
| Quiz có đáp án sai | Gemini đọc nhầm từ đề. Nhờ Gemini sửa, hoặc vào trang quản lý quiz để sửa. Bạn nên luôn kiểm tra bản xem trước. |
| Bài nộp thử "đang chấm" mãi | Nhờ Gemini kiểm tra lại sau vài giây. Nếu quá 1 phút, báo quản trị viên kiểm tra máy chấm. |
| Gemini báo hết phiên đăng nhập | Kết nối lại theo bước 3 và 4 ở trên. |

## Dành cho quản trị viên
Cấu hình, nhật ký kiểm toán, cách tắt khẩn cấp và thu hồi quyền nằm ở mục **14A** của `docs/HE-THONG.md`.
