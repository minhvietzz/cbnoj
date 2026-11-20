---
name: contest-setup
description: Tạo kỳ thi (contest) lập trình trên CBNoj - đặt giờ, thể thức chấm, danh sách bài, ẩn/đóng băng bảng điểm, thí sinh/tổ chức, rồi kiểm tra trước giờ thi. Dùng khi người dùng nói "tạo contest", "tạo kỳ thi", "mở cuộc thi", "thêm bài vào contest".
---

# Tạo kỳ thi (contest)

Contest nhiều kỳ đã có (`manage.py shell -c "from judge.models import Contest; ..."`), dùng một kỳ gần nhất làm mẫu (đặc biệt các trường `format_name`, `scoreboard_visibility`, `is_visible`, `organization`, `is_organization_private`). Giờ trong DB là **UTC**; giờ VN = UTC+7 (08:00 VN = 01:00 UTC). Xác nhận lại giờ với người dùng bằng giờ VN.

## 1. Hỏi / xác nhận
Tên kỳ thi, mã (`key`, chữ thường không dấu), giờ bắt đầu/kết thúc (VN), danh sách bài (mã) và điểm từng bài, thể thức (`default`, `icpc`, `ioi`, `legacy_ioi`, `atcoder`, `ecoo`, `vnoj`; xem `judge/contest_format/`; kỳ thi gần đây dùng `default`), bảng điểm hiện hay ẩn/đóng băng (`frozen_last_minutes`, `scoreboard_visibility`), công khai hay chỉ tổ chức (`is_organization_private`, `organization` = tổ chức `cbnoj`), có `access_code` không, có cho thi ảo (`disallow_virtual`), có xếp hạng rating không (`is_rated`).

## 2. Tạo bằng shell
```python
from datetime import datetime, timezone
from judge.models import Contest, ContestProblem, Problem, Profile, Organization
c = Contest(key='ten_ky_thi', name='Tên kỳ thi', description='...', summary='',
            start_time=datetime(2026,11,20,1,0,tzinfo=timezone.utc), end_time=datetime(2026,11,20,4,0,tzinfo=timezone.utc),
            format_name='default', is_visible=False, is_rated=False)   # ẩn cho tới khi kiểm tra xong
c.save()
c.authors.add(Profile.objects.get(user__username='admin'))
for i, code in enumerate(['b05_tong', 'b05_max'], 1):
    ContestProblem.objects.create(contest=c, problem=Problem.objects.get(code=code), points=100, order=i, partial=True)
```
Xem mẫu từ contest hiện có bằng `Contest._meta`/`ContestProblem._meta` nếu thiếu trường. Tổ chức riêng: đặt `organization`, `is_organization_private=True`. Hoặc dùng `/admin/judge/contest/add/`.

## 3. Kiểm tra trước giờ thi (bắt buộc)
- Mọi bài trong contest đã có dữ liệu test và **đã được nộp thử đúng** (skill `up-problem`); bài `is_public=False` vẫn dùng được trong contest nếu đã gắn.
- `judge1`, `judge2`, `bridged`, `runner` đều `RUNNING`.
- Mở trang `/contest/<key>` bằng user tạm hoặc `curl` (200); kiểm tra giờ hiển thị đúng (VN).
- **Không restart `site`** trong suốt kỳ thi; nếu kỳ thi sắp diễn ra mà cần deploy, làm trước hoặc sau.
- Cân nhắc tải: mỗi thí sinh gọi nhiều yêu cầu; site hiện chịu 12 yêu cầu đồng thời (mục 13 của tài liệu). Thi trên 100 người cùng lúc → chạy `site-health` ở 5 phút đầu.
- Bật `is_visible=True` khi sẵn sàng (hỏi người dùng trước).

## 4. Ghi nhật ký
Mục 15 của `docs/HE-THONG.md`: key, giờ (VN), thể thức, danh sách bài. Cập nhật số contest ở mục 1.
