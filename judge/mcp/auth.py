import hashlib
import re

from django.conf import settings
from oauth2_provider.models import get_access_token_model

SCOPE = 'mcp'
_BEARER = re.compile(r'\ABearer ([A-Za-z0-9._~+/=-]{8,512})\Z')

TEACHER_PERMISSIONS = (
    'judge.add_quiz',
    'judge.add_problem',
    'judge.add_classroom',
    'judge.create_organization_problem',
    'judge.edit_organization_post',
)


def site_origin(request):
    return request.build_absolute_uri('/').rstrip('/')


def resource_metadata_url(request):
    return site_origin(request) + '/.well-known/oauth-protected-resource'


def is_teacher_account(user):
    """Teachers are accounts that may publish content: staff-like permissions, organization admins or class managers."""
    if not user.is_active:
        return False
    if user.is_superuser:
        return True
    if any(user.has_perm(p) for p in TEACHER_PERMISSIONS):
        return True
    profile = user.profile
    if profile.admin_of.exists():
        return True
    from judge.models.classroom import MANAGER_ROLES, ClassMember
    return ClassMember.objects.filter(user=profile, role__in=MANAGER_ROLES).exists()


def authenticate(request):
    """Return ``(user, None)`` or ``(None, (status, error_code))``."""
    header = request.headers.get('authorization', '')
    match = _BEARER.match(header)
    if not match:
        return None, (401, 'missing_token')
    token_value = match.group(1)
    model = get_access_token_model()
    try:
        token = model.objects.select_related('user').get(
            token_checksum=hashlib.sha256(token_value.encode()).hexdigest(),
        )
    except model.DoesNotExist:
        return None, (401, 'invalid_token')
    if not token.is_valid([SCOPE]) or token.user is None:
        return None, (401, 'invalid_token')
    user = token.user
    if not user.is_active or not hasattr(user, 'profile'):
        return None, (401, 'invalid_token')
    if not is_teacher_account(user):
        return None, (403, 'not_teacher')
    return user, None


def enabled():
    return bool(getattr(settings, 'MCP_ENABLED', False))
