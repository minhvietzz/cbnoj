---
name: quiz-results
description: Xem và xuất kết quả quiz/bài thi trắc nghiệm trên CBNoj - bảng điểm, xuất CSV/Excel, câu nào sai nhiều, vi phạm giám sát, xử lý lượt làm (đặt lại, cộng thời gian, vô hiệu hóa, công bố điểm). Dùng khi người dùng nói "xem điểm", "xuất điểm", "kết quả bài thi", "reset lượt làm", "cho làm lại", "cộng thêm giờ".
---

# Kết quả và xử lý lượt làm quiz

Đọc `docs/HE-THONG.md` mục 9. Trang web đã có sẵn: `/quiz/<slug>/results/` (bảng điểm), `?export=csv|xlsx` (xuất file), `/quiz/<slug>/results/live/` (theo dõi trực tiếp), `.../results/action/` (hành động của giáo viên: `extend`, `extend_all`, `publish`/`unpublish`, đặt lại...). Ưu tiên dùng giao diện web; shell chỉ để lấy số liệu nhanh hoặc khi giao diện không làm được.

## Xem bảng điểm nhanh (chỉ đọc)
```python
# manage.py shell
from judge.models import Quiz
from judge.utils import quiz_stats
q = Quiz.objects.get(slug='kt-giua-ki-11-hoa')
for r in quiz_stats.exam_ranking(q):
    a = r['attempt']; print(r['rank'], r['user'].user.username, r['score'], '/', r['max'], r['score10'], a.violation_count, a.auto_submitted)
```
`exam_ranking` lấy lượt tốt nhất mỗi người, bỏ qua người quản trị/giáo viên và lượt bị vô hiệu hóa.
Độ khó từng câu: `quiz_stats.question_accuracy(q)`. Danh sách đang làm dở: `q.attempts.filter(finished__isnull=True)`.

## Xuất file
Ghi vào **scratchpad** (không để trong site). CSV cần BOM `﻿` để Excel đọc tiếng Việt:
```python
import csv, io
rows = quiz_stats.exam_ranking(q)
with open('<scratchpad>/ketqua.csv', 'w', newline='', encoding='utf-8-sig') as f:
    w = csv.writer(f); w.writerow(['Hạng','Tài khoản','Họ tên','Điểm','Tối đa','Thang 10','Số vi phạm'])
    for r in rows: w.writerow([r['rank'], r['user'].user.username, r['user'].user.first_name, r['score'], r['max'], r['score10'], r['attempt'].violation_count])
```
Hoặc `judge.utils.xlsx.build_xlsx(header, rows, title)` ra bytes `.xlsx`. Gửi file cho người dùng bằng SendUserFile.
**Đáp án chỉ được lộ sau khi bài thi kết thúc** (`quiz.answers_released()`); đừng xuất đáp án đúng trước đó.

## Xử lý lượt làm (phải hỏi người dùng trước)
- **Cho làm lại** (ví dụ học sinh bị lỗi mạng): xóa hoặc vô hiệu hóa lượt đó → `attempt.invalidated=True; attempt.save()` (giữ bằng chứng, không tính vào xếp hạng; nhớ kiểm tra trong `judge/views/quiz.py` (`QuizStart`) xem `max_attempts` có đếm lượt bị vô hiệu hóa hay không trước khi hứa cho làm lại). Xóa hẳn lượt (`attempt.delete()`) chỉ khi người dùng xác nhận "xóa vĩnh viễn".
- **Cộng thêm giờ**: `attempt.extra_minutes += n` (một người) hoặc `quiz.extra_minutes += n` (tất cả) - dùng nút trên giao diện nếu được.
- **Công bố điểm**: `quiz.results_published = True` (khi `results_release='manual'`).
- **Lượt kẹt "đang làm" quá hạn**: `manage.py finalize_quiz_attempts` (hiện chưa có cron, xem mục 6 tài liệu).
- Trước khi sửa dữ liệu lượt làm, ghi lại id lượt/người/giá trị cũ để hoàn tác.
- Lượt đang mở trên thực tế cần xử lý: tra cứu rồi báo người dùng (ví dụ một lượt dở ở quiz Hóa).

## Kết thúc
Báo số liệu chính xác (có bao nhiêu người, điểm trung bình, ai vi phạm) và những gì đã thay đổi. Nếu đã sửa dữ liệu → ghi mục 15 của `docs/HE-THONG.md`.
