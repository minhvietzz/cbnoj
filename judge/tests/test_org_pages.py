from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from judge.models import ClassMember, Classroom, Organization, Profile, Quiz, QuizAttempt, RoleInClass
from judge.utils import classroom as stats


def make_profile(username, **extra):
    user = get_user_model().objects.create_user(username, password='x', email=username + '@example.com', **extra)
    profile, _ = Profile.objects.get_or_create(user=user)
    return profile


class OrganizationPagesTest(TestCase):
    def setUp(self):
        cache.clear()
        self.org = Organization.objects.create(name='School', slug='school', short_name='SC', about='x', is_open=True)
        self.admin = make_profile('og_admin')
        self.org.admins.add(self.admin)
        self.s1 = make_profile('og_s1', first_name='Nguyen Minh Anh')
        self.s2 = make_profile('og_s2')
        self.outsider = make_profile('og_out')
        for p in (self.admin, self.s1, self.s2):
            p.organizations.add(self.org)
        self.classroom = Classroom.objects.create(name='10A1', slug='10a1', organization=self.org)
        ClassMember.objects.create(classroom=self.classroom, user=self.admin, role=RoleInClass.HOMEROOM)
        ClassMember.objects.create(classroom=self.classroom, user=self.s1, role=RoleInClass.STUDENT)
        self.quiz = Quiz.objects.create(title='Midterm', slug='midterm', mode='exam', is_public=True, time_limit=45,
                                        start_time=timezone.now() - timedelta(hours=3),
                                        end_time=timezone.now() - timedelta(hours=1))
        self.quiz.classes.add(self.classroom)

    def login(self, profile):
        self.client.force_login(profile.user)

    def test_home_and_header(self):
        self.login(self.s1)
        response = self.client.get(reverse('organization_home', args=['school']))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'og-head')
        self.assertContains(response, '10A1')

    def test_outsider_sees_no_classes(self):
        self.login(self.outsider)
        response = self.client.get(reverse('organization_home', args=['school']))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, '10A1')

    def test_members_filters(self):
        self.login(self.admin)
        url = reverse('organization_users', args=['school'])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Nguyen Minh Anh')
        names = [r['username'] for r in response.context['rows']]
        self.assertEqual(sorted(names), ['og_admin', 'og_s1', 'og_s2'])
        self.assertEqual([r['username'] for r in self.client.get(url, {'q': 'minh'}).context['rows']], ['og_s1'])
        by_name = self.client.get(url, {'q': 'minh'}).context['rows']
        self.assertEqual([r['username'] for r in by_name], ['og_s1'])
        filtered = self.client.get(url, {'class': '10a1', 'role': 'student'}).context['rows']
        self.assertEqual([r['username'] for r in filtered], ['og_s1'])
        self.assertEqual([r['username'] for r in self.client.get(url, {'role': 'admin'}).context['rows']], ['og_admin'])

    def test_members_classes_hidden_from_outsiders(self):
        self.login(self.outsider)
        response = self.client.get(reverse('organization_users', args=['school']), {'class': '10a1'})
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, '10A1')

    def test_exams_page_filters(self):
        self.login(self.admin)
        url = reverse('organization_exams', args=['school'])
        response = self.client.get(url)
        self.assertEqual([e['name'] for e in response.context['exams']], ['Midterm'])
        self.assertEqual(response.context['exams'][0]['state'], 'ended')
        self.assertEqual(self.client.get(url, {'state': 'live'}).context['exams'], [])
        self.assertEqual(len(self.client.get(url, {'class': '10a1'}).context['exams']), 1)

    def test_org_list_and_classes(self):
        self.login(self.admin)
        self.assertEqual(self.client.get(reverse('organization_list')).status_code, 200)
        self.assertContains(self.client.get(reverse('organization_classes', args=['school'])), '10A1')

    def test_needs_support_counts_missed_exams(self):
        rows = stats.needs_support(self.classroom)
        self.assertEqual([(r['profile'].id, r['missed']) for r in rows], [(self.s1.id, 1)])
        QuizAttempt.objects.create(quiz=self.quiz, user=self.s1, seed=1, question_count=1)
        stats.missed_exams(self.classroom)
        self.assertEqual(stats.missed_exams(self.classroom), {})

    def test_quiz_list_subject_counts(self):
        self.login(self.s1)
        response = self.client.get(reverse('quiz_list'))
        self.assertEqual(response.status_code, 200)
        self.assertIn('subject_counts', response.context)
