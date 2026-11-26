from django.http import HttpResponse, JsonResponse
from django.views.decorators.http import require_GET

from judge.mcp import auth


def _json(data):
    response = JsonResponse(data)
    response['Cache-Control'] = 'public, max-age=300'
    response['Access-Control-Allow-Origin'] = '*'
    return response


@require_GET
def protected_resource(request, suffix=''):
    if not auth.enabled():
        return HttpResponse(status=404)
    origin = auth.site_origin(request)
    return _json({
        'resource': origin + '/mcp',
        'authorization_servers': [origin],
        'scopes_supported': [auth.SCOPE],
        'bearer_methods_supported': ['header'],
        'resource_name': 'CBNoj',
    })


@require_GET
def authorization_server(request):
    if not auth.enabled():
        return HttpResponse(status=404)
    origin = auth.site_origin(request)
    return _json({
        'issuer': origin,
        'authorization_endpoint': origin + '/o/authorize/',
        'token_endpoint': origin + '/o/token/',
        'registration_endpoint': origin + '/o/register/',
        'revocation_endpoint': origin + '/o/revoke_token/',
        'scopes_supported': [auth.SCOPE],
        'response_types_supported': ['code'],
        'grant_types_supported': ['authorization_code', 'refresh_token'],
        'code_challenge_methods_supported': ['S256'],
        'token_endpoint_auth_methods_supported': ['none', 'client_secret_post', 'client_secret_basic'],
    })
