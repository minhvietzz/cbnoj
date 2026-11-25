from django.conf import settings
from django.http import Http404, HttpResponse, HttpResponseRedirect
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET

# Renamed from 'cbn_ui': browsers that prefetched /ui/old/ had been given a stale '0' that kept the old look.
CBN_UI_COOKIE = 'cbn_ui2'
CBN_UI_COOKIE_AGE = 365 * 24 * 60 * 60


def cbn_ui_enabled(request):
    """Cookie `cbn_ui2` ('1' / '0') wins; without it fall back to settings.CBN_UI_DEFAULT (False by default)."""
    value = request.COOKIES.get(CBN_UI_COOKIE)
    if value in ('0', '1'):
        return value == '1'
    return bool(getattr(settings, 'CBN_UI_DEFAULT', False))


def _safe_back(request):
    for candidate in (request.GET.get('next'), request.META.get('HTTP_REFERER')):
        if candidate and url_has_allowed_host_and_scheme(
            candidate, allowed_hosts={request.get_host()}, require_https=request.is_secure(),
        ):
            return candidate
    return '/'


def _is_speculative(request):
    """Prefetch / prerender / preview requests must never change the look: a browser may fire them for any link."""
    purpose = ' '.join(request.headers.get(h, '') for h in ('Sec-Purpose', 'Purpose', 'X-Purpose', 'X-Moz')).lower()
    return any(word in purpose for word in ('prefetch', 'prerender', 'preview'))


@require_GET
def set_ui_mode(request, mode):
    """/ui/new/ and /ui/old/: remember the chosen look for a year, then go back to the page the user came from."""
    if mode not in ('new', 'old'):
        raise Http404()
    if _is_speculative(request):
        response = HttpResponse(status=204)
        response['Cache-Control'] = 'no-store'
        return response
    response = HttpResponseRedirect(_safe_back(request))
    response.set_cookie(CBN_UI_COOKIE, '1' if mode == 'new' else '0', max_age=CBN_UI_COOKIE_AGE,
                        samesite='Lax', secure=request.is_secure())
    return response
