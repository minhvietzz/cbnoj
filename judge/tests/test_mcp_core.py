import base64
import hashlib
import json
from datetime import timedelta
from urllib.parse import parse_qs, urlparse

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone
from oauth2_provider.models import get_access_token_model, get_application_model

from judge.models import Profile

GEMINI_REDIRECT = 'https://oauth-redirect.googleusercontent.com/r/user_bound_custom-mcp-123-chuyenbacninh.io.vn'


def make_user(name, perms=()):
    user = get_user_model().objects.create_user(username=name, password='pw')
    Profile.objects.create(user=user)
    for codename in perms:
        user.user_permissions.add(Permission.objects.get(codename=codename, content_type__app_label='judge'))
    return get_user_model().objects.get(pk=user.pk)


def make_token(user, token, scope='mcp', expires_in=3600):
    Application = get_application_model()
    app = Application.objects.create(
        name='t', client_type='public', authorization_grant_type='authorization-code', redirect_uris=GEMINI_REDIRECT,
    )
    get_access_token_model().objects.create(
        user=user, token=token, application=app, scope=scope, expires=timezone.now() + timedelta(seconds=expires_in),
    )
    return token


def rpc(client, token, method, params=None, msg_id=1, **extra):
    body = {'jsonrpc': '2.0', 'method': method}
    if msg_id is not None:
        body['id'] = msg_id
    if params is not None:
        body['params'] = params
    headers = {}
    if token:
        headers['HTTP_AUTHORIZATION'] = 'Bearer ' + token
    return client.post('/mcp', data=json.dumps(body), content_type='application/json', **headers, **extra)


@override_settings(MCP_ENABLED=True)
class McpProtocolTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.teacher = make_user('mcp_teacher', ['add_quiz'])
        cls.student = make_user('mcp_student')
        cls.tok = make_token(cls.teacher, 'teacher-token-0123456789')
        cls.student_tok = make_token(cls.student, 'student-token-0123456789')

    def setUp(self):
        cache.clear()

    @override_settings(MCP_ENABLED=False)
    def test_disabled_is_404(self):
        self.assertEqual(rpc(self.client, self.tok, 'ping').status_code, 404)
        self.assertEqual(self.client.get('/.well-known/oauth-authorization-server').status_code, 404)
        self.assertEqual(self.client.post('/o/register/', '{}', content_type='application/json').status_code, 404)

    def test_requires_token_and_points_to_metadata(self):
        r = rpc(self.client, None, 'ping')
        self.assertEqual(r.status_code, 401)
        self.assertIn('resource_metadata="http://testserver/.well-known/oauth-protected-resource"',
                      r['WWW-Authenticate'])

    def test_bad_expired_or_unscoped_tokens_are_401(self):
        self.assertEqual(rpc(self.client, 'nope-nope-nope-nope', 'ping').status_code, 401)
        expired = make_token(self.teacher, 'expired-token-0123456789', expires_in=-5)
        self.assertEqual(rpc(self.client, expired, 'ping').status_code, 401)
        wrong = make_token(self.teacher, 'wrongscope-token-0123456', scope='profile')
        self.assertEqual(rpc(self.client, wrong, 'ping').status_code, 401)

    def test_old_api_token_header_format_is_not_rejected_by_middleware(self):
        # The legacy APIMiddleware answers 400 to unknown bearer formats; /mcp must be exempt.
        self.assertNotEqual(rpc(self.client, self.tok, 'ping').status_code, 400)

    def test_non_teacher_is_forbidden(self):
        r = rpc(self.client, self.student_tok, 'ping')
        self.assertEqual(r.status_code, 403)

    def test_only_post(self):
        r = self.client.get('/mcp', HTTP_AUTHORIZATION='Bearer ' + self.tok)
        self.assertEqual(r.status_code, 405)

    def test_initialize_echoes_supported_version(self):
        cases = (('2025-06-18', '2025-06-18'), ('2025-03-26', '2025-03-26'), ('1999-01-01', '2025-11-25'))
        for asked, expected in cases:
            r = rpc(self.client, self.tok, 'initialize', {'protocolVersion': asked, 'capabilities': {}})
            result = r.json()['result']
            self.assertEqual(result['protocolVersion'], expected)
            self.assertIn('tools', result['capabilities'])

    def test_notification_gets_202(self):
        r = rpc(self.client, self.tok, 'notifications/initialized', msg_id=None)
        self.assertEqual(r.status_code, 202)

    def test_invalid_json_and_unknown_method(self):
        r = self.client.post('/mcp', '{not json', content_type='application/json',
                             HTTP_AUTHORIZATION='Bearer ' + self.tok)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(rpc(self.client, self.tok, 'nope/nope').json()['error']['code'], -32601)

    def test_tools_list_and_whoami(self):
        r = rpc(self.client, self.tok, 'tools/list')
        names = [t['name'] for t in r.json()['result']['tools']]
        self.assertIn('whoami', names)
        r = rpc(self.client, self.tok, 'tools/call', {'name': 'whoami', 'arguments': {}})
        result = r.json()['result']
        self.assertFalse(result['isError'])
        data = json.loads(result['content'][0]['text'])
        self.assertEqual(data['username'], 'mcp_teacher')
        self.assertIn('đăng quiz/bài thi trắc nghiệm', data['can'])

    def test_tool_errors_are_reported_not_raised(self):
        r = rpc(self.client, self.tok, 'tools/call', {'name': 'khong-co', 'arguments': {}})
        self.assertTrue(r.json()['result']['isError'])
        r = rpc(self.client, self.tok, 'tools/call', {'name': 'whoami', 'arguments': {'x': 1}})
        self.assertTrue(r.json()['result']['isError'])

    @override_settings(MCP_RATE_LIMIT_PER_MINUTE=3)
    def test_rate_limit(self):
        codes = []
        for _ in range(5):
            r = rpc(self.client, self.tok, 'tools/call', {'name': 'whoami', 'arguments': {}})
            codes.append(r.json()['result']['isError'])
        self.assertEqual(codes, [False, False, False, True, True])

    @override_settings(MCP_MAX_BODY_BYTES=50)
    def test_body_limit(self):
        r = rpc(self.client, self.tok, 'tools/call', {'name': 'whoami', 'arguments': {}, 'pad': 'x' * 100})
        self.assertEqual(r.status_code, 413)


@override_settings(MCP_ENABLED=True)
class McpOAuthTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.teacher = make_user('oauth_teacher', ['add_quiz'])

    def setUp(self):
        cache.clear()

    def test_metadata_documents(self):
        pr = self.client.get('/.well-known/oauth-protected-resource').json()
        self.assertEqual(pr['resource'], 'http://testserver/mcp')
        self.assertEqual(pr['authorization_servers'], ['http://testserver'])
        again = self.client.get('/.well-known/oauth-protected-resource/mcp').json()
        self.assertEqual(again['resource'], pr['resource'])
        asm = self.client.get('/.well-known/oauth-authorization-server').json()
        self.assertEqual(asm['registration_endpoint'], 'http://testserver/o/register/')
        self.assertEqual(asm['code_challenge_methods_supported'], ['S256'])

    def register(self, **extra):
        body = {'client_name': 'Gemini', 'redirect_uris': [GEMINI_REDIRECT], 'token_endpoint_auth_method': 'none'}
        body.update(extra)
        return self.client.post('/o/register/', json.dumps(body), content_type='application/json')

    def test_dcr_public_client(self):
        r = self.register()
        self.assertEqual(r.status_code, 201)
        data = r.json()
        self.assertNotIn('client_secret', data)
        app = get_application_model().objects.get(client_id=data['client_id'])
        self.assertEqual(app.client_type, 'public')
        self.assertEqual(app.redirect_uris, GEMINI_REDIRECT)

    def test_dcr_confidential_client_gets_secret_once(self):
        r = self.register(token_endpoint_auth_method='client_secret_post')
        self.assertEqual(r.status_code, 201)
        self.assertTrue(r.json()['client_secret'])

    def test_dcr_rejects_foreign_redirects(self):
        for uri in ('https://evil.example.com/cb', 'http://oauth-redirect.googleusercontent.com/r/x',
                    'https://oauth-redirect.googleusercontent.com.evil.com/r/x', 'javascript:alert(1)'):
            self.assertEqual(self.register(redirect_uris=[uri]).status_code, 400, uri)
        self.assertEqual(self.register(redirect_uris=[]).status_code, 400)
        self.assertEqual(self.register(token_endpoint_auth_method='private_key_jwt').status_code, 400)
        self.assertEqual(get_application_model().objects.count(), 0)

    def test_dcr_keeps_only_allowed_redirects_and_accepts_many(self):
        many = [GEMINI_REDIRECT.replace('123', str(i)) for i in range(8)]
        r = self.register(redirect_uris=many + ['https://evil.example.com/cb'])
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json()['redirect_uris'], many)
        app = get_application_model().objects.get(client_id=r.json()['client_id'])
        self.assertNotIn('evil', app.redirect_uris)
        self.assertEqual(self.register(redirect_uris=many * 3).status_code, 400)

    def test_dcr_is_rate_limited_per_ip(self):
        codes = [self.register().status_code for _ in range(22)]
        self.assertEqual(codes[:20], [201] * 20)
        self.assertEqual(codes[20:], [429, 429])

    def test_full_authorization_code_flow_with_pkce(self):
        client_id = self.register().json()['client_id']
        verifier = 'v' * 64
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
        params = {
            'response_type': 'code', 'client_id': client_id, 'redirect_uri': GEMINI_REDIRECT, 'state': 'xyz',
            'scope': 'mcp', 'code_challenge': challenge, 'code_challenge_method': 'S256',
        }

        # not logged in -> redirected to login
        r = self.client.get('/o/authorize/', params)
        self.assertEqual(r.status_code, 302)
        self.assertIn('login', r['Location'])

        self.client.force_login(self.teacher)
        r = self.client.get('/o/authorize/', params)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Cho phép')
        self.assertContains(r, 'name="code_challenge"')
        self.assertContains(r, 'csrfmiddlewaretoken')

        r = self.client.post('/o/authorize/', dict(params, allow='Authorize'))
        self.assertEqual(r.status_code, 302)
        location = urlparse(r['Location'])
        self.assertTrue(r['Location'].startswith(GEMINI_REDIRECT))
        query = parse_qs(location.query)
        self.assertEqual(query['state'], ['xyz'])
        code = query['code'][0]

        self.client.logout()
        # wrong verifier is refused
        bad = self.client.post('/o/token/', {
            'grant_type': 'authorization_code', 'code': code, 'redirect_uri': GEMINI_REDIRECT,
            'client_id': client_id, 'code_verifier': 'w' * 64,
        })
        self.assertEqual(bad.status_code, 400)

        # the code is single use: authorize again for a clean code
        self.client.force_login(self.teacher)
        location = self.client.post('/o/authorize/', dict(params, allow='Authorize'))['Location']
        code = parse_qs(urlparse(location).query)['code'][0]
        self.client.logout()
        r = self.client.post('/o/token/', {
            'grant_type': 'authorization_code', 'code': code, 'redirect_uri': GEMINI_REDIRECT,
            'client_id': client_id, 'code_verifier': verifier,
        })
        self.assertEqual(r.status_code, 200, r.content)
        tokens = r.json()
        self.assertEqual(tokens['scope'], 'mcp')
        self.assertLessEqual(tokens['expires_in'], 3600)
        self.assertTrue(tokens['refresh_token'])

        # the access token works on /mcp
        r = rpc(self.client, tokens['access_token'], 'tools/call', {'name': 'whoami', 'arguments': {}})
        self.assertEqual(json.loads(r.json()['result']['content'][0]['text'])['username'], 'oauth_teacher')

        # refresh works too
        r = self.client.post('/o/token/', {
            'grant_type': 'refresh_token', 'refresh_token': tokens['refresh_token'], 'client_id': client_id,
        })
        self.assertEqual(r.status_code, 200, r.content)

    def test_pkce_is_required(self):
        client_id = self.register().json()['client_id']
        self.client.force_login(self.teacher)
        r = self.client.get('/o/authorize/', {
            'response_type': 'code', 'client_id': client_id, 'redirect_uri': GEMINI_REDIRECT, 'scope': 'mcp',
        })
        self.assertNotEqual(r.status_code, 200)
