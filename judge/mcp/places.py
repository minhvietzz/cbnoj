"""Where a teacher may put new content (site-wide, an organization they administer, a class they manage).

The rules mirror the checks in the tools (and on the web). Used by `whoami` to list the places, and by the create tools
to pick the destination automatically when the account is allowed to post in exactly one place.
"""
from django.conf import settings

from judge.mcp.registry import ToolError
from judge.models.classroom import ClassMember, MANAGER_ROLES

KIND_NAMES = {'quiz': 'quiz', 'blog': 'bài viết', 'problem': 'bài tập code'}


def _admin_orgs(profile):
    return list(profile.admin_of.all())


def places(ctx, kind):
    """{'site': bool, 'organizations': [Organization], 'classes': [Classroom]} where the account may create `kind`."""
    user, profile = ctx.user, ctx.profile
    orgs, classes, site = [], [], False
    if kind == 'quiz':
        site = bool(user.is_superuser or user.has_perm('judge.add_quiz'))
        orgs = _admin_orgs(profile)
        classes = [m.classroom for m in ClassMember.objects.filter(user=profile, role__in=MANAGER_ROLES)
                   .select_related('classroom')]
    elif kind == 'blog':
        official = getattr(ctx.request, 'official_contest_mode', False)
        site = bool(not official and (user.is_superuser or
                                      profile.problem_count >= settings.VNOJ_BLOG_MIN_PROBLEM_COUNT))
        orgs = _admin_orgs(profile) if user.has_perm('judge.edit_organization_post') else []
    elif kind == 'problem':
        if user.has_perm('judge.edit_own_problem'):
            site = bool(user.has_perm('judge.add_problem'))
            orgs = _admin_orgs(profile) if user.has_perm('judge.create_organization_problem') else []
    return {'site': site, 'organizations': orgs, 'classes': classes}


def describe(ctx):
    """Plain data for `whoami`: for each kind, the places that are open to this account."""
    result = {}
    for kind in KIND_NAMES:
        p = places(ctx, kind)
        item = {'site_wide': p['site'], 'organizations': [{'slug': o.slug, 'name': o.name} for o in p['organizations']]}
        if kind == 'quiz':
            item['classes'] = [{'id': c.id, 'name': c.name} for c in p['classes']]
        result[kind] = item
    return result


def default_destination(ctx, kind):
    """Pick the destination when the caller named none.

    Site-wide allowed -> None (keep the usual default: site-wide). Otherwise exactly one organization/class is chosen
    automatically; several are listed in the error so the model asks the teacher. Nothing available -> None, and the
    tool's own permission message applies. Returns ('organization', Organization) or ('class', Classroom) or None.
    """
    p = places(ctx, kind)
    if p['site']:
        return None
    options = [('organization', o) for o in p['organizations']] + [('class', c) for c in p['classes']]
    if len(options) <= 1:
        return options[0] if options else None
    lines = ['- tổ chức "%s" (organization="%s")' % (o.name, o.slug) if what == 'organization' else
             '- lớp "%s" (class_id=%d)' % (o.name, o.id) for what, o in options]
    raise ToolError('Tài khoản của bạn đăng %s được ở nhiều nơi; hãy hỏi giáo viên muốn đăng ở đâu rồi gọi lại với '
                    'tham số tương ứng:\n%s' % (KIND_NAMES[kind], '\n'.join(lines)))


def where_note(what, obj):
    label = 'tổ chức' if what == 'organization' else 'lớp'
    return 'Tài khoản chỉ được đăng ở một nơi nên đã tự đăng vào %s "%s".' % (label, obj.name)
