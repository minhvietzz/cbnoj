# flake8: noqa: E501  (long Vietnamese tool descriptions)
from datetime import timedelta

from django.conf import settings
from django.urls import reverse
from django.utils import timezone
from reversion import revisions

from judge.forms import BlogPostForm
from judge.mcp.registry import ToolError, tool
from judge.models import BlogPost, Organization
from judge.tasks.webhook import on_new_blogpost
from judge.utils.unicode import remove_accents

MAX_CONTENT = 100000


def _find_org(value):
    value = str(value).strip()
    org = Organization.objects.filter(id=value).first() if value.isdigit() else None
    return org or Organization.objects.filter(slug=value).first()


def _info(ctx, post):
    return {
        'id': post.id, 'title': post.title, 'visible': post.visible,
        'organization': post.organization.slug if post.organization_id else None,
        'url': ctx.request.build_absolute_uri(post.get_absolute_url()),
        'edit_url': ctx.request.build_absolute_uri(reverse('blog_post_edit', args=(post.id, post.slug))),
    }


def _form(ctx, post, title, content, visible, publish_on):
    data = {'title': title, 'content': content, 'publish_on': publish_on.strftime('%Y-%m-%d %H:%M:%S')}
    if visible:
        data['visible'] = 'on'
    form = BlogPostForm(data, instance=post, user=ctx.user)
    if not form.is_valid():
        problems = ['%s: %s' % (field, ' '.join(errs)) for field, errs in form.errors.items()]
        raise ToolError('Bài viết không hợp lệ, chưa lưu:\n' + '\n'.join(problems))
    return form


def _check_content(content):
    content = str(content or '').strip()
    if not content:
        raise ToolError('Nội dung bài viết đang trống.')
    if len(content) > MAX_CONTENT:
        raise ToolError('Nội dung quá dài (tối đa %d ký tự).' % MAX_CONTENT)
    return content


@tool(
    'blog_create',
    'Tạo bài viết/thông báo (nội dung Markdown). Mặc định là BẢN NHÁP (chưa ai thấy ngoài tác giả); chỉ đặt publish=true '
    'khi giáo viên yêu cầu đăng ngay. Có organization thì đăng trong tổ chức (bạn phải là quản trị tổ chức; chỉ thành viên '
    'tổ chức thấy); không có thì là bài cá nhân công khai trên trang (cần đã giải đủ số bài theo quy định của trang).',
    {
        'title': {'type': 'string', 'description': 'Tiêu đề, tối đa 100 ký tự.'},
        'content': {'type': 'string', 'description': 'Nội dung Markdown (có thể dùng $...$ cho công thức, ![](url) cho ảnh).'},
        'organization': {'type': 'string', 'description': 'Slug hoặc id tổ chức để đăng trong tổ chức (tùy chọn).'},
        'publish': {'type': 'boolean', 'description': 'true = hiển thị ngay; mặc định false (bản nháp).'},
    },
    required=['title', 'content'],
)
def blog_create(ctx, title, content, organization=None, publish=False):
    user, profile = ctx.user, ctx.profile
    title = ' '.join(str(title).split())
    content = _check_content(content)
    org = None
    if organization:
        org = _find_org(organization)
        if org is None or not org.is_admin(profile):
            raise ToolError('Không có tổ chức này hoặc bạn không phải quản trị của tổ chức đó.')
        if not user.has_perm('judge.edit_organization_post'):
            raise ToolError('Tài khoản của bạn chưa có quyền đăng bài trong tổ chức. Hãy nhờ quản trị viên cấp quyền.')
    else:
        if getattr(ctx.request, 'official_contest_mode', False):
            raise ToolError('Đang ở chế độ thi chính thức, không đăng bài cá nhân được.')
        need = settings.VNOJ_BLOG_MIN_PROBLEM_COUNT
        if profile.problem_count < need and not user.is_superuser:
            raise ToolError('Bài cá nhân yêu cầu đã giải ít nhất %d bài (bạn mới giải %d). '
                            'Hãy đăng trong tổ chức bạn quản trị (tham số organization).' % (need, profile.problem_count))

    recent = BlogPost.objects.filter(authors=profile, title=title, organization=org,
                                     publish_on__gte=timezone.now() - timedelta(minutes=5))
    existing = recent.first()
    if existing is not None and existing.content == content:
        result = _info(ctx, existing)
        result['note'] = 'Bài cùng tên và nội dung vừa được tạo cách đây ít phút nên không tạo trùng.'
        return result

    form = _form(ctx, None, title, content, bool(publish), timezone.now())
    with revisions.create_revision(atomic=True):
        post = form.save()
        post.authors.add(profile)
        if org is not None:
            post.slug = ''.join(x for x in org.slug.lower() if x.isalnum())
            post.organization = org
        else:
            post.slug = remove_accents(user.username.lower())
        post.publish_on = timezone.now()
        post.save()
        revisions.set_comment('Created via MCP')
        revisions.set_user(user)
    if post.visible and org is None:
        on_new_blogpost(post.id)
    result = _info(ctx, post)
    result['next'] = ('Đã đăng.' if post.visible else
                      'Đây là bản nháp. Mở edit_url để xem/sửa, hoặc gọi blog_update với publish=true để đăng.')
    return result


@tool(
    'blog_update',
    'Sửa tiêu đề/nội dung của bài viết bạn là tác giả, hoặc đăng/gỡ bài (publish true/false). Lịch sử chỉnh sửa vẫn được lưu. '
    'Chỉ gửi các trường muốn đổi.',
    {
        'post_id': {'type': 'integer', 'description': 'Id bài viết (từ blog_create hoặc blog_list_mine).'},
        'title': {'type': 'string'},
        'content': {'type': 'string', 'description': 'Toàn bộ nội dung Markdown mới (thay thế nội dung cũ).'},
        'publish': {'type': 'boolean', 'description': 'true = hiển thị, false = chuyển về bản nháp.'},
    },
    required=['post_id'], idempotent=True,
)
def blog_update(ctx, post_id, title=None, content=None, publish=None):
    post = BlogPost.objects.filter(id=post_id).first()
    if post is None or not post.is_editable_by(ctx.user):
        raise ToolError('Không có bài viết này hoặc bạn không có quyền sửa nó.')
    if title is None and content is None and publish is None:
        raise ToolError('Chưa có trường nào để đổi.')
    new_title = ' '.join(str(title).split()) if title is not None else post.title
    new_content = _check_content(content) if content is not None else post.content
    visible = post.visible if publish is None else bool(publish)
    was_visible = post.visible
    form = _form(ctx, post, new_title, new_content, visible, post.publish_on)
    with revisions.create_revision(atomic=True):
        post = form.save()
        post.visible = visible
        if visible and not was_visible:
            post.publish_on = timezone.now()
        post.save()
        revisions.set_comment('Edited via MCP')
        revisions.set_user(ctx.user)
    return _info(ctx, post)


@tool(
    'blog_list_mine',
    'Liệt kê các bài viết bạn là tác giả (mới nhất trước): id, tiêu đề, đã đăng hay còn là bản nháp, tổ chức.',
    {'limit': {'type': 'integer', 'minimum': 1, 'maximum': 50, 'description': 'Số bài tối đa, mặc định 20.'}},
    read_only=True, idempotent=True,
)
def blog_list_mine(ctx, limit=20):
    limit = max(1, min(int(limit or 20), 50))
    posts = BlogPost.objects.filter(authors=ctx.profile).select_related('organization').order_by('-id')[:limit]
    return {'count': len(posts), 'posts': [_info(ctx, p) for p in posts]}
