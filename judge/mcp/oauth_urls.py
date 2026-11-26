"""The OAuth2 endpoints of django-oauth-toolkit WITHOUT its application management pages.

With the stock urls any logged-in user can open /o/applications/register/ and create an OAuth client with an arbitrary
redirect address. Clients are created by dynamic registration (restricted to trusted AI assistants, see dcr.py) or by an
administrator in the Django admin. Users keep the page that lists and revokes the connections they granted."""
from oauth2_provider import urls as dot_urls

app_name = 'oauth2_provider'

KEEP_MANAGEMENT = {'authorized-token-list', 'authorized-token-delete'}

urlpatterns = [
    *dot_urls.base_urlpatterns,
    *[p for p in dot_urls.management_urlpatterns if p.name in KEEP_MANAGEMENT],
    *dot_urls.oidc_urlpatterns,
]
