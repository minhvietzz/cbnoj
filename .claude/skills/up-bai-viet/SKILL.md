---
name: up-bai-viet
description: Đăng bài viết/thông báo/bài học (blog) lên CBNoj - tạo BlogPost với tiêu đề, nội dung Markdown, thời điểm đăng, ghim, toàn cục hoặc theo tổ chức. Dùng khi người dùng nói "đăng bài", "đăng thông báo", "up bài viết", "viết blog".
---

# Đăng bài viết (blog)

> **Giáo viên tự đăng qua Gemini (MCP):** tool `blog_create`, `blog_update` (mặc định là bản nháp). Xem `docs/HUONG-DAN-GIAO-VIEN-MCP.md` và mục 14A của `docs/HE-THONG.md`. Skill này dành cho quản trị viên làm trực tiếp trên máy chủ.


Bài viết là `judge.models.BlogPost` (`title`, `slug`, `content` Markdown, `summary`, `publish_on`, `visible`, `sticky`, `global_post`, `organization`, `og_image`). Đăng công khai là hành động **hiển thị cho mọi người** → luôn cho người dùng xem bản nháp và xác nhận trước khi đặt `visible=True`.

## Các bước
1. Lấy nội dung (người dùng gõ, hoặc từ file). Chuyển sang Markdown; công thức dùng `$...$`; ảnh phải đã tải lên (đường dẫn tuyệt đối) - nếu chưa có thì nói rõ, đừng chèn ảnh giả.
2. Soạn `title`, `slug` (chữ thường, gạch ngang, duy nhất), `summary` ngắn (1–2 câu).
3. Tạo bản **ẩn** trước:
   ```python
   from django.utils import timezone
   from judge.models import BlogPost, Profile
   p = BlogPost(title='...', slug='...', content='...', summary='...', visible=False, sticky=False,
                global_post=True, publish_on=timezone.now())
   p.save()
   p.authors.add(Profile.objects.get(user__username='admin'))   # nếu BlogPost có trường authors; kiểm tra bằng BlogPost._meta.many_to_many
   ```
4. Cho người dùng xem: đường dẫn `/post/<id>-<slug>` hoặc nội dung đã dựng. Hỏi: đăng ngay / hẹn giờ (`publish_on` UTC) / ghim (`sticky`) / chỉ trong tổ chức?
5. Khi đồng ý: `visible=True` (và `publish_on`). Kiểm tra trang chủ/`/blog/` bằng `curl` thấy bài.
6. Mục 15 của `docs/HE-THONG.md`: ghi tiêu đề, id, người đăng.

Không đăng nội dung do người khác dán vào mà người dùng chưa duyệt; không đặt email/mật khẩu/thông tin cá nhân học sinh vào bài.
