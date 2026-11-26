from judge.mcp.registry import tool
from judge.models.classroom import ClassMember, MANAGER_ROLES

CAPABILITIES = (
    ('judge.add_quiz', 'đăng quiz/bài thi trắc nghiệm'),
    ('judge.add_problem', 'tạo bài tập code'),
    ('judge.create_organization_problem', 'tạo bài tập code trong tổ chức mình quản trị'),
    ('judge.add_classroom', 'tạo lớp'),
    ('judge.edit_organization_post', 'đăng bài viết trong tổ chức'),
)


@tool(
    'whoami',
    'Cho biết tài khoản CBNoj đang đăng nhập và những việc tài khoản này được phép làm '
    '(đăng quiz, tạo bài tập, tổ chức/lớp đang quản lý). Nên gọi đầu tiên.',
    read_only=True,
    idempotent=True,
)
def whoami(ctx):
    user, profile = ctx.user, ctx.profile
    classes = ClassMember.objects.filter(user=profile, role__in=MANAGER_ROLES).select_related('classroom')
    return {
        'username': user.username,
        'display_rank': profile.display_rank,
        'superuser': user.is_superuser,
        'can': [text for perm, text in CAPABILITIES if user.has_perm(perm)],
        'organizations_administered': [{'slug': o.slug, 'name': o.name} for o in profile.admin_of.all()],
        'classes_managed': [{'id': m.classroom_id, 'name': m.classroom.name} for m in classes],
        'site': ctx.request.build_absolute_uri('/').rstrip('/'),
    }
