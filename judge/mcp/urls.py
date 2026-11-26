from django.urls import path, re_path

from judge.mcp import dcr, oauth_meta, protocol

urlpatterns = [
    re_path(r'^mcp/?$', protocol.mcp_endpoint, name='mcp_endpoint'),
    path('.well-known/oauth-protected-resource', oauth_meta.protected_resource, name='mcp_protected_resource'),
    re_path(r'^\.well-known/oauth-protected-resource/(?P<suffix>.+)$', oauth_meta.protected_resource),
    path('.well-known/oauth-authorization-server', oauth_meta.authorization_server, name='mcp_auth_server'),
    path('o/register/', dcr.register, name='mcp_register'),
]
