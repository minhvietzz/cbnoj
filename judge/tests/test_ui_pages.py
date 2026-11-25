from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from judge.models import Language, Organization, Problem, ProblemGroup, Profile, Quiz
from judge.views.ui_switch import CBN_UI_COOKIE


@override_settings(CBN_UI_DEFAULT=True)
class UIPagesTestCase(TestCase):
    """The main pages answer 200 for guests/students/admins and link the paper theme."""

    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.admin = User.objects.create_superuser('ui_admin', 'a@example.com', 'pw')
        Profile.objects.create(user=cls.admin)
        cls.student = User.objects.create_user('ui_student', password='pw')
        cls.student_profile = Profile.objects.create(user=cls.student)
        cls.org = Organization.objects.create(name='UI Org', slug='ui-org', short_name='UIO', about='x', is_open=True)
        group = ProblemGroup.objects.create(name='g', full_name='g')
        cls.problem = Problem.objects.create(code='uip', name='UI Problem', description='hello', time_limit=1,
                                             memory_limit=65536, points=10, group=group, is_public=True)
        cls.problem.allowed_languages.set(Language.objects.all())
        cls.quiz = Quiz.objects.create(title='UI Quiz', slug='ui-quiz', is_public=True, creator=cls.admin.profile)

    def check(self, name, *args):
        for who in (None, 'ui_student', 'ui_admin'):
            self.client.logout()
            if who:
                self.client.force_login(get_user_model().objects.get(username=who))
            response = self.client.get(reverse(name, args=args))
            self.assertEqual(response.status_code, 200, (name, who))
            self.assertContains(response, 'cbn-theme.css', msg_prefix='%s/%s' % (name, who))
            self.assertContains(response, 'class="cbn-ui"')
        return response

    def test_home(self):
        response = self.check('home')
        self.assertContains(response, 'lh-band')

    def test_lists(self):
        for name in ('contest_list', 'course_list', 'quiz_list', 'problem_list', 'user_list'):
            self.check(name)

    def test_org(self):
        for name in ('organization_home', 'organization_exams', 'organization_classes',
                     'problem_list_organization', 'contest_list_organization'):
            self.check(name, 'ui-org')
        self.assertContains(self.check('organization_home', 'ui-org'), 'og-logo')

    def test_profile(self):
        self.check('user_page', 'ui_student')

    def test_problem_single_layout(self):
        # every user gets the one two-column layout, whatever the (now unused) problem_ui column says
        for ui in ('old', 'new'):
            Profile.objects.update(problem_ui=ui)
            response = self.check('problem_detail', 'uip')
            self.assertContains(response, 'UI Problem')
            self.assertContains(response, 'ws-crumb')
            self.assertNotContains(response, 'ui-new')


class UiSwitchPrefetchTest(TestCase):
    """A browser prefetching the 'old interface' link must not switch the look for the user."""

    def test_prefetch_does_not_set_the_cookie(self):
        for header in ({'HTTP_SEC_PURPOSE': 'prefetch'}, {'HTTP_PURPOSE': 'prefetch'},
                       {'HTTP_SEC_PURPOSE': 'prefetch;prerender'}):
            response = self.client.get('/ui/old/', **header)
            self.assertEqual(response.status_code, 204)
            self.assertNotIn(CBN_UI_COOKIE, response.cookies)

    def test_a_real_click_still_works(self):
        response = self.client.get('/ui/old/')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.cookies[CBN_UI_COOKIE].value, '0')
