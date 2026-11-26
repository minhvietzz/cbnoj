from datetime import timedelta
from urllib.parse import urlsplit

from django.conf import settings
from django.utils import timezone
from oauth2_provider.oauth2_validators import OAuth2Validator

from judge.mcp import audit
from judge.mcp.auth import SCOPE as MCP_SCOPE
from judge.mcp.dcr import redirect_allowed


class VNOIOAuthValidator(OAuth2Validator):
    oidc_claim_scope = OAuth2Validator.oidc_claim_scope.copy().update({
        'permissions': 'profile',
    })

    def get_additional_claims(self, request):
        user = request.user
        return {
            'email': user.email,
            'given_name': user.first_name,
            'preferred_username': user.username,
            'permissions': list(user.get_all_permissions()),
        }

    def validate_scopes(self, client_id, scopes, client, request, *args, **kwargs):
        # The `mcp` scope lets a client act as a teacher: only clients whose every redirect address is on the list of
        # trusted AI assistants may ask for it, whoever registered them (admin, user form or dynamic registration).
        if MCP_SCOPE in scopes:
            uris = (client.redirect_uris or '').split()
            if not uris or not all(redirect_allowed(u) for u in uris):
                return False
        return super().validate_scopes(client_id, scopes, client, request, *args, **kwargs)

    # ---- audit trail and refresh-token lifetime (security audit F6) --------------------------------------------------
    @staticmethod
    def _who(request):
        user, client = getattr(request, 'user', None), getattr(request, 'client', None)
        uris = (getattr(client, 'redirect_uris', '') or '').split()
        host = urlsplit(uris[0]).hostname if uris else None
        return 'user=%s app_id=%s app_name=%r redirect_host=%s' % (
            getattr(user, 'username', '?'), getattr(client, 'pk', '?'), (getattr(client, 'name', '') or '')[:60], host)

    def save_authorization_code(self, client_id, code, request, *args, **kwargs):
        result = super().save_authorization_code(client_id, code, request, *args, **kwargs)
        audit.log_event('oauth consent granted: %s scopes=%s', self._who(request), ' '.join(request.scopes or []))
        return result

    def save_bearer_token(self, token, request, *args, **kwargs):
        result = super().save_bearer_token(token, request, *args, **kwargs)
        audit.log_event('oauth token issued: %s grant=%s', self._who(request), getattr(request, 'grant_type', '?'))
        return result

    def validate_refresh_token(self, refresh_token, client, request, *args, **kwargs):
        # django-oauth-toolkit never expires refresh tokens itself. Rotation gives every refresh a new token, so this is
        # a sliding window: a connection unused for MCP_REFRESH_TOKEN_LIFETIME_SECONDS has to be authorised again.
        if not super().validate_refresh_token(refresh_token, client, request, *args, **kwargs):
            return False
        lifetime = getattr(settings, 'MCP_REFRESH_TOKEN_LIFETIME_SECONDS', 0)
        instance = getattr(request, 'refresh_token_instance', None)
        if lifetime and instance is not None and timezone.now() - instance.created > timedelta(seconds=lifetime):
            audit.log_event('oauth refresh refused (expired): %s', self._who(request))
            return False
        return True
