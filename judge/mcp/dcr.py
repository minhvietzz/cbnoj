"""RFC 7591 dynamic client registration, restricted to a whitelist of redirect URIs (Gemini, Claude)."""
import json
from datetime import timedelta
from urllib.parse import urlsplit

from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from oauth2_provider.models import get_access_token_model, get_application_model

from judge.mcp import audit, auth

MAX_APPLICATIONS = 2000
PER_IP_PER_HOUR = 20
MAX_REDIRECT_URIS = 20


def _error(code, description, status=400):
    return JsonResponse({'error': code, 'error_description': description}, status=status)


def redirect_allowed(uri):
    """True only for a clean https URL whose host is the host of an allowed prefix and that starts with that prefix.

    The URI is later stored in a whitespace-separated field, so any whitespace or control character would let a client
    smuggle a second, unvetted redirect address in the same string."""
    if not isinstance(uri, str) or not 0 < len(uri) <= 1000:
        return False
    # printable ASCII only: str.split() (used by oauth2_provider) also splits on U+00A0, U+2028 and other Unicode spaces
    if any(not 33 <= ord(c) <= 126 or c in '\\#' for c in uri):
        return False
    try:
        parts = urlsplit(uri)
        port = parts.port
    except ValueError:
        return False
    if parts.scheme != 'https' or port is not None or '@' in parts.netloc:
        return False
    if any(seg in ('.', '..') or seg.lower() in ('%2e', '%2e%2e') for seg in parts.path.split('/')):
        return False
    for prefix in getattr(settings, 'MCP_ALLOWED_REDIRECT_PREFIXES', ()):
        if uri.startswith(prefix) and parts.hostname == urlsplit(prefix).hostname:
            return True
    return False


def _purge_stale(Application):
    """Drop dynamically registered apps that never obtained a token for two days."""
    cutoff = timezone.now() - timedelta(days=2)
    token_model = get_access_token_model()
    used = token_model.objects.values_list('application_id', flat=True)
    Application.objects.filter(user__isnull=True, created__lt=cutoff).exclude(id__in=used).delete()


@csrf_exempt
def register(request):
    if not auth.enabled():
        return HttpResponse(status=404)
    if request.method != 'POST':
        response = HttpResponse(status=405)
        response['Allow'] = 'POST'
        return response
    if audit.rate_limited('dcr:%s' % request.META.get('REMOTE_ADDR', '?'), PER_IP_PER_HOUR, 3600):
        return _error('invalid_client_metadata', 'Too many registrations, try again later.', 429)
    try:
        data = json.loads(request.body.decode('utf-8'))
        assert isinstance(data, dict)
    except (ValueError, UnicodeDecodeError, AssertionError, RecursionError):
        return _error('invalid_client_metadata', 'Body must be a JSON object.')

    uris = data.get('redirect_uris')
    if not isinstance(uris, list) or not uris or len(uris) > MAX_REDIRECT_URIS or \
            not all(isinstance(u, str) for u in uris):
        audit.log_event('dcr rejected: bad redirect_uris shape (%s, count=%s)', type(uris).__name__,
                        len(uris) if isinstance(uris, list) else '-')
        return _error('invalid_redirect_uri', 'redirect_uris must be a list of 1-%d strings.' % MAX_REDIRECT_URIS)
    # Google registers several redirect URIs at once (production, sandbox...). Keep only the ones we trust.
    allowed = [u for u in uris if redirect_allowed(u)]
    if not allowed:
        audit.log_event('dcr rejected: no allowed redirect_uri among %s', [u[:120] for u in uris])
        return _error('invalid_redirect_uri', 'redirect_uri is not on the allowed list of AI clients.')
    dropped = len(uris) - len(allowed)
    if dropped:
        audit.log_event('dcr: dropped %d redirect_uri not on the allowed list: %s', dropped,
                        [u[:120] for u in uris if not redirect_allowed(u)])
    uris = allowed
    method = data.get('token_endpoint_auth_method', 'none')
    if method not in ('none', 'client_secret_post', 'client_secret_basic'):
        return _error('invalid_client_metadata', 'Unsupported token_endpoint_auth_method.')

    Application = get_application_model()
    _purge_stale(Application)
    if Application.objects.count() >= MAX_APPLICATIONS:
        return _error('invalid_client_metadata', 'Registration is closed.', 503)

    public = method == 'none'
    app = Application(
        name=str(data.get('client_name') or 'MCP client')[:100],
        client_type=Application.CLIENT_PUBLIC if public else Application.CLIENT_CONFIDENTIAL,
        authorization_grant_type=Application.GRANT_AUTHORIZATION_CODE,
        redirect_uris=' '.join(uris),
        skip_authorization=False,
    )
    secret = None
    if public:
        app.client_secret = ''
    else:
        secret = app.client_secret  # plaintext; hashed when saved
    app.save()

    body = {
        'client_id': app.client_id,
        'client_id_issued_at': int(timezone.now().timestamp()),
        'client_name': app.name,
        'redirect_uris': uris,
        'grant_types': ['authorization_code', 'refresh_token'],
        'response_types': ['code'],
        'token_endpoint_auth_method': method,
        'scope': auth.SCOPE,
    }
    if secret:
        body['client_secret'] = secret
        body['client_secret_expires_at'] = 0
    response = JsonResponse(body, status=201)
    response['Cache-Control'] = 'no-store'
    return response
