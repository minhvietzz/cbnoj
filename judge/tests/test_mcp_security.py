# flake8: noqa: E501
"""Regression tests for the findings of the 2026-11-26 security audit (OAuth redirect smuggling, self-service OAuth
applications, PKCE plain, protocol robustness, bounded preview)."""
import base64
import hashlib
import json
import time
from datetime import timedelta
from unittest import mock
from urllib.parse import parse_qs, urlparse

from django.core.cache import cache
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone
from oauth2_provider.models import get_access_token_model, get_application_model, get_refresh_token_model

from judge.mcp.dcr import redirect_allowed
from judge.tests.test_mcp_core import make_token, make_user, rpc
from judge.utils.test_gen import generate_preview, validate_spec

GOOGLE = 'https://oauth-redirect.googleusercontent.com/r/'


class RedirectAllowedTest(SimpleTestCase):
    @override_settings(MCP_ALLOWED_REDIRECT_PREFIXES=(GOOGLE, 'https://claude.ai/api/mcp/auth_callback'))
    def test_allowed_and_rejected(self):
        for good in (GOOGLE + 'user_bound_custom-mcp-12733fa300f3d6db98e44973', GOOGLE + 'abc?x=1',
                     'https://claude.ai/api/mcp/auth_callback'):
            self.assertTrue(redirect_allowed(good), good)
        for bad in (GOOGLE + 'x https://evil.example/cb', GOOGLE + 'x\thttps://evil.example', GOOGLE + 'x\r\nSet-Cookie: a=b',
                    GOOGLE + 'x y', GOOGLE + 'x#frag', GOOGLE + '../../x', GOOGLE + 'a/%2e%2e/b', GOOGLE + 'a\\b',
                    'http://oauth-redirect.googleusercontent.com/r/x', 'https://oauth-redirect.googleusercontent.com.evil.example/r/x',
                    'https://oauth-redirect.googleusercontent.com:444/r/x', 'https://evil.example/cb', '', None, 5, GOOGLE + 'a' * 1000,
                    'https://claude.ai@evil.example/api/mcp/auth_callback'):
            self.assertFalse(redirect_allowed(bad), repr(bad)[:80])


@override_settings(MCP_ENABLED=True, MCP_RATE_LIMIT_PER_MINUTE=100000)
class OAuthHardeningTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.teacher = make_user('sec_teacher', ['add_quiz'])
        cls.student = make_user('sec_student')

    def setUp(self):
        cache.clear()

    def register(self, **body):
        return self.client.post('/o/register/', data=json.dumps(body), content_type='application/json')

    def test_dcr_cannot_smuggle_a_second_redirect(self):
        r = self.register(redirect_uris=[GOOGLE + 'x https://evil.example/cb'])
        self.assertEqual(r.status_code, 400, r.content)
        r = self.register(redirect_uris=[GOOGLE + 'ok', GOOGLE + 'y\nhttps://evil.example/cb'])
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json()['redirect_uris'], [GOOGLE + 'ok'])
        self.assertFalse(get_application_model().objects.filter(redirect_uris__contains='evil').exists())

    def test_dcr_deeply_nested_json_is_a_clean_400(self):
        r = self.client.post('/o/register/', data='[' * 200000, content_type='application/json')
        self.assertEqual(r.status_code, 400)

    def test_users_cannot_create_oauth_applications(self):
        self.client.force_login(self.student)
        for path in ('/o/applications/', '/o/applications/register/'):
            self.assertEqual(self.client.get(path).status_code, 404, path)
        r = self.client.post('/o/applications/register/', {
            'name': 'evil', 'client_id': 'evilcid', 'client_secret': 'x' * 20, 'client_type': 'public',
            'authorization_grant_type': 'authorization-code', 'redirect_uris': 'https://evil.example/cb', 'algorithm': ''})
        self.assertEqual(r.status_code, 404)
        self.assertFalse(get_application_model().objects.exists())
        self.assertEqual(self.client.get('/o/authorized_tokens/').status_code, 200, 'users can still revoke their grants')

    def authorize(self, app, **override):
        verifier = 'v' * 64
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
        q = {'client_id': app.client_id, 'response_type': 'code', 'redirect_uri': app.redirect_uris.split()[0],
             'code_challenge': challenge, 'code_challenge_method': 'S256', 'scope': 'mcp'}
        q.update(override)
        return self.client.get('/o/authorize/', {k: v for k, v in q.items() if v is not None})

    def test_mcp_scope_refused_for_clients_with_untrusted_redirects(self):
        Application = get_application_model()
        evil = Application.objects.create(name='evil', client_type='public', authorization_grant_type='authorization-code',
                                          redirect_uris='https://evil.example/cb')
        mixed = Application.objects.create(name='mixed', client_type='public', authorization_grant_type='authorization-code',
                                           redirect_uris=GOOGLE + 'ok https://evil.example/cb')
        good = Application.objects.create(name='good', client_type='public', authorization_grant_type='authorization-code',
                                          redirect_uris=GOOGLE + 'ok')
        self.client.force_login(self.teacher)
        for app in (evil, mixed):
            r = self.authorize(app, redirect_uri=app.redirect_uris.split()[0])
            self.assertEqual(r.status_code, 302, app.name)
            self.assertIn('error=invalid_scope', r['Location'], app.name)
        self.assertEqual(self.authorize(good).status_code, 200)
        self.assertEqual(self.authorize(good, scope=None).status_code, 200, 'default scope is mcp and still valid for a good client')
        r = self.authorize(evil, redirect_uri=evil.redirect_uris, scope=None)
        self.assertIn('error=invalid_scope', r['Location'], 'the default scope is checked too')

    def test_consent_page_warns_and_shows_destination(self):
        good = get_application_model().objects.create(name='Gemini', client_type='public', authorization_grant_type='authorization-code',
                                                      redirect_uris=GOOGLE + 'ok')
        self.client.force_login(self.teacher)
        body = self.authorize(good).content.decode()
        self.assertIn('Chỉ bấm', body)
        self.assertIn(GOOGLE + 'ok', body)

    def test_pkce_plain_refused(self):
        good = get_application_model().objects.create(name='Gemini', client_type='public', authorization_grant_type='authorization-code',
                                                      redirect_uris=GOOGLE + 'ok')
        self.client.force_login(self.teacher)
        r = self.authorize(good, code_challenge='a' * 50, code_challenge_method='plain')
        self.assertEqual(r.status_code, 302)
        self.assertIn('error=invalid_request', r['Location'])
        self.assertEqual(self.authorize(good).status_code, 200)


@override_settings(MCP_ENABLED=True, MCP_RATE_LIMIT_PER_MINUTE=100000)
class ProtocolHardeningTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.teacher = make_user('sec_proto_teacher', ['add_quiz'])
        cls.tok = make_token(cls.teacher, 'sec-proto-token-0123456789')

    def setUp(self):
        cache.clear()

    def post(self, body, token=None, header=None):
        extra = {'HTTP_AUTHORIZATION': header} if header else {'HTTP_AUTHORIZATION': 'Bearer ' + (token or self.tok)}
        return self.client.post('/mcp', data=body, content_type='application/json', **extra)

    def test_deep_json_and_odd_types_do_not_crash(self):
        for body in ('[' * 900000, '{"a":' * 150000, b'\xff\xfe{'):
            self.assertEqual(self.post(body).status_code, 400)
        r = self.post(json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 5}))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['error']['code'], -32600)
        r = self.post(json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': ['x']}))
        self.assertEqual(r.json()['error']['code'], -32600)

    def test_bearer_must_match_exactly(self):
        self.assertEqual(rpc(self.client, self.tok, 'ping').status_code, 200)
        for header in ('Bearer ' + self.tok + '\n', 'Bearer ' + self.tok + ' ', 'Bearer  ' + self.tok, 'bearer ' + self.tok):
            r = self.post(json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'ping'}), header=header)
            self.assertEqual(r.status_code, 401, repr(header))


class PreviewBoundedTest(SimpleTestCase):
    def test_preview_is_time_bounded(self):
        groups = [{'name': 'g%d' % i, 'count': 3, 'params': {}} for i in range(10)]
        spec = validate_spec({'lines': [{'type': 'array', 'len': 700000, 'min': 1, 'max': 99}], 'groups': groups})
        started = time.monotonic()
        preview = generate_preview(spec, budget=0.3)
        self.assertLess(time.monotonic() - started, 4)
        self.assertTrue(any(p.get('skipped') or p.get('partial') for p in preview))
        self.assertEqual(len(preview), 10)

    def test_empty_line_flood_is_capped(self):
        from judge.utils.test_gen import generate_all, SpecError
        spec = validate_spec({'lines': [{'type': 'matrix', 'rows': 10 ** 18, 'cols': 0, 'min': 0, 'max': 0}],
                              'groups': [{'count': 1, 'params': {}}]})
        with self.assertRaises(SpecError) as ctx:
            generate_all(spec)
        self.assertEqual(ctx.exception.code, 'too_big')


@override_settings(MCP_ENABLED=True, MCP_RATE_LIMIT_PER_MINUTE=100000)
class OAuthAuditAndLifetimeTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.teacher = make_user('sec_audit_teacher', ['add_quiz'])

    def setUp(self):
        cache.clear()
        self.verifier = 'v' * 64
        self.challenge = base64.urlsafe_b64encode(hashlib.sha256(self.verifier.encode()).digest()).decode().rstrip('=')
        self.redirect = GOOGLE + 'user_bound_custom-mcp-1'
        self.client_id = self.client.post('/o/register/', data=json.dumps({'redirect_uris': [self.redirect], 'client_name': 'Gemini\nfake'}),
                                          content_type='application/json').json()['client_id']

    def connect(self):
        """Run consent + code exchange as the teacher; returns the token response."""
        self.client.force_login(self.teacher)
        params = {'response_type': 'code', 'client_id': self.client_id, 'redirect_uri': self.redirect, 'scope': 'mcp',
                  'code_challenge': self.challenge, 'code_challenge_method': 'S256', 'allow': 'Authorize'}
        location = self.client.post('/o/authorize/', params)['Location']
        code = parse_qs(urlparse(location).query)['code'][0]
        self.client.logout()
        r = self.client.post('/o/token/', {'grant_type': 'authorization_code', 'code': code, 'redirect_uri': self.redirect,
                                           'client_id': self.client_id, 'code_verifier': self.verifier})
        self.assertEqual(r.status_code, 200, r.content)
        return r.json()

    def refresh(self, token):
        return self.client.post('/o/token/', {'grant_type': 'refresh_token', 'refresh_token': token, 'client_id': self.client_id})

    def test_grants_are_logged_without_secrets(self):
        with mock.patch('judge.oauth_validator.audit.log_event') as log:
            tokens = self.connect()
        lines = [c.args[0] % c.args[1:] for c in log.call_args_list]
        self.assertTrue(any(l.startswith('oauth consent granted') and 'user=sec_audit_teacher' in l and 'scopes=mcp' in l and
                            'redirect_host=oauth-redirect.googleusercontent.com' in l for l in lines), lines)
        self.assertTrue(any(l.startswith('oauth token issued') and 'grant=authorization_code' in l for l in lines), lines)
        blob = '\n'.join(lines)
        self.assertNotIn(tokens['access_token'], blob)
        self.assertNotIn(tokens['refresh_token'], blob)
        self.assertNotIn('\n', blob.split('oauth token issued')[0].split('app_name=')[1].split(' redirect_host')[0], 'client name is escaped')

    @override_settings(MCP_REFRESH_TOKEN_LIFETIME_SECONDS=30 * 24 * 3600)
    def test_unused_connection_expires_but_use_slides_the_window(self):
        tokens = self.connect()
        r = self.refresh(tokens['refresh_token'])
        self.assertEqual(r.status_code, 200, r.content)
        newer = r.json()
        # a refresh token last issued 31 days ago is refused, one issued 29 days ago still works
        get_refresh_token_model().objects.filter(token=newer['refresh_token']).update(created=timezone.now() - timedelta(days=29))
        r = self.refresh(newer['refresh_token'])
        self.assertEqual(r.status_code, 200, r.content)
        newest = r.json()
        get_refresh_token_model().objects.filter(token=newest['refresh_token']).update(created=timezone.now() - timedelta(days=31))
        with mock.patch('judge.oauth_validator.audit.log_event') as log:
            r = self.refresh(newest['refresh_token'])
        self.assertEqual(r.status_code, 400, r.content)
        self.assertEqual(r.json()['error'], 'invalid_grant')
        self.assertTrue(any('refused (expired)' in c.args[0] for c in log.call_args_list))

    @override_settings(MCP_REFRESH_TOKEN_LIFETIME_SECONDS=0)
    def test_lifetime_zero_means_no_limit(self):
        tokens = self.connect()
        get_refresh_token_model().objects.update(created=timezone.now() - timedelta(days=400))
        self.assertEqual(self.refresh(tokens['refresh_token']).status_code, 200)

    def test_user_can_list_and_revoke_connections(self):
        tokens = self.connect()
        self.client.force_login(self.teacher)
        r = self.client.get('/o/authorized_tokens/')
        self.assertEqual(r.status_code, 200)
        access = get_access_token_model().objects.get(token=tokens['access_token'])
        self.assertContains(r, 'Gemini')
        r = self.client.post('/o/authorized_tokens/%d/delete/' % access.pk)
        self.assertEqual(r.status_code, 302)
        self.client.logout()
        self.assertEqual(rpc(self.client, tokens['access_token'], 'ping').status_code, 401, 'revoked token no longer works')
