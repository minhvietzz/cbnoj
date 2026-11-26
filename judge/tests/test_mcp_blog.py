from django.core.cache import cache
from django.test import TestCase, override_settings

from judge.mcp.tools.blog import blog_create  # noqa: F401  (ensures the module imports)
from judge.models import BlogPost, Organization
from judge.tests.test_mcp_core import make_token, make_user
from judge.tests.test_mcp_quiz import call


@override_settings(MCP_ENABLED=True, MCP_RATE_LIMIT_PER_MINUTE=1000)
class McpBlogTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='School', slug='school', short_name='SC', about='x')
        cls.org_admin = make_user('blog_org_admin', ['edit_organization_post'])
        cls.org.admins.add(cls.org_admin.profile)
        cls.org_tok = make_token(cls.org_admin, 'blog-orgadmin-token-0123456')
        cls.no_perm_admin = make_user('blog_admin_noperm')
        cls.org.admins.add(cls.no_perm_admin.profile)
        cls.no_perm_tok = make_token(cls.no_perm_admin, 'blog-noperm-token-012345678')
        cls.teacher = make_user('blog_teacher', ['add_quiz'])
        cls.teacher_tok = make_token(cls.teacher, 'blog-teacher-token-01234567')
        cls.solver = make_user('blog_solver', ['add_quiz'])
        cls.solver.profile.problem_count = 10
        cls.solver.profile.save()
        cls.solver_tok = make_token(cls.solver, 'blog-solver-token-012345678')

    def setUp(self):
        cache.clear()

    def test_tools_listed(self):
        from judge.tests.test_mcp_core import rpc
        names = [t['name'] for t in rpc(self.client, self.org_tok, 'tools/list').json()['result']['tools']]
        for name in ('blog_create', 'blog_update', 'blog_list_mine'):
            self.assertIn(name, names)

    def test_organization_draft_by_default(self):
        error, data = call(self.client, self.org_tok, 'blog_create', {
            'title': 'Thông báo thi', 'content': '## Lịch thi\n\nThi ngày **5/12**.', 'organization': 'school'})
        self.assertFalse(error, data)
        post = BlogPost.objects.get(id=data['id'])
        self.assertFalse(post.visible)
        self.assertEqual(post.organization, self.org)
        self.assertEqual(list(post.authors.all()), [self.org_admin.profile])
        self.assertEqual(post.slug, 'school')
        self.assertIn('Lịch thi', post.content)
        self.assertTrue(data['url'].startswith('http://testserver/post/'))
        self.assertIn('nháp', data['next'])

    def test_publish_flag_and_update(self):
        _, data = call(self.client, self.org_tok, 'blog_create',
                       {'title': 'Bài A', 'content': 'v1', 'organization': 'school', 'publish': True})
        self.assertTrue(BlogPost.objects.get(id=data['id']).visible)
        error, data2 = call(self.client, self.org_tok, 'blog_update',
                            {'post_id': data['id'], 'content': 'v2', 'publish': False})
        self.assertFalse(error, data2)
        post = BlogPost.objects.get(id=data['id'])
        self.assertEqual((post.content, post.visible, post.title), ('v2', False, 'Bài A'))

    def test_create_is_idempotent(self):
        args = {'title': 'Lặp', 'content': 'nội dung', 'organization': 'school'}
        _, first = call(self.client, self.org_tok, 'blog_create', args)
        error, second = call(self.client, self.org_tok, 'blog_create', args)
        self.assertFalse(error)
        self.assertEqual(first['id'], second['id'])
        self.assertEqual(BlogPost.objects.count(), 1)

    def test_validation(self):
        self.assertTrue(call(self.client, self.org_tok, 'blog_create',
                             {'title': 'x' * 101, 'content': 'a', 'organization': 'school'})[0])
        self.assertTrue(call(self.client, self.org_tok, 'blog_create',
                             {'title': 'ok', 'content': '   ', 'organization': 'school'})[0])
        self.assertEqual(BlogPost.objects.count(), 0)

    def test_organization_needs_admin_and_permission(self):
        error, _ = call(self.client, self.teacher_tok, 'blog_create',
                        {'title': 'x', 'content': 'y', 'organization': 'school'})
        self.assertTrue(error)
        error, text = call(self.client, self.no_perm_tok, 'blog_create',
                           {'title': 'x', 'content': 'y', 'organization': 'school'})
        self.assertTrue(error)
        self.assertIn('quyền', text)
        self.assertEqual(BlogPost.objects.count(), 0)

    def test_personal_post_needs_solved_problems(self):
        error, text = call(self.client, self.teacher_tok, 'blog_create', {'title': 'Cá nhân', 'content': 'y'})
        self.assertTrue(error)
        self.assertIn('10', text)
        error, data = call(self.client, self.solver_tok, 'blog_create', {'title': 'Cá nhân', 'content': 'y'})
        self.assertFalse(error, data)
        post = BlogPost.objects.get(id=data['id'])
        self.assertEqual((post.visible, post.organization, post.slug), (False, None, 'blog_solver'))

    def test_update_only_own_posts(self):
        _, data = call(self.client, self.org_tok, 'blog_create',
                       {'title': 'Của admin', 'content': 'a', 'organization': 'school'})
        error, _ = call(self.client, self.teacher_tok, 'blog_update', {'post_id': data['id'], 'content': 'hack'})
        self.assertTrue(error)
        error, _ = call(self.client, self.org_tok, 'blog_update', {'post_id': 99999, 'content': 'x'})
        self.assertTrue(error)
        self.assertEqual(BlogPost.objects.get(id=data['id']).content, 'a')

    def test_list_mine(self):
        call(self.client, self.org_tok, 'blog_create', {'title': 'L1', 'content': 'a', 'organization': 'school'})
        call(self.client, self.solver_tok, 'blog_create', {'title': 'L2', 'content': 'a'})
        error, data = call(self.client, self.org_tok, 'blog_list_mine')
        self.assertFalse(error)
        self.assertEqual([p['title'] for p in data['posts']], ['L1'])
