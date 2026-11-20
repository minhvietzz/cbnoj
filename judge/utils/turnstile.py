import json
import logging
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django import forms
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

logger = logging.getLogger('judge.turnstile')

VERIFY_URL = 'https://challenges.cloudflare.com/turnstile/v0/siteverify'


def turnstile_enabled():
    return bool(getattr(settings, 'TURNSTILE_SITE_KEY', '') and getattr(settings, 'TURNSTILE_SECRET_KEY', ''))


class TurnstileWidget(forms.Widget):
    """Renders Cloudflare's "I am human" box; the browser script adds the token as `cf-turnstile-response`."""

    def render(self, name, value, attrs=None, renderer=None):
        return format_html(
            '<div class="cf-turnstile" data-sitekey="{}" data-theme="auto"></div>'
            '<script src="https://challenges.cloudflare.com/turnstile/v0/api.js" async defer></script>',
            settings.TURNSTILE_SITE_KEY,
        )

    def value_from_datadict(self, data, files, name):
        return data.get('cf-turnstile-response', '')


class TurnstileField(forms.Field):
    widget = TurnstileWidget
    default_error_messages = {
        'required': _('Please complete the "I am human" check.'),
        'invalid': _('The human check failed. Please try again.'),
    }

    def __init__(self, request=None, **kwargs):
        self.request = request
        kwargs.setdefault('label', '')
        super().__init__(**kwargs)

    def validate(self, value):
        super().validate(value)
        data = {'secret': settings.TURNSTILE_SECRET_KEY, 'response': value}
        if self.request is not None and self.request.META.get('REMOTE_ADDR'):
            data['remoteip'] = self.request.META['REMOTE_ADDR']
        try:
            req = Request(VERIFY_URL, data=urlencode(data).encode(), method='POST')
            with urlopen(req, timeout=8) as resp:
                result = json.loads(resp.read().decode())
        except (URLError, OSError, ValueError):
            logger.exception('Could not reach Cloudflare Turnstile')
            raise ValidationError(self.error_messages['invalid'], code='invalid')
        if not result.get('success'):
            logger.info('Turnstile rejected a token: %s', result.get('error-codes'))
            raise ValidationError(self.error_messages['invalid'], code='invalid')
