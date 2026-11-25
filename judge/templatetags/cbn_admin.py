from django import template

register = template.Library()

# (group title, [object names in display order])
GROUPS = [
    ('Bài tập', ['Problem', 'Submission', 'ProblemGroup', 'ProblemType', 'Tag', 'TagGroup', 'TagProblem', 'License',
                 'Language', 'OrganizationProblemTag']),
    ('Kỳ thi lập trình', ['Contest', 'ContestParticipation', 'ContestTag']),
    ('Trắc nghiệm', ['Quiz', 'QuizQuestion', 'QuizAttempt', 'BankQuestion', 'BankTag', 'QuizProfileStat']),
    ('Lớp và môn', ['Classroom', 'ClassAssignment', 'ClassAnnouncement', 'Subject', 'Course', 'CourseLesson']),
    ('Người dùng và tổ chức', ['User', 'Profile', 'Group', 'Organization', 'OrganizationRequest', 'Badge',
                               'RegistrationProfile']),
    ('Bài viết và hỗ trợ', ['BlogPost', 'BlogPostTag', 'Comment', 'CommentLock', 'Ticket', 'FlatPage']),
    ('Hệ thống', ['Judge', 'NavigationBar', 'MiscConfig', 'Redirect', 'Site', 'LogEntry', 'ImpersonationLog']),
    ('Đăng nhập bên ngoài', ['Application', 'AccessToken', 'RefreshToken', 'Grant', 'IDToken', 'UserSocialAuth',
                             'Association', 'Nonce']),
]


@register.filter
def admin_groups(app_list):
    """Regroup the admin app list by job instead of by Django app."""
    by_name = {}
    for app in app_list or []:
        for model in app['models']:
            by_name[model['object_name']] = model
    groups, used = [], set()
    for title, names in GROUPS:
        models = [by_name[n] for n in names if n in by_name]
        used.update(n for n in names if n in by_name)
        if models:
            groups.append({'title': title, 'models': models})
    rest = [m for n, m in by_name.items() if n not in used]
    if rest:
        groups.append({'title': 'Khác', 'models': rest})
    return groups


# Vietnamese names for the sidebar (same order as the design), keyed by object_name.
NAV_NAMES = {
    'Problem': 'Bài', 'Submission': 'Bài nộp', 'ProblemGroup': 'Nhóm bài', 'ProblemType': 'Dạng đề', 'Tag': 'Tag',
    'TagGroup': 'Nhóm tag', 'TagProblem': 'Tag bài', 'License': 'Giấy phép', 'Language': 'Ngôn ngữ',
    'OrganizationProblemTag': 'Dạng bài của tổ chức', 'Contest': 'Kỳ thi', 'ContestParticipation': 'Tham gia kỳ thi',
    'ContestTag': 'Thẻ kỳ thi', 'Quiz': 'Đề trắc nghiệm', 'QuizQuestion': 'Câu hỏi', 'QuizAttempt': 'Bài làm',
    'BankQuestion': 'Ngân hàng câu hỏi', 'BankTag': 'Thẻ ngân hàng', 'QuizProfileStat': 'Thống kê trắc nghiệm',
    'Classroom': 'Lớp', 'ClassAssignment': 'Bài giao', 'ClassAnnouncement': 'Thông báo lớp', 'Subject': 'Môn học',
    'Course': 'Khóa học', 'CourseLesson': 'Bài học', 'User': 'Người dùng', 'Profile': 'Hồ sơ', 'Group': 'Nhóm quyền',
    'Organization': 'Tổ chức', 'OrganizationRequest': 'Yêu cầu vào tổ chức', 'Badge': 'Huy hiệu',
    'RegistrationProfile': 'Hồ sơ đăng ký', 'BlogPost': 'Bài blog', 'BlogPostTag': 'Nhãn blog', 'Comment': 'Nhận xét',
    'CommentLock': 'Khóa bình luận', 'Ticket': 'Phiếu hỗ trợ', 'FlatPage': 'Trang tĩnh', 'Judge': 'Máy chấm',
    'NavigationBar': 'Menu điều hướng', 'MiscConfig': 'Cấu hình khác', 'Redirect': 'Chuyển hướng', 'Site': 'Trang web',
    'LogEntry': 'Nhật ký thao tác', 'ImpersonationLog': 'Nhật ký đăng nhập thay', 'Application': 'Ứng dụng OAuth',
    'AccessToken': 'Mã truy cập', 'RefreshToken': 'Mã làm mới', 'Grant': 'Grant', 'IDToken': 'ID token',
    'UserSocialAuth': 'Liên kết mạng xã hội', 'Association': 'Association', 'Nonce': 'Nonce',
}


@register.simple_tag(takes_context=True)
def cba_nav(context):
    """Sidebar groups with the item matching the current URL marked active; its group opens."""
    path = context['request'].path
    apps = context.get('available_apps') or context.get('app_list') or []
    groups = admin_groups(apps)
    best = None
    for g in groups:
        for m in g['models']:
            url = m.get('admin_url')
            m['label'] = NAV_NAMES.get(m['object_name'], m['name'])
            m['active'] = False
            if url and path.startswith(url) and (best is None or len(url) > len(best['admin_url'])):
                best = m
    if best is not None:
        best['active'] = True
    for g in groups:
        g['open'] = any(m['active'] for m in g['models'])
        g['count'] = len(g['models'])
    return groups


# Friendlier list titles / "add" nouns than Django's verbose names.
TITLES = {'Problem': ('Bài tập', 'bài tập'), 'Judge': ('Máy chấm', 'máy chấm')}


@register.simple_tag
def cba_title(opts, kind):
    t = TITLES.get(opts.object_name)
    if t:
        return t[0] if kind == 'plural' else t[1]
    return opts.verbose_name_plural.capitalize() if kind == 'plural' else opts.verbose_name
