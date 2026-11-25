# Dự án nâng cấp phần trắc nghiệm CBNoj ("Trung tâm thi")

Ngày lập: 2026-11-22, **sửa lần 3 cùng ngày** sau khi có thêm ảnh chụp video. Tham chiếu: phần mềm **ExamJudge Pro** (tác giả Tô Hưng).

## 0. Nguồn và giới hạn (đọc trước)

- Nguồn: caption video và **9 ảnh chụp màn hình video (hai đợt)** do bạn gửi (giới thiệu, nạp mã đề PDF, phát đề ngẫu nhiên, "mỗi em một đề", thi trên điện thoại). Tôi chưa xem video đầy đủ và chưa chạy thử phần mềm; chữ nhỏ trong ảnh (nhất là bảng đáp án) có chỗ không đọc chắc được, đã ghi rõ ở dưới.
- Đây là phần mềm có bản quyền của người khác. Dự án này **tự thiết kế và tự viết**; không sao chép mã, giao diện hay tài nguyên của họ.

## 1. Phát hiện quan trọng từ ảnh: họ KHÔNG tách đề PDF thành câu hỏi

Bản kế hoạch đầu của tôi giả định phải "đọc PDF rồi tách từng câu" (rất khó, dễ sai công thức). Ảnh cho thấy **họ làm khác và đơn giản hơn nhiều**:

1. Giáo viên nạp **nhiều tệp PDF**, mỗi tệp một mã đề; **mã đề lấy từ tên tệp** (`0101.pdf`, `0102.pdf`…).
2. Nạp **một tệp Excel chứa đáp án của mọi mã đề** (mỗi mã một dòng; cột theo phần I / II / III; có kiểm tra "đủ 22 câu mỗi mã", thống kê phân bố đáp án A/B/C/D để phát hiện đáp án lệch).
3. **PDF được chuyển thành ảnh từng trang**; máy thí sinh **chỉ nhận ảnh của đúng mã đề của em đó, có in mờ số báo danh, không nhận tệp PDF** (chống chép/gửi đề).
4. Học sinh **đọc đề trên ảnh và trả lời ở "phiếu trả lời"** riêng (bấm A/B/C/D, điền đúng/sai, nhập đáp án ngắn) — giống tô phiếu giấy.
5. Chấm tự động bằng file đáp án; thống kê "gộp theo câu gốc" giữa các mã (cách họ biết câu nào tương ứng câu nào giữa các mã: **chưa rõ**).

Hệ quả: tính năng cốt lõi là **"thi bằng đề PDF + phiếu trả lời"**, không cần nhận dạng nội dung PDF, đề có công thức/hình vẫn đúng 100% vì chỉ là ảnh. Đây cũng chính là cách giáo viên đang làm đề (trộn mã đề bằng Word/công cụ khác rồi xuất PDF).

Các điểm khác thấy trong ảnh:
- **Sơ đồ phòng thi** (lưới, ví dụ 8 máy/hàng, 40 thí sinh, 4 mã): *trái, phải, trước, sau khác mã*, mỗi mã chia đều (10 em/mã), nút **"Bốc lại"**; mã được bốc trước giờ thi và giữ nguyên.
- **Thẻ dự thi** in 10 thẻ/trang A4: họ tên, SBD, lớp, phòng, máy, **mã đăng nhập 6 ký tự** (bỏ chữ dễ nhầm O/I với số 0/1) và **mã QR** mở thẳng trang thi trên điện thoại. Học sinh **vào thi bằng mã trên thẻ**, không cần tài khoản.
- **Quy trình 5 bước**: Thông tin → Đề thi PDF → Đáp án → Thí sinh → Phát đề, in thẻ. Thanh bên: Các kỳ thi, Tạo kỳ thi, Giám sát, Xếp hạng trực tiếp, Kết quả thống kê, **Thu bài, đóng gói**.
- **Hai chế độ kết nối**: LAN (máy giám khảo làm máy chủ) và Internet qua đường link; có nhãn trạng thái "Sẵn sàng / LAN".
- **Giao diện điện thoại**: nhập mã thẻ; nút **thử loa** (giọng nói "Chúc em làm bài tốt"); cảnh báo rằng thoát ra ngoài hoặc mở app khác sẽ bị ghi vi phạm; trong bài: đồng hồ, tiến độ "1/22 câu", ảnh đề, hàng nút A B C D, **trước/sau**, **Bảng câu hỏi** (Phần I 12 câu, Phần II 4 câu, Phần III 6 câu; trạng thái đã làm / làm dở / đánh dấu), nút **Đánh dấu câu này**, **Xem phiếu**, nút Nộp.
- Đề mẫu 22 câu: 12 trắc nghiệm (0,25 điểm/câu) + 4 đúng/sai + 6 trả lời ngắn = đúng **cấu trúc đề tốt nghiệp THPT 2025**.

### 1b. Bổ sung từ 4 ảnh đợt hai (khóa máy, giám sát trực tiếp, chấm điểm, xuất báo cáo)

- **Phiếu trả lời mô phỏng phiếu tô của Bộ GD&ĐT 2025** (trên máy tính): ô tròn A/B/C/D để tô, bấm lại để bỏ; ô số báo danh và mã đề; phần III có ô "ghi nhanh". Thanh trên cùng: họ tên, SBD, lớp, máy, mã đề, **"Đã làm 3/22"**, **"Đã lưu hh:mm:ss"**, đồng hồ, nút Nộp bài.
- **Cảnh báo vi phạm**: hộp thoại "VI PHẠM LẦN 1/3 – Em vừa rời khỏi cửa sổ bài thi", **đọc thành tiếng** cùng nội dung, nói rõ "giám thị đã nhận được thông báo, bài làm vẫn được giữ nguyên", nút "Em đã hiểu". Tiêu đề màn hình nói thêm bắt cả **cắm USB** và **mở ứng dụng lạ**. *Ghi chú giới hạn:* trình duyệt web **không** phát hiện được USB hay ứng dụng khác đang chạy; việc đó chỉ làm được bằng phần mềm cài trên máy. Trên web chỉ phát hiện rời tab/cửa sổ, mất tiêu điểm, thoát toàn màn hình (CBNoj đã có).
- **Giám sát trực tiếp**: bốn thẻ số liệu (đã vào thi 38/40, số câu làm trung bình 7/22, số em đang vi phạm, số em mất kết nối, đã nộp); **lưới từng máy xếp theo số máy**, mỗi ô là **hình thu nhỏ phiếu trả lời đang làm** của em đó, kèm mã đề, số câu đã làm, trạng thái mạng; bộ lọc **Tất cả / Vi phạm / Mất kết nối / Làm chậm / Đã nộp / Vắng**; bảng **Điều khiển kỳ thi**: còn lại hh:mm, "Kết thúc kỳ thi, thu bài tất cả", **đường link vào thi + nút sao chép**, **"Mã thoát hôm nay"** (giám thị nhập mã để cho một em ra ngoài mà không tính vi phạm), **luồng thông báo** ("Máy 40 – Phạm Đức Bảo đã vào phòng thi (điện thoại)"); **nhắn tin cả phòng**, **cộng giờ từng em**.
- **Kết quả**: ghi "Kết quả chính thức · 40 bài · phiên bản 1 · **0 bài đã kiểm tra chữ ký số**" (tức mỗi bài nộp được ký để phát hiện sửa điểm sau khi thi); nút **Xuất Excel (có biểu đồ)**, **Xuất PDF A4**, **Phiếu cả lớp (PDF)**, **Công bố cho học sinh**. Thẻ điểm trung bình / trung vị / cao nhất. **Phổ điểm** (cột theo khoảng 0,5 điểm, vạch điểm trung bình); **xếp loại theo lớp** (thanh chồng Giỏi/Khá/Trung bình/Yếu); **tỉ lệ đúng từng câu gốc** (I.1…III.6, theo mã câu gốc đã gộp giữa các mã); bảng **"Câu cần xem lại"** gồm % đúng, **độ phân biệt**, phân bố lựa chọn A/B/C/D, nhận xét tự động ("Câu khó – dưới 30% đúng", "15% ghi 0,5" cho câu đúng/sai). **Bảng điểm** cột: hạng, SBD, họ tên, lớp, phòng, máy, mã đề, điểm phần I/II/III, tổng, ghi chú ("làm trên điện thoại").
- **Báo cáo PDF đúng thể thức hành chính**: quốc hiệu và tiêu ngữ, tên trường, "Báo cáo kết quả thi…", ô tóm tắt (TB, trung vị, cao nhất, % từ 5,0 trở lên, số dự thi/vắng), biểu đồ, lặp tiêu đề mỗi trang, chỗ ký. Excel theo phòng.

So với CBNoj: **đã có** phổ điểm, độ phân biệt, % đúng từng câu, xuất Excel, `results_published` (công bố), cộng giờ/đặt lại/buộc nộp, trang giám sát trực tiếp cơ bản. **Chưa có**: lưới giám sát theo máy có thu nhỏ phiếu, bộ lọc trạng thái, nhắn tin cả phòng, mã thoát, đọc to cảnh báo, xếp loại theo lớp, nhận xét tự động cho câu, PDF đúng thể thức, phiếu cả lớp, ký/băm kết quả chống sửa điểm, ghi chú "làm trên điện thoại".

## 2. CBNoj đang ở đâu so với đó

| Chức năng | CBNoj hiện có | Khoảng cách |
|---|---|---|
| Thi bằng **đề PDF dạng ảnh + phiếu trả lời** | Không có. Quiz hiện là câu hỏi nhập sẵn dạng văn bản | **Lớn, làm mới** |
| **Mã đề** (0101…), phát mã cho thí sinh | Chỉ có rút N câu ngẫu nhiên theo seed, không có "mã đề" cố định in/đối chiếu được | **Lớn** |
| **Sơ đồ phòng thi**, ngồi cạnh khác mã, "Bốc lại" | Không có | **Lớn** |
| **Thẻ dự thi** (SBD, mã đăng nhập, QR), vào thi không cần tài khoản | Cần tài khoản CBNoj; có công cụ tạo tài khoản hàng loạt | Trung bình |
| Watermark SBD trên đề | Có chữ chìm trên màn hình (CSS), chưa in vào ảnh đề | Nhỏ-trung bình |
| Chấm theo đáp án, thang điểm 2025 (đúng/sai 0,1/0,25/0,5/1) | **Có** (`quiz_grading.TF4_LADDER`), `single/multi/short/tf4` | Không |
| Giám sát, tự nộp khi vi phạm, heartbeat, SEB | **Có** (11 loại vi phạm) | Thêm "thử loa/giọng nói" |
| Phổ điểm, phân tích câu, xuất Excel | **Có** (CSV/Excel, độ phân biệt) | Thiếu PDF, phiếu từng học sinh |
| Xếp hạng trực tiếp / giám sát trực tiếp | Có `QuizLive`, `results/live` | Chỉnh giao diện |
| Giao diện điện thoại cho bài thi | Chưa rà (chưa kiểm tra bằng thiết bị thật) | Trung bình |
| LAN không cần Internet | Không có | Chỉ khi cần (mục 6) |

Kết luận: phần chấm điểm, giám sát, báo cáo của CBNoj **đã tốt**. Thứ thiếu là một **chế độ thi mới "Đề PDF"** cùng quy trình phát đề/thẻ dự thi quanh nó.

## 3. Hướng đi

**A (khuyến nghị): thêm chế độ "Thi theo đề PDF" vào phần Quiz hiện có**, dùng lại chấm điểm, giám sát, thông báo, báo cáo, tài khoản, backup. Không viết lại site.
**B: bản LAN độc lập** — chỉ sau A và chỉ khi trường có phòng máy mất Internet (mục 6).

## 4. Các gói công việc

### GĐ1. Chế độ đề PDF: nạp, đáp án, làm bài (3 tuần) — lõi
- **Nạp PDF** nhiều tệp, mã đề lấy từ tên tệp (có thể sửa). Chuyển mỗi trang thành ảnh một lần lúc nạp, lưu ngoài web root (không ai tải trực tiếp được).
  - **Cần thư viện dựng PDF thành ảnh**. Máy chủ hiện **chưa có** (`pdftoppm`/`pdftotext`/PyMuPDF đều không có). Đề nghị `pypdfium2` (cài bằng pip vào venv của site, không cần gói hệ thống) — **cần bạn cho phép cài**.
- **Nạp Excel đáp án** (mẫu tải về): mỗi mã một dòng; kiểm tra đủ số câu từng phần, báo ô sai định dạng, hiện phân bố A/B/C/D từng mã. Cấu trúc câu từng phần (ví dụ 12 + 4 + 6 và điểm từng phần) là cấu hình của kỳ thi.
- **Phục vụ ảnh theo thí sinh**: server ghép ảnh trang + **in mờ SBD/họ tên** bằng Pillow (đã có), lưu đệm theo thí sinh, chỉ phục vụ cho đúng lượt làm đang hợp lệ, header chống lưu đệm; không có đường dẫn PDF gốc cho học sinh.
- **Giao diện làm bài** (ưu tiên điện thoại): ảnh đề phóng to/thu nhỏ, hàng nút đáp án, trước/sau, bảng câu hỏi theo phần, đánh dấu câu, xem phiếu, đồng hồ, nộp. Tự lưu từng câu.
- **Chấm**: dùng `quiz_grading` hiện có; thêm loại "phiếu" gắn với mã đề của lượt làm.
- **Nghiệm thu**: kỳ thi thử 4 mã × 22 câu, 40 tài khoản thử; điểm khớp bảng tay 100%; ảnh tải về của em A có SBD của A; em B không lấy được ảnh của A (thử trực tiếp bằng URL).

### GĐ2. Phát mã và phòng thi (2 tuần)
- `ExamRoom` (lưới hàng × cột), `ExamSeat` (chỗ ↔ thí sinh ↔ SBD ↔ mã đề).
- **Thuật toán phát**: chia mã đều (±1), **trái/phải/trước/sau khác mã** (bài toán tô màu đồ thị lưới; với ≥ 2 mã luôn giải được trên lưới, kiểm tra bằng test), nút "Bốc lại", **khóa sau khi mở kỳ thi**.
- Nhập danh sách thí sinh từ Excel/CSV (SBD, họ tên, lớp, phòng).
- **Nghiệm thu**: 3 phòng, 40/32/24 chỗ, 2–6 mã: mọi cặp kề khác mã, chênh lệch số em mỗi mã ≤ 1; chạy 1000 lần ngẫu nhiên không vi phạm.

### GĐ3. Thẻ dự thi và vào thi bằng mã (1,5 tuần)
- Sinh **mã đăng nhập 6 ký tự** từ bảng chữ bỏ O/I/0/1, chống đoán (giới hạn thử sai theo IP và theo mã), **mã QR** ra trang thi.
- In 10 thẻ/trang A4 (PDF, cần thư viện tạo PDF; chọn khi làm) và danh sách phòng.
- Cho phép thí sinh **không có tài khoản CBNoj** (tài khoản tạm gắn kỳ thi) *hoặc* dùng tài khoản có sẵn; chọn theo kỳ thi.
- **Rủi ro quyền riêng tư**: SBD/họ tên/lớp của học sinh; chỉ giáo viên thấy; cập nhật trang Chính sách quyền riêng tư.

### GĐ4. Giám sát trực tiếp, cảnh báo, độ tin cậy (2,5 tuần)
- **Phiếu trả lời** trên màn hình (mô phỏng phiếu tô Bộ GD&ĐT: ô tròn, bấm lại để bỏ, phần III có ô nhập), thanh "Đã làm x/22", "Đã lưu hh:mm:ss"; tự lưu từng câu, **tiếp tục khi mất mạng ngắn**.
- **Hộp thoại vi phạm** "Lần x/N" + **đọc thành tiếng tiếng Việt** (`speechSynthesis`; có chữ và âm báo dự phòng nếu máy không có giọng) + nút "Em đã hiểu". Màn hình vào thi có **thử loa**.
- **Giám sát trực tiếp** (nâng cấp `QuizLive`): thẻ số liệu, **lưới từng thí sinh** (thu nhỏ phiếu đang làm, số câu, mạng, mã đề), bộ lọc Tất cả/Vi phạm/Mất kết nối/Làm chậm/Đã nộp/Vắng, luồng thông báo, **nhắn tin cả phòng**, cộng giờ từng em, buộc nộp, **mã thoát** của giám thị, nút "Kết thúc kỳ thi, thu bài tất cả".
- Thí sinh trên **điện thoại không khóa được màn hình**: chỉ ghi nhận rời trang/mất tiêu điểm, ghi chú "làm trên điện thoại" vào bảng điểm. Việc **cắm USB / mở ứng dụng lạ** web **không phát hiện được**; nếu cần phải làm phần mềm cài trên máy (ngoài phạm vi dự án này; có thể kết hợp Safe Exam Browser đã hỗ trợ).
- **Kiểm thử tải** (`scripts/quiz_loadtest.py`) 200 và 400 thí sinh; đo riêng phần phục vụ ảnh và **làm mới lưới giám sát** (thu nhỏ phiếu cho 400 em là tải lớn, cân nhắc chỉ gửi trạng thái chữ và thu nhỏ khi giám thị bấm vào). Máy hiện 4 nhân, RAM 7,9 GB; **chưa có số đo**.
- **Nghiệm thu**: mô phỏng 40 em, 5 em rời tab, 3 em mất mạng: giám thị thấy đúng trong 15 giây; nhắn tin cả phòng đến mọi máy trong 5 giây.

### GĐ5. Kết quả, báo cáo, đóng gói (2,5 tuần)
- **Kết quả chính thức có phiên bản**; mỗi bài nộp được **ký bằng HMAC** (khóa bí mật của site) để phát hiện sửa điểm trực tiếp trong DB; nút "Kiểm tra chữ ký" báo số bài hợp lệ. (Đây là chống sửa nhầm/sửa lén, không phải chữ ký số pháp lý.)
- **Thống kê**: giữ phổ điểm, độ phân biệt, xuất Excel đã có; thêm **xếp loại theo lớp**, % đúng theo **câu gốc** (cột "mã câu gốc" trong Excel mẫu để gộp giữa các mã), bảng "Câu cần xem lại" có **nhận xét tự động** (dưới 30% đúng, phân bố lựa chọn lệch, % em ghi 0,5 ở câu đúng/sai).
- **Báo cáo PDF A4 đúng thể thức**: quốc hiệu–tiêu ngữ, tên trường (cấu hình), ô tóm tắt, biểu đồ, lặp tiêu đề mỗi trang, chỗ ký; **Excel có biểu đồ**, tách theo phòng; **Phiếu cả lớp (PDF)**: mỗi em một trang (đáp án chọn / đáp án đúng / điểm từng phần).
- **Công bố cho học sinh** (đã có `results_published`) và thông báo chuông (đã có).
- **Thu bài, đóng gói**: một tệp nén lưu trữ (điểm, bài làm, nhật ký vi phạm, ảnh đề đã dùng).
- **Cần thư viện tạo PDF/biểu đồ**: chưa có trên máy chủ, chọn khi làm và xin phép cài. PDF tiếng Việt phải nhúng phông có dấu.
- **Nghiệm thu**: PDF 200 học sinh dưới 30 giây, đủ dấu tiếng Việt; sửa một điểm trong DB thì kiểm tra chữ ký báo sai đúng bài đó.

### GĐ6. Trung tâm thi (1,5 tuần)
Một trang cho giáo viên theo thứ tự thật của công việc (giống thanh bên và 5 bước họ dùng, nhưng thiết kế riêng): **Thông tin → Đề PDF → Đáp án → Thí sinh → Phát đề & in thẻ → Giám sát → Kết quả**. Vẽ bản mẫu trước (như đã làm với đăng nhập), duyệt rồi mới làm.

## 5. Lịch và thứ tự

Khoảng **12–13 tuần** nếu một người làm tuần tự: GĐ1 → GĐ2 → GĐ3 → GĐ4 → GĐ5 → GĐ6 (GĐ4 và GĐ5 đã tăng vì thêm giám sát lưới và báo cáo đúng thể thức). Có thể **dùng được sớm sau GĐ1+2** (khoảng 5 tuần đầu có sản phẩm chạy thử): thi bằng đề PDF, phát mã, chấm tự động. Mỗi giai đoạn triển khai riêng, **không migrate/restart khi có kỳ thi đang chạy**.

## 6. LAN / không Internet (chỉ khi cần)

Ảnh cho thấy họ có chế độ LAN vì chạy trên một máy tính của giáo viên. CBNoj chạy trên máy chủ Internet nên mặc định **không cần LAN**. Nếu có phòng máy không có Internet: đóng gói bản Quiz rút gọn (Docker hoặc script cài) chạy trên một máy trong phòng; kết quả xuất file rồi nhập về site chính. Ước tính 3–4 tuần, **chỉ làm khi bạn xác nhận có nhu cầu**.

## 7. Rủi ro

| Rủi ro | Cách giảm |
|---|---|
| Lộ đề (chụp màn hình, quay điện thoại) | Watermark SBD trong ảnh, mã đề khác nhau, giám thị; không ngăn được tuyệt đối |
| Quá tải khi 400 em tải ảnh cùng lúc | Dựng ảnh một lần, đệm theo thí sinh, nén WebP/JPEG; đo trước (GĐ4); có thể thêm Cloudflare cache cho ảnh *không* chứa SBD (phần nền) — chưa chắc làm được vì SBD in vào ảnh |
| Chấm sai do nhầm đáp án Excel | Kiểm tra định dạng, hiện phân bố đáp án, **chấm thử bằng bài làm giả** trước khi mở thi |
| Mã đăng nhập bị đoán | 6 ký tự không nhầm lẫn, giới hạn thử sai, hết hạn sau kỳ thi |
| Phá bài thi đang chạy khi triển khai | Migration lùi được, thử trên DB tạm, chỉ triển khai khi không có kỳ thi |
| Sao chép sản phẩm có bản quyền | Chỉ học ý tưởng quy trình; tự viết toàn bộ |

## 8. Việc cần bạn quyết định

1. **Đề của trường có sẵn dạng PDF theo mã đề không?** (Nếu có, chế độ "Đề PDF" là đúng hướng. Nếu giáo viên chỉ có Word/văn bản thì tiếp tục dùng quiz hiện có, vẫn rút câu ngẫu nhiên được.)
2. **Học sinh có tài khoản CBNoj sẵn không?** (quyết định có làm "vào thi bằng mã thẻ" ngay hay dùng tài khoản trước.)
3. Kỳ thi lớn nhất **bao nhiêu thí sinh cùng lúc**?
4. Có **phòng máy không Internet** khi thi không?
5. Có cho **cài `pypdfium2`** (thư viện Python dựng PDF thành ảnh) vào môi trường của site không?
6. Bắt đầu từ GĐ1? Mình đề nghị vẽ trước bản thiết kế màn **"Tạo kỳ thi 5 bước"**, **"Sơ đồ phòng"** và **"Làm bài trên điện thoại"** để bạn duyệt.
