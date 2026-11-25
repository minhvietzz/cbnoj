# Dự án cải tạo CBNoj: Tổ chức – Lớp – Bài tập theo môn – Ôn luyện – Mã đề

Ngày lập: 2026-11-22. Đây là **kế hoạch**, chưa sửa code. Gộp và thay thế các phần liên quan của `docs/DU-AN-TRAC-NGHIEM.md` (phần thi LAN: **đã bỏ theo yêu cầu**).

## 0. Yêu cầu của bạn (tôi hiểu như sau — hãy sửa nếu sai)

1. **Ôn luyện dựa trên cơ sở dữ liệu đề thi** (ngân hàng câu hỏi).
2. **Đưa câu hỏi lên bằng PDF hoặc Word**; hệ thống **tự sinh n mã đề ngẫu nhiên** (n chỉnh được, sinh bằng cách xáo câu/đáp án) và **hiển thị dạng PDF** để giáo viên không còn phải làm mã đề.
3. **Thêm "Lớp" trong phần Tổ chức**: một lớp được quản lý như một lớp học thật; trong lớp có thể có **kỳ thi lập trình** và **bài thi trắc nghiệm**; hiện không quản lý lớp được nên phải đổi.
4. **Bài tập tách làm hai**: ① Bài tập lập trình, ② Bài tập trắc nghiệm; **phân theo môn** (môn Tin trước; trang trắc nghiệm trình bày giống trang bài lập trình).
5. **Giữ phần Khóa học.**
6. **Thanh điều hướng thêm "Tổ chức"**. Ví dụ tổ chức Chuyên Bắc Ninh có: **Thành viên**, **Danh sách kỳ thi** (chung cả tổ chức), **Lớp của tôi** (mỗi tài khoản được phân quyền, phân lớp).
7. **Thêm tính năng hay cho lớp** (xếp hạng, …) — theo đề xuất của tôi.

## 0b. Quyết định của chủ site (2026-11-22) — thay các câu hỏi ở mục 12

1. **Upstream VNOJ:** tách hẳn khỏi VNOJ; về sau có tính năng mới thì tự học theo, không gộp commit. (Bỏ rủi ro xung đột upstream; số migration tự đánh liên tục.)
2. **Danh sách lớp:** học sinh **tự tạo tài khoản như thường**, rồi điền vào một bảng (Google Sheet/Excel) để ghép lớp → cần công cụ **nhập danh sách ghép lớp** (khớp theo tên truy cập hoặc email, báo ai chưa có tài khoản).
3. **Môn học:** chưa chốt; cần **chức năng tạo môn** ngay trong giao diện quản trị (bảng `Subject`).
4. **Đề thử PDF:** dùng các đề PDF đã tải lên site.
5. **Cho cài** thư viện đọc/tạo PDF vào máy chủ.
6. **Xếp hạng lớp:** công khai.
7. **Thứ tự:** làm tất cả.
8. (Câu 8 chỉ hỏi có đợt nào muốn bỏ/hoãn không — trả lời "không" là làm hết.)

**Ràng buộc thêm:** phần OJ (khóa học lập trình, xếp hạng, học tập lập trình) **giữ nguyên**, site vẫn là một OJ. **Lớp** nằm trong tổ chức *hoặc* đứng riêng (không cần tổ chức); thanh trên có nút **"Lớp của tôi"** → bảng các lớp của tài khoản.

**Hệ quả cho thiết kế:** `Classroom.organization` cho phép rỗng; một lớp độc lập chỉ do quản trị site (hoặc người có quyền tạo lớp) quản lý. Mục 12 câu 1 và 6 coi như đã quyết.

## 1. Hiện trạng (đã kiểm tra trong mã nguồn và CSDL ngày 2026-11-22)

| Hạng mục | Hiện có | Hệ quả |
|---|---|---|
| Tổ chức | `Organization` (mô hình của VNOJ): trang riêng `/organization/<slug>`, thành viên, quản trị viên, mã tham gia, yêu cầu vào, thẻ bài riêng, **thanh điều hướng riêng khi đang ở trong tổ chức** (Bài tập / Bài nộp / Kỳ thi / Thành viên) | Có sẵn nền để mở rộng, **không viết lại** |
| Dữ liệu thật | **1 tổ chức** (CBNoj/`cbnoj`), nhưng **chỉ 5 thành viên trên 256 tài khoản**; 205 bài lập trình, 20 contest, 7 quiz, 2 khóa học | Phải **đưa học sinh vào tổ chức và vào lớp** (nhập danh sách), nếu không "Lớp của tôi" sẽ trống |
| Lớp | **Không có khái niệm lớp.** Gần nhất là `Course` (khóa học) có vai trò Học sinh/Trợ giảng/Giáo viên (`CourseRole`) | Cần mô hình mới, nhưng **không biến Course thành Lớp** (xem mục 3) |
| Contest | Có `organization` (một tổ chức) và `is_organization_private` | Chưa gắn được vào **lớp** |
| Quiz | Có `organizations` (nhiều), `course`, `track` | Chưa gắn được vào **lớp** và **môn** |
| Bài lập trình | `Problem` có `organization`, nhóm (`ProblemGroup`, 19 nhóm kiểu "chữ số, điều kiện, mảng…"), loại, thẻ | **Chưa có "môn"** |
| Ngân hàng câu hỏi | Có `BankQuestion/BankTag`, `/bank/`, nhập từ Word, luyện tập cá nhân (`/practice/`), **sổ lỗi** (`judge/utils/practice.py`), chuỗi ngày học (`streak.py`), thống kê chủ đề | **Ngân hàng đang trống: 0 câu hỏi** → việc đầu tiên là đổ đề cũ vào |
| Sinh mã đề / in PDF | Không có. Máy chủ **không có** Chromium, wkhtmltopdf, LaTeX, LibreOffice, `python-docx`, thư viện PDF | Xem mục 6: cần chọn cách tạo PDF |
| Điều hướng | Thanh trên **do cơ sở dữ liệu quản lý** (cây `nav_bar`), chỉnh được không cần sửa code | Đổi menu rẻ |
| Danh sách bài | `/problems/` một danh sách | Tách đôi như bạn muốn là thay đổi vừa phải |

**Hạn chế lớn của thiết kế hiện tại:** mọi thứ gắn vào "tổ chức" hoặc "khóa học", không có tầng giữa "lớp". Vì vậy không thể nói "lớp 10A1 có contest tuần này, bài trắc nghiệm này, và xem điểm cả lớp".

## 2. Mô hình đích (khái niệm)

```
Tổ chức (trường)            ← Organization (có sẵn)
 ├─ Thành viên (mọi người trong trường)
 ├─ Kỳ thi của tổ chức      ← contest/quiz dùng chung toàn trường
 ├─ Môn học (Tin, Toán…)    ← mới: Subject
 └─ Lớp (10A1, 11 Tin…)     ← mới: Classroom
     ├─ Thành viên lớp: Giáo viên chủ nhiệm / Giáo viên bộ môn / Trợ giảng / Học sinh
     ├─ Bài giao (lập trình, trắc nghiệm, có hạn nộp)
     ├─ Kỳ thi của lớp (contest lập trình, bài thi trắc nghiệm)
     ├─ Khóa học được gán cho lớp (Course có sẵn)
     └─ Xếp hạng, sổ điểm, chuyên cần, thông báo lớp
```

Một tài khoản có thể thuộc nhiều lớp (ví dụ lớp chính + đội tuyển) với **vai trò khác nhau ở từng lớp**.

## 3. Quyết định thiết kế quan trọng (và lý do)

1. **Lớp là mô hình mới `Classroom`, không dùng lại `Course`.** Một lớp học nhiều môn/khóa; một khóa có thể dùng cho nhiều lớp. `Course` giữ nguyên là "lộ trình bài học", gán vào lớp qua bảng nối; học sinh của lớp tự là học viên của khóa.
2. **Giữ `Organization`**, không đổi tên bảng. Chỉ thêm. Mọi thứ cũ (trang tổ chức, bài riêng, thẻ) tiếp tục chạy.
3. **Không phá URL cũ.** `/problems/`, `/contests/`, `/quizzes/`, `/courses/` vẫn mở được; trang mới là lớp bọc/chuyển hướng.
4. **"Môn" là bảng riêng** (`Subject`, mặc định chỉ có "Tin học"). Gắn `Problem`, `Quiz`, `BankQuestion`, `Course` vào môn bằng khóa ngoại (có thể rỗng = Tin học) để thêm Toán/Lý/Hóa sau chỉ là thêm dữ liệu, không sửa code.
5. **Quyền theo hai tầng:** vai trò trong tổ chức (đã có: quản trị viên, thành viên) và vai trò trong lớp (mới). Mọi view kiểm tra bằng **một hàm duy nhất** `can(user, action, obj)` để không rải điều kiện khắp nơi.

## 4. Mô hình dữ liệu mới (đề xuất)

| Bảng | Trường chính | Ghi chú |
|---|---|---|
| `Subject` | tên, slug, thứ tự, màu/biểu tượng | Dòng đầu: Tin học |
| `Classroom` | `organization`, tên, `school_year`, `homeroom` (GVCN), `subject` (tùy chọn), mã tham gia, lưu trữ (bool) | Một tổ chức nhiều lớp |
| `ClassMember` | `classroom`, `user`, `role` (HS / TG / GVBM / GVCN), ngày vào, `seat` tùy chọn | duy nhất `(classroom, user)` |
| `ClassAssignment` | lớp, tiêu đề, loại (bài lập trình / bài trắc nghiệm / bài học), đối tượng (problem / quiz / lesson), mở lúc, **hạn nộp**, điểm | "Bài giao" có hạn |
| `ClassAnnouncement` | lớp, tác giả, nội dung, ghim | Thông báo lớp (+ chuông) |
| Bảng nối | `Contest.classes`, `Quiz.classes`, `Course.classes` (nhiều-nhiều) | Gắn kỳ thi/bài thi/khóa vào lớp |
| Cột mới | `Problem.subject`, `Quiz.subject`, `BankQuestion.subject`, `Course.subject` | Đều cho phép rỗng |
| `ExamVariant` | quiz, mã (101…), thứ tự câu, thứ tự đáp án | Cho mã đề (mục 6) |

Tất cả là **migration chỉ thêm bảng/cột**, lùi được, không đổi dữ liệu cũ. Số migration phải kiểm tra xung đột với upstream (VNOJ đang trước 11 commit, đã có va chạm số `0244/0245`).

## 5. Điều hướng và trang mới

**Thanh trên (toàn site):**
`Học tập` · **`Bài tập ▾`** (Lập trình · Trắc nghiệm) · `Khóa học` · `Kỳ thi` · **`Tổ chức ▾`** (mới) · `Xếp hạng` · `Bài nộp` · `Thông tin`

**`Tổ chức ▾`** liệt kê các tổ chức của tôi; vào một tổ chức có thanh phụ:
**Tổng quan · Thành viên · Kỳ thi của tổ chức · Lớp của tôi · Tất cả lớp (quản trị) · Bài tập · Xếp hạng**.

- **Thành viên:** danh sách + lọc theo lớp/vai trò, nhập CSV (dùng lại công cụ tạo tài khoản hàng loạt).
- **Kỳ thi của tổ chức:** gộp contest + bài thi trắc nghiệm của cả tổ chức, lọc theo lớp/môn/trạng thái.
- **Lớp của tôi:** học sinh thấy lớp mình; giáo viên thấy các lớp mình dạy; mỗi lớp là **một trang tổng quan lớp** (mục 7).

**Bài tập** gồm hai tab, có bộ chọn **môn** ở đầu (Tin học là mặc định):
- **Lập trình:** trang hiện tại (danh sách, nhóm, độ khó, thẻ), thêm lọc theo môn và lớp.
- **Trắc nghiệm:** trang mới **cùng bố cục** trang lập trình: danh sách bộ câu hỏi/bài luyện theo **chủ đề → chương**, mức độ, trạng thái làm của tôi (chưa làm/đang làm/đạt), điểm tốt nhất; nút "Ôn luyện nhanh N câu" (mục 8).

## 6. Mã đề tự sinh và PDF (yêu cầu số 2)

**Luồng giáo viên:** tải đề lên (Word, hoặc PDF) → xem trước và sửa → chọn **số mã đề n** (ví dụ 4) → bấm "Sinh mã đề" → nhận **bộ PDF** (mỗi mã một tệp, kèm **một tệp đáp án** mọi mã) → in, hoặc để học sinh thi online (mỗi em được phát một mã).

- **Cách sinh:** xáo thứ tự câu **trong từng phần** (giữ nguyên phần I → II → III và đoạn ngữ liệu đi liền nhau) và xáo thứ tự đáp án A/B/C/D (câu có "cả A và B đều đúng"/"đáp án khác" phải ghim vị trí, cần phát hiện bằng cờ trên câu). Với n mã: kiểm tra **không có hai mã trùng hoàn toàn** và đáp án đúng **phân bố đều** A/B/C/D. Dùng seed cố định để tạo lại đúng cùng bộ.
- **Mã đề dùng cho thi online:** `QuizAttempt` ghi mã; chấm bằng đáp án của đúng mã (đã có nền `seed` trong hệ thống).
- **Nhập đề:**
  - **Word:** đã có bộ phân tích (`judge/utils/quiz_parser.py`, định dạng đánh dấu `[qus] … [ans]`). Cần thêm chế độ **nhận đề Word thường** (đánh số "Câu 1.", A/B/C/D, đáp án gạch chân hoặc bảng cuối đề) với **màn hình xem trước và sửa**.
  - **PDF:** nhận dạng chữ trong PDF là phần **khó và dễ sai** (công thức, hình, bảng). Đề nghị chia hai mức: (a) PDF chữ thuần → tách câu tự động, **luôn qua xem trước**, câu có công thức/hình giữ dạng **ảnh cắt**; (b) PDF scan/ảnh → không đoán, yêu cầu Word. Cần thư viện đọc PDF (chưa có; đề nghị `pypdfium2`, cài bằng pip vào môi trường site, **cần bạn cho phép**).
- **Tạo PDF (chọn một):**

| Cách | Công thức toán | Cần cài | Nhận xét |
|---|---|---|---|
| **A. Trang "bản in" + nút Lưu PDF của trình duyệt** | Đẹp (MathJax sẵn có) | Không | **Đề nghị làm trước**: nhanh, không thêm gói; giáo viên bấm In → Lưu PDF. Nhược: không tự động hóa hàng loạt, in 4 mã là 4 lần |
| **B. Máy chủ dựng PDF bằng WeasyPrint** | Cần chuyển công thức sang MathML/ảnh, **chưa chắc đẹp** | Gói hệ thống pango/cairo | Tự động, tải một lần cả bộ n mã; phải thử công thức thật |
| **C. Trình duyệt không giao diện (Chromium) trên máy chủ** | Đẹp nhất | Chromium (khoảng 300 MB), tốn RAM | Chất lượng cao nhất, nặng nhất |

  Đề nghị **A trước** (GĐ giữa), **sau đó thử B với 5 đề thật có công thức**; chỉ lên C nếu B không đạt. Quyết định này cần số liệu thật từ đề của trường, tôi **chưa kết luận được trước khi thử**.
- **Nghiệm thu:** từ một đề 40 câu sinh 4 mã: không mã nào trùng, mỗi đáp án A/B/C/D chiếm 20–30%, đáp án mỗi mã chấm lại khớp 100% với đề gốc, in ra A4 không vỡ trang giữa câu.

## 6b. Chấm bài và thống kê qua các mã
Thống kê từng câu phải **gộp theo câu gốc** (id câu), không theo vị trí trong mã. Đây là lý do `ExamVariant` lưu thứ tự theo id câu.

## 7. Lớp: tính năng (đề xuất theo mức ưu tiên)

**Cốt lõi (làm trong đợt này):**
1. **Trang tổng quan lớp:** sĩ số, thông báo ghim, bài giao sắp hạn, kỳ thi sắp tới, hoạt động gần đây.
2. **Bài giao có hạn nộp** (lập trình/trắc nghiệm/bài học) + **nhắc hạn bằng chuông** (đã có hạ tầng thông báo và celery beat). Đây cũng là hạng mục "deadline khóa học" từng đề xuất.
3. **Bảng xếp hạng lớp:** theo tuần / tháng / học kỳ / cả năm; điểm tổng hợp = lập trình + trắc nghiệm + chuyên cần với **trọng số do giáo viên chỉnh**; lọc theo môn; hiển thị **tiến bộ** (hạng tăng/giảm), không chỉ điểm tuyệt đối.
4. **Sổ điểm lớp:** bảng học sinh × bài giao/kỳ thi, xuất Excel (đã có bộ xuất xlsx).
5. **Chuyên cần tự động:** có làm bài giao/dự thi hay không, không cần điểm danh tay.
6. **Cảnh báo học sinh cần hỗ trợ:** không hoạt động 7 ngày, điểm giảm liên tiếp, hay bỏ thi; hiện cho giáo viên (không công khai cho cả lớp).
7. **Thông báo lớp** (ghim, có chuông).

**Mở rộng (đợt sau, nếu bạn thích):**
8. **Bản đồ nhiệt hoạt động** (kiểu lịch xanh như GitHub) cho từng học sinh và cho lớp.
9. **Hồ sơ năng lực** học sinh: biểu đồ mạnh/yếu theo chủ đề (đã có thống kê chủ đề `QuizTopicStat`).
10. **Thi đấu giữa các lớp:** contest tính điểm theo đội lớp, bảng xếp hạng liên lớp.
11. **Huy hiệu và chuỗi ngày học của lớp** (đã có `streak.py` ở mức cá nhân).
12. **Báo cáo tuần (PDF)** cho giáo viên/phụ huynh. *Nhạy cảm quyền riêng tư: chỉ xuất khi giáo viên chủ động, không tự gửi.*
13. **Nhóm học tập** nhỏ trong lớp.

> Lưu ý đạo đức sư phạm: bảng xếp hạng công khai có thể gây áp lực cho học sinh yếu. Đề nghị **mặc định chỉ hiện top 10 và vị trí của chính em**, giáo viên bật/tắt hiện toàn bảng.

## 8. Ôn luyện từ cơ sở dữ liệu đề thi (yêu cầu số 1)

Đã có: tạo bộ luyện cá nhân từ ngân hàng, sổ lỗi, chuỗi ngày học. Cần làm:
1. **Đổ dữ liệu vào ngân hàng** (hiện 0 câu): tự động nhập câu hỏi của 7 quiz hiện có + nhập hàng loạt đề cũ qua mục 6. Gắn **môn → chương → chủ đề → mức độ**.
2. **Ôn theo chương/chủ đề/mức độ**, tự rút N câu, **ưu tiên câu mình hay sai**.
3. **Làm lại câu sai** (đã có sổ lỗi) kèm **lặp lại ngắt quãng** (câu sai hiện lại sau 1, 3, 7 ngày).
4. **Thi thử bấm giờ** từ ngân hàng theo cấu trúc đề (ví dụ 12 + 4 + 6).
5. **Chế độ lớp:** giáo viên giao "ôn tập chương X, 20 câu, hạn thứ sáu" là một bài giao (mục 7).
6. **Thống kê cá nhân:** điểm yếu theo chủ đề, tiến độ theo tuần.
- **Chất lượng dữ liệu là rủi ro lớn nhất:** đáp án sai trong ngân hàng thì ôn luyện dạy sai. Cần cờ "đã kiểm duyệt", báo lỗi từ học sinh, và hiển thị tỉ lệ đúng bất thường (đã có phân tích độ phân biệt) để giáo viên rà. Có sẵn 3 câu nghi sai đáp án ở quiz Hóa (xem `HE-THONG.md` mục 9.4).

## 9. Phân quyền (bảng đề xuất)

| Việc | Quản trị site | Quản trị tổ chức | GVCN/GVBM của lớp | Trợ giảng | Học sinh |
|---|---|---|---|---|---|
| Tạo/xóa lớp, gán GV | ✓ | ✓ | – | – | – |
| Thêm/bớt học sinh vào lớp | ✓ | ✓ | ✓ (lớp mình) | – | – |
| Giao bài, tạo kỳ thi cho lớp | ✓ | ✓ | ✓ | ✓ (giao bài) | – |
| Xem sổ điểm, cảnh báo | ✓ | ✓ | ✓ | ✓ | chỉ của mình |
| Sửa đáp án/ngân hàng | ✓ | ✓ | ✓ (môn mình) | – | – |
| Xem xếp hạng lớp | ✓ | ✓ | ✓ | ✓ | theo cài đặt GV |
| Làm bài/ôn luyện | ✓ | ✓ | ✓ | ✓ | ✓ (lớp mình) |

## 10. Lộ trình (một người làm tuần tự)

| Đợt | Nội dung | Tuần | Dùng được khi |
|---|---|---|---|
| **P0. Nền** | `Subject`, `Classroom`, `ClassMember`, hàm phân quyền, nhập danh sách lớp bằng CSV, đưa 256 tài khoản vào tổ chức/lớp | 2,5 | Có lớp thật, giáo viên thấy học sinh của mình |
| **P1. Điều hướng + Bài tập 2 tab** | Menu "Tổ chức", thanh phụ tổ chức, trang Thành viên / Kỳ thi tổ chức / Lớp của tôi, tách Bài tập lập trình ↔ trắc nghiệm, lọc theo môn | 3 | Cấu trúc mới hoạt động |
| **P2. Lớp cốt lõi** | Tổng quan lớp, bài giao + hạn + nhắc, thông báo lớp, gắn contest/quiz/khóa vào lớp | 3 | Quản lý lớp thật |
| **P3. Xếp hạng + sổ điểm + cảnh báo** | Mục 7 (3–6) | 2,5 | Giáo viên theo dõi lớp |
| **P4. Ngân hàng + nhập đề + ôn luyện** | Mục 8 + nhập Word thường + màn hình xem trước | 3,5 | Học sinh ôn luyện từ ngân hàng |
| **P5. Mã đề + PDF** | Mục 6 (cách A), sau đó thử B | 3 | Giáo viên sinh n mã, in PDF |
| **P6. Trung tâm thi** | Giám sát lưới, báo cáo PDF, chữ ký kết quả… (theo `DU-AN-TRAC-NGHIEM.md` GĐ4–5, bỏ phần LAN) | 4 | Thi chính thức đầy đủ |
| **P7. Mở rộng lớp** | Mục 7 (8–13) chọn lọc | tùy | – |

**Tổng khoảng 21 tuần cho P0–P6** (≈ 5 tháng), P7 tùy chọn. Có thể rút xuống nếu bỏ P6 hoặc làm P5 bản A và P6 một phần. **Con số này là ước tính của tôi, chưa kiểm chứng; độ chính xác thấp nhất ở P4 (nhập PDF) và P5 (PDF có công thức).**

**Thứ tự có lý do:** P0–P2 trước vì mọi thứ khác (xếp hạng, bài giao, kỳ thi lớp) cần có "lớp"; P4 trước P5 vì cần có đề trong ngân hàng mới có gì để sinh mã; P6 cuối vì phụ thuộc mã đề.

## 11. Rủi ro và cách giảm

| Rủi ro | Cách giảm |
|---|---|
| Cải tạo lớn làm hỏng cái đang chạy (20 contest, quiz đang thi) | Mọi migration chỉ thêm; không triển khai khi có kỳ thi; thử trên DB bản sao tạm; sao lưu trước (đã có quy trình tự động) |
| **Xung đột với upstream VNOJ** (đang trước 11 commit, đã va số migration) | Quyết định sớm: hoặc **gộp upstream trước khi bắt đầu**, hoặc **chấp nhận tách nhánh** (không gộp nữa). Cần bạn chọn (mục 12) |
| Học sinh chưa vào tổ chức/lớp → trang trống | P0 gồm nhập danh sách; có trang "học sinh chưa có lớp" cho quản trị |
| Phức tạp giao diện | Vẽ bản thiết kế từng trang (như đã làm với đăng nhập) và duyệt trước khi code |
| Quyền riêng tư (điểm, cảnh báo, vi phạm) | Bảng quyền ở mục 9, ghi nhật ký truy cập sổ điểm, cập nhật trang Chính sách quyền riêng tư |
| Xếp hạng gây áp lực | Mặc định chỉ top 10 + vị trí của em; giáo viên tùy chỉnh |
| Dữ liệu ngân hàng sai | Cờ kiểm duyệt, báo lỗi, cảnh báo thống kê |
| PDF công thức xấu | Thử 5 đề thật trước khi cam kết cách B/C |
| Dịch thuật | Mỗi đợt thêm chuỗi vào `django.po` và biên dịch (đã có quy trình) |

## 12. Việc cần bạn quyết định (theo độ quan trọng)

1. **Nhánh upstream VNOJ:** gộp commit mới của VNOJ **trước** khi bắt đầu, hay **tách hẳn** và không gộp nữa? (Cải tạo lớn sẽ rất khó gộp về sau.)
2. **Danh sách lớp và học sinh**: bạn có file (CSV/Excel: họ tên, lớp, tên truy cập) không? Số lớp, số học sinh mỗi lớp?
3. **Môn học**: ngoài Tin, môn nào sẽ dùng trong 1 năm tới (Toán, Lý, Hóa?) và ai nhập đề?
4. **Cách tạo PDF**: đồng ý làm **A (in từ trình duyệt)** trước, rồi thử B với đề thật? Bạn có 3–5 đề **Word có công thức** thật để thử không?
5. **Cho cài thêm thư viện** (`pypdfium2`, có thể WeasyPrint và gói hệ thống đi kèm) vào máy chủ?
6. **Xếp hạng lớp**: công khai toàn bộ hay mặc định top 10?
7. **Thứ tự**: bạn muốn thấy cái gì dùng được **sớm nhất**? (Tôi đề nghị P0→P2: có lớp thật trước.) Có đợt nào bạn muốn bỏ hoặc hoãn không?
8. Nếu đồng ý, tôi sẽ **vẽ bản thiết kế** trước cho: menu "Tổ chức", trang tổng quan lớp, trang Bài tập (2 tab), và màn "Sinh mã đề" để bạn duyệt, rồi mới viết code P0.
