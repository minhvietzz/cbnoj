---
name: users-admin
description: Quản lý tài khoản CBNoj hàng loạt - tạo tài khoản từ danh sách lớp (CSV), gán vào tổ chức, đặt lại mật khẩu, khóa/mở khóa, đổi quyền. Dùng khi người dùng nói "tạo tài khoản cho lớp", "tạo user hàng loạt", "reset mật khẩu", "khóa tài khoản", "thêm vào tổ chức".
---

# Quản lý tài khoản

**Mật khẩu là thông tin nhạy cảm:** không in mật khẩu ra chat. Mật khẩu sinh ra chỉ được ghi vào **file CSV kết quả trong scratchpad**, rồi gửi file đó cho người quản trị bằng SendUserFile (hoặc bảo họ lấy ở đường dẫn). Không ghi vào tài liệu, log hay nhật ký.
Hỏi người dùng trước khi tạo/khóa/xóa/đổi quyền (ảnh hưởng người thật).

## Tạo hàng loạt
Lệnh có sẵn: `manage.py batchadduser <input.csv> <output.csv>`.
- `input.csv`: cột `username,fullname` (UTF-8, có dòng tiêu đề). Username không dấu, chữ thường/số, không trùng (kiểm tra trước: `User.objects.filter(username__in=[...])`).
- `output.csv` có thêm cột `password` (mật khẩu ngẫu nhiên, bảng chữ cái bỏ ký tự dễ nhầm). Gửi file này cho người quản trị để phát cho học sinh.
- Một người: `manage.py adduser <tên> <email> <mật_khẩu> [ngôn_ngữ] [--staff|--superuser]` - tránh truyền mật khẩu trên dòng lệnh khi có thể (lịch sử shell); ưu tiên `batchadduser`.
Sau khi tạo: kiểm tra có `Profile`, đăng nhập thử một tài khoản mẫu bằng test Client (`force_login`), **không** thử mật khẩu thật.

## Gán tổ chức (hiện có một tổ chức `cbnoj`, id 1)
```python
from judge.models import Organization, Profile
org = Organization.objects.get(slug='cbnoj')
for name in [...]:
    prof = Profile.objects.get(user__username=name)
    prof.organizations.add(org)        # quan hệ Profile.organizations (ngược lại: Organization.member)
```
Sau khi thêm thành viên kiểm tra `org.member_count` có tăng đúng không (nếu không, xem `judge/models/profile.py`/signals để biết nơi cập nhật).

## Đặt lại mật khẩu
`user.set_password(<mới>); user.save()` - mật khẩu mới sinh ngẫu nhiên, ghi vào CSV trong scratchpad, **không** in. Hoặc gửi email đặt lại mật khẩu qua trang quên mật khẩu (email chạy nền qua celery).

## Khóa / mở khóa / quyền
- Khóa đăng nhập: `user.is_active = False`. Cấm nộp bài/bình luận: `profile.mute = True` / cấm theo `ban_reason` (xem `judge/models/profile.py`, trang `user/ban.html`).
- Quyền quản trị (`is_staff`, `is_superuser`, nhóm): chỉ đổi khi người dùng yêu cầu rõ ràng; ghi lại ai được cấp gì.
- **Xóa tài khoản**: không xóa; dùng khóa. Chỉ xóa vĩnh viễn khi người dùng xác nhận và đã sao lưu DB (skill `backup`).

## Kết thúc
Báo: bao nhiêu tài khoản tạo/sửa, tên file CSV (đường dẫn đầy đủ trong scratchpad), việc chưa làm. Mục 15 của `docs/HE-THONG.md`: ghi "tạo N tài khoản lớp X" (không ghi mật khẩu). Cập nhật số tài khoản ở mục 1 nếu thay đổi lớn.
