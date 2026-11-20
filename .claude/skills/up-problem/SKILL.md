---
name: up-problem
description: Đăng bài tập lập trình (problem) có bộ test lên CBNoj - tạo bản ghi Problem, đặt dữ liệu test cho judge (init.yml, file .in/.out, zip), nhóm/loại bài, điểm, giới hạn, rồi nộp thử lời giải mẫu để xác nhận chấm đúng. Dùng khi người dùng nói "up bài", "thêm bài tập", "đăng đề code", "up test cho bài".
---

# Đăng bài tập có bộ test

Đọc `docs/HE-THONG.md` mục 7.1. Một bài gồm **(a) bản ghi `Problem` trong DB** và **(b) thư mục dữ liệu** `/home/vnojsite/problems/<mã>/` mà judge đọc.

## 1. Thu thập thông tin (hỏi người dùng nếu thiếu)
mã bài (chữ thường, số, `_`, ví dụ `b05_tong`), tên, đề bài (Markdown, có thể có LaTeX `$...$`), nhóm (`ProblemGroup`), loại (`ProblemType`), điểm tổng, giới hạn thời gian (giây) và bộ nhớ, có chấm điểm từng phần không, công khai hay chưa, bộ test (file `.in/.out` hoặc zip), có checker đặc biệt không (mặc định so sánh `standard`).
Xem nhóm/loại có sẵn: `manage.py shell -c "from judge.models import *; print(list(ProblemGroup.objects.values_list('name',flat=True))); print(list(ProblemType.objects.values_list('name',flat=True)))"`.

## 2. Dữ liệu test
1. Tạo thư mục `/home/vnojsite/problems/<mã>/`, đặt các file `1.in 1.out 2.in 2.out ...` (tên không dấu).
2. Viết `init.yml` cạnh chúng:
   ```yaml
   test_cases:
   - {in: 1.in, out: 1.out, points: 20}
   - {in: 2.in, out: 2.out, points: 20}
   ```
   Tổng `points` các test = điểm bài (các bài hiện tại: 10 test × 10 hoặc 2 test × 50...). Bài có file vào/ra (`freopen`) cần thêm `input_file`/`output_file` theo tài liệu DMOJ.
3. Tạo `<mã>.zip` chứa các file test (không chứa thư mục cha) và bản ghi `ProblemData` (`zipfile='<mã>/<mã>.zip'`, `checker='standard'`, `grader='standard'`, `zipfile_size`).
4. `chown -R cbnoj:cbnoj /home/vnojsite/problems/<mã>` (hoặc đúng quyền của các bài hiện có; judge chạy bằng `cbnoj-judge` nên thư mục phải **đọc được** bởi mọi user: `chmod -R a+rX`).
Cách thay thế: tải zip qua trang "Dữ liệu" của bài trong giao diện quản trị.

## 3. Bản ghi Problem
Dùng `manage.py shell`:
```python
from judge.models import Problem, ProblemGroup, ProblemType, ProblemData, Language, Profile
p = Problem(code='b05_tong', name='Tính tổng', description='...Markdown...',
            group=ProblemGroup.objects.get(name='g_nhapxuat'), time_limit=1.0, memory_limit=262144,  # KB
            points=100, partial=True, is_public=False)
p.save()
p.types.set([ProblemType.objects.get(name='uncategorized')])
p.authors.add(Profile.objects.get(user__username='admin'))
p.allowed_languages.set(Language.objects.filter(key__in=[...]))   # xem một bài mẫu: Problem.objects.get(code='b03_fibo').allowed_languages
ProblemData.objects.create(problem=p, zipfile='b05_tong/b05_tong.zip', checker='standard', grader='standard')
```
Lấy bài mẫu `b03_fibo` làm chuẩn (`memory_limit=262144`, `partial=True`, `is_public=True`, 10 ngôn ngữ cho phép). Để `is_public=False` cho tới khi kiểm tra xong.

## 4. Kiểm tra bắt buộc: nộp thử lời giải mẫu
1. Viết lời giải đúng (C++/Python) và một lời giải sai.
2. Nộp bằng Django test Client với user tạm hoặc qua `Submission` + `judge.judgeapi`/trang web; chờ judge chấm (`judge1/judge2` phải RUNNING; xem `supervisorctl status`).
3. Lời giải đúng phải đạt đủ điểm, lời giải sai phải bị trừ điểm. Kiểm tra giới hạn thời gian.
4. **Xóa** bài nộp thử và user tạm.
Nếu mọi thứ tốt → báo người dùng và hỏi có `is_public=True` không.

## 5. Ghi nhật ký
Thêm vào mục 15 của `docs/HE-THONG.md` (mã bài, nơi dữ liệu). Cập nhật số bài ở mục 1 nếu thay đổi nhiều.
