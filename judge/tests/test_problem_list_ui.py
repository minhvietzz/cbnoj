from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from judge.models import Language, Problem, ProblemGroup, Profile, Submission


@override_settings(CBN_UI_DEFAULT=True)
class ProblemListUiTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.group = ProblemGroup.objects.create(name='mangx', full_name='Mảng X')
        cls.solved = Problem.objects.create(code='plsolved', name='Solved', group=cls.group, time_limit=1,
                                            memory_limit=65536, points=10, is_public=True)
        cls.todo = Problem.objects.create(code='pltodo', name='Todo', group=cls.group, time_limit=1,
                                          memory_limit=65536, points=10, is_public=True)
        user = User.objects.create_user('pluser', password='x')
        cls.profile = Profile.objects.get_or_create(user=user)[0]
        cls.profile.language = Language.get_default_language()
        cls.profile.save()
        Submission.objects.create(user=cls.profile, problem=cls.solved, language=Language.get_default_language(),
                                  result='AC', status='D', points=10, case_points=10, case_total=10)

    def get(self, query=''):
        self.client.login(username='pluser', password='x')
        return self.client.get(reverse('problem_list') + query)

    def test_group_counts_and_total(self):
        response = self.get()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Mảng X')
        self.assertContains(response, 'pl-n">2<')

    def test_status_filter(self):
        self.assertContains(self.get('?status=unsolved'), 'pltodo')
        self.assertNotContains(self.get('?status=unsolved'), 'plsolved')
        self.assertContains(self.get('?status=solved'), 'plsolved')
        self.assertNotContains(self.get('?status=solved'), 'pltodo')

    def test_problem_page_has_single_layout(self):
        self.client.login(username='pluser', password='x')
        response = self.client.get(reverse('problem_detail', args=['pltodo']))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'ws-crumb')
