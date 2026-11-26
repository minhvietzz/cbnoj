---
name: up-quiz
description: Đăng đề trắc nghiệm lên CBNoj (mục Quiz) từ PDF/DOCX/ảnh/văn bản - trích câu hỏi, tạo Quiz với 4 loại câu (một đáp án, nhiều đáp án, trả lời ngắn, đúng/sai 4 ý), đặt chế độ thi/giám sát/rút N câu mỗi bài, rồi thi thử để kiểm tra. Dùng khi người dùng nói "up đề", "up test", "up quiz", "đặt thành bài thi", "khóa màn hình", "rút 30 câu trong 86 câu".
---

# Đăng quiz lên CBNoj

> **Giáo viên tự đăng qua Gemini (MCP):** tool `quiz_format_help`, `quiz_preview`, `quiz_create`, `quiz_configure` làm cùng việc này, tạo quiz riêng tư. Xem `docs/HUONG-DAN-GIAO-VIEN-MCP.md` và mục 14A của `docs/HE-THONG.md`. Skill này dành cho quản trị viên làm trực tiếp trên máy chủ.


Trước tiên đọc `docs/HE-THONG.md` mục 9 (hệ thống quiz). Mọi thao tác dùng `/home/vnojsite/bin/python manage.py shell`.

## 1. Lấy nội dung đề
- **PDF**: `pdfplumber` (đã cài ở thư mục `pylib` của scratchpad nếu còn; nếu không `pip install --target <scratchpad>/pylib pdfplumber pypdfium2`, rồi `PYTHONPATH=... python3`; đừng dùng `python3 -I`). Không có `pdftotext`.
- **DOCX**: là file zip; đọc `word/document.xml` bằng `zipfile`. Ảnh nằm ở `word/media/` (đề kiểu "ảnh có đáp án đỏ" thì mở ảnh bằng Read để nhìn và gõ lại).
- Đề dạng ảnh: xem từng ảnh bằng công cụ Read, chép lại câu hỏi, chọn đáp án theo dấu (màu đỏ/gạch chân/bảng đáp án cuối đề).
- Câu hỏi có công thức/hình mà không chép được: nói rõ cho người dùng, đừng tự bịa.

## 2. Chọn dạng câu
`single` (1 đáp án đúng), `multi` (nhiều đáp án đúng), `short` (nhập chữ; đáp án chấp nhận trong `accepted_answers`, ngăn cách bằng `|`), `tf4` (4 ý đúng/sai; điểm tính theo số ý đúng). Tự luận không có trong hệ thống: bỏ qua phần tự luận và nói với người dùng.
Đề có nhiều phần: dùng `section='Phần I: Trắc nghiệm'`, ... Đoạn ngữ liệu chung: `passage`.
Điểm: chia đều cho tổng điểm mong muốn (ví dụ 28 câu = 7 điểm → 0,25/câu; 86 câu rút 30 → 10/30 = 0,3333/câu).

## 3. Tạo quiz
Dùng mẫu `template_make_quiz.py` trong thư mục này: sao chép vào scratchpad, sửa dữ liệu, chạy `manage.py shell < file.py`. Mẫu dùng `transaction.atomic`, từ chối nếu slug đã tồn tại, lấy `creator` từ quiz tham chiếu.
Hoặc, với file Word/txt theo định dạng `[qus]/[ans]`, người dùng có thể tự tải ở `/quizzes/upload/` (xem docstring `judge/utils/quiz_parser.py`).

Tham số quan trọng của `Quiz`:
- `mode='exam'` (thi) hay `'practice'` (luyện tập). "Đặt thành bài thi" = `mode='exam'`, `proctoring='strict'`, `time_limit=45`, `max_attempts=1`, `max_violations=3`, `results_release='after_end'` hoặc `'immediate'`, `shuffle_questions=True`, `shuffle_options` tùy đề (đề có "A và B đều đúng" thì để False).
- `proctoring`: `off` / `light` (chặn copy, chuột phải) / `strict` (khóa toàn màn hình + giám sát; người học phải đồng ý nội quy).
- `questions_per_attempt=N`: mỗi bài rút ngẫu nhiên N câu (0 = tất cả).
- `start_time`/`end_time`: cửa sổ làm bài (giờ UTC trong DB; giờ VN = UTC+7). Không có thì mở mọi lúc.
- `is_public=True` nếu muốn mọi người thấy; `organizations` để giới hạn theo tổ chức.
- `source_name`: tên file nguồn.

## 4. Kiểm tra bắt buộc
1. Đếm lại: số câu, tổng điểm (`quiz.total_points`, `quiz.paper_points`), mỗi câu đơn có đúng 1 đáp án đúng.
2. **Thi thử bằng user tạm**: tạo `User` + `Profile(language=Language.get_default_language())`, `Client.force_login`, POST `quiz_start` với `{'agree':'1'}` nếu giám sát nghiêm, lấy trang làm bài, nộp đáp án đúng → phải đạt điểm tối đa; với rút N câu, kiểm tra đúng N câu và các seed khác nhau cho bộ khác nhau. **Xóa user tạm và lượt làm** sau đó.
3. Liệt kê cho người dùng **những đáp án bạn không chắc** (đề không có đáp án, chép từ ảnh mờ…), đừng giấu.

## 5. Kết thúc
Báo: id, slug, đường dẫn `/quiz/<slug>/`, cấu hình đã đặt, phần chưa chắc. Hỏi người dùng có muốn đặt cửa sổ giờ thi / đặt công khai không. **Ghi vào mục 15 và bảng 9.4 của `docs/HE-THONG.md`.**
