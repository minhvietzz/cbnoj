import json

from django.test import TestCase, override_settings

from judge.models import (BlogPost, ClassMember, Classroom, Organization, Problem, ProblemGroup, ProblemType, Quiz,
                          RoleInClass)
from judge.tests.test_mcp_core import make_token, make_user
from judge.tests.test_mcp_quiz import GOOD, call


@override_settings(MCP_ENABLED=True, MCP_RATE_LIMIT_PER_MINUTE=1000)
class McpPlacesTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        ProblemGroup.objects.get_or_create(name='Uncategorized', defaults={'full_name': 'Uncategorized'})
        ProblemType.objects.get_or_create(name='uncategorized', defaults={'full_name': 'Uncategorized'})
        cls.org = Organization.objects.create(name='Trường A', slug='truong-a', short_name='TA', about='x')
        cls.org2 = Organization.objects.create(name='Trường B', slug='truong-b', short_name='TB', about='x')
        cls.class_a = Classroom.objects.create(name='10A1', slug='10a1', organization=cls.org, school_year='2026',
                                               join_code='J1')
        cls.class_b = Classroom.objects.create(name='10A2', slug='10a2', organization=cls.org, school_year='2026',
                                               join_code='J2')

        # Administers exactly one organization and has no site-wide rights.
        cls.one_org = make_user('pl_one_org', ['edit_organization_post', 'create_organization_problem',
                                               'edit_own_problem'])
        cls.org.admins.add(cls.one_org.profile)
        cls.one_org_tok = make_token(cls.one_org, 'places-one-org-token-0123456')

        # Administers two organizations.
        cls.two_org = make_user('pl_two_org', ['edit_organization_post'])
        cls.org.admins.add(cls.two_org.profile)
        cls.org2.admins.add(cls.two_org.profile)
        cls.two_org_tok = make_token(cls.two_org, 'places-two-org-token-0123456')

        # Teaches exactly one class, nothing else.
        cls.class_teacher = make_user('pl_class_teacher')
        ClassMember.objects.create(classroom=cls.class_a, user=cls.class_teacher.profile, role=RoleInClass.TEACHER)
        cls.class_tok = make_token(cls.class_teacher, 'places-class-token-01234567')

        # Teaches two classes.
        cls.two_class = make_user('pl_two_class')
        for classroom in (cls.class_a, cls.class_b):
            ClassMember.objects.create(classroom=classroom, user=cls.two_class.profile, role=RoleInClass.HOMEROOM)
        cls.two_class_tok = make_token(cls.two_class, 'places-twoclass-token-012345')

        # Site-wide teacher who also administers an organization.
        cls.site_teacher = make_user('pl_site_teacher', ['add_quiz'])
        cls.org.admins.add(cls.site_teacher.profile)
        cls.site_tok = make_token(cls.site_teacher, 'places-site-token-012345678')

    def test_whoami_lists_places(self):
        error, data = call(self.client, self.one_org_tok, 'whoami')
        self.assertFalse(error)
        places = data['where_can_post']
        self.assertEqual(places['quiz']['site_wide'], False)
        self.assertEqual([o['slug'] for o in places['quiz']['organizations']], ['truong-a'])
        self.assertEqual([o['slug'] for o in places['blog']['organizations']], ['truong-a'])
        self.assertEqual([o['slug'] for o in places['problem']['organizations']], ['truong-a'])
        self.assertEqual(places['problem']['site_wide'], False)
        error, data = call(self.client, self.class_tok, 'whoami')
        self.assertEqual([c['id'] for c in data['where_can_post']['quiz']['classes']], [self.class_a.id])
        self.assertEqual(data['where_can_post']['blog']['organizations'], [])
        error, data = call(self.client, self.site_tok, 'whoami')
        self.assertTrue(data['where_can_post']['quiz']['site_wide'])

    def test_quiz_goes_to_the_only_organization(self):
        error, data = call(self.client, self.one_org_tok, 'quiz_create', {'title': 'Thi A', 'text': GOOD})
        self.assertFalse(error, data)
        self.assertIn('placed', data)
        self.assertEqual(list(Quiz.objects.get(slug=data['slug']).organizations.all()), [self.org])

    def test_quiz_goes_to_the_only_class(self):
        error, data = call(self.client, self.class_tok, 'quiz_create', {'title': 'Thi lớp', 'text': GOOD})
        self.assertFalse(error, data)
        self.assertEqual(list(Quiz.objects.get(slug=data['slug']).classes.all()), [self.class_a])

    def test_several_places_asks_which(self):
        for token in (self.two_class_tok,):
            error, text = call(self.client, token, 'quiz_create', {'title': 'Thi', 'text': GOOD})
            self.assertTrue(error)
            self.assertIn('class_id=%d' % self.class_a.id, text)
            self.assertIn('class_id=%d' % self.class_b.id, text)
        error, text = call(self.client, self.two_org_tok, 'blog_create', {'title': 'T', 'content': 'a'})
        self.assertTrue(error)
        self.assertIn('truong-a', text)
        self.assertIn('truong-b', text)
        self.assertEqual((Quiz.objects.count(), BlogPost.objects.count()), (0, 0))
        # naming one works
        error, data = call(self.client, self.two_org_tok, 'blog_create',
                           {'title': 'T', 'content': 'a', 'organization': 'truong-b'})
        self.assertFalse(error, data)
        self.assertEqual(BlogPost.objects.get(id=data['id']).organization, self.org2)

    def test_blog_goes_to_the_only_organization(self):
        error, data = call(self.client, self.one_org_tok, 'blog_create', {'title': 'Thông báo', 'content': 'nội dung'})
        self.assertFalse(error, data)
        self.assertEqual(BlogPost.objects.get(id=data['id']).organization, self.org)
        self.assertIn('placed', data)

    def test_problem_goes_to_the_only_organization(self):
        error, data = call(self.client, self.one_org_tok, 'problem_create',
                           {'code': 'truonga_tong', 'name': 'Tổng', 'statement': 'Tính a+b.'})
        self.assertFalse(error, data)
        problem = Problem.objects.get(code='truonga_tong')
        self.assertEqual((problem.organization, problem.is_organization_private), (self.org, True))
        self.assertIn('placed', data)

    def test_site_wide_teacher_keeps_site_default(self):
        error, data = call(self.client, self.site_tok, 'quiz_create', {'title': 'Công khai', 'text': GOOD})
        self.assertFalse(error, data)
        self.assertNotIn('placed', data)
        self.assertEqual(list(Quiz.objects.get(slug=data['slug']).organizations.all()), [])

    def test_no_place_keeps_old_error(self):
        nobody = make_user('pl_nobody', ['add_classroom'])
        tok = make_token(nobody, 'places-nobody-token-0123456')
        error, text = call(self.client, tok, 'quiz_create', {'title': 'x', 'text': GOOD})
        self.assertTrue(error)
        self.assertIn('quyền', text)
        self.assertEqual(json.dumps(Quiz.objects.count()), '0')
