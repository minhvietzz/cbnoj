from unittest import skipIf

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import NoReverseMatch, reverse

from judge.models import Course, CourseLesson, CourseRole, NavigationBar, Profile


@skipIf(getattr(settings, 'QUIZ_ENABLED', False), 'only meaningful while the quiz feature is switched off')
class QuizSwitchedOffTest(TestCase):
    """With QUIZ_ENABLED unset (the default) the site must behave as if the quiz feature did not exist."""

    def setUp(self):
        user = get_user_model().objects.create_user(username='member', password='pw')
        self.member = Profile.objects.create(user=user)
        admin = get_user_model().objects.create_superuser(username='root', password='pw', email='r@example.com')
        Profile.objects.create(user=admin)
        self.course = Course.objects.create(name='Tin 12', slug='tin-12', is_public=True)
        CourseRole.objects.create(course=self.course, user=self.member, role='ST')

    def test_pages_are_gone(self):
        self.client.login(username='member', password='pw')
        for path in ('/quizzes/', '/quizzes/me/', '/practice/', '/practice/mistakes/', '/bank/', '/quiz/anything/',
                     '/quiz/anything/attempt/1/', '/course/tin-12/quizzes/'):
            self.assertEqual(self.client.get(path).status_code, 404, path)

    def test_routes_are_not_registered(self):
        for name in ('quiz_list', 'practice', 'bank_list', 'quiz_detail', 'course_quizzes'):
            with self.assertRaises(NoReverseMatch):
                reverse(name, args=['x'] if name in ('quiz_detail', 'course_quizzes') else [])

    def test_menu_entry_is_hidden_but_kept_in_the_database(self):
        NavigationBar.objects.create(key='quizzes', label='Quizzes', path='/quizzes/', regex='^/quizz?(es)?/',
                                     order=10)
        self.assertEqual(self.client.get('/').status_code, 200)
        self.assertNotContains(self.client.get('/'), 'href="/quizzes/"')
        self.assertTrue(NavigationBar.objects.filter(path='/quizzes/').exists())

    def test_courses_still_work_without_the_quiz_tab(self):
        self.client.login(username='member', password='pw')
        for url in (reverse('course_detail', args=['tin-12']), reverse('course_grades', args=['tin-12'])):
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 200, url)
            self.assertNotContains(resp, '/quizzes/')

    def test_admin_has_no_quiz_models(self):
        self.client.login(username='root', password='pw')
        resp = self.client.get('/admin/judge/')
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'quizattempt')
        self.assertContains(resp, 'course')

    def test_lesson_page_renders_for_a_member(self):
        lesson = CourseLesson.objects.create(course=self.course, title='Bai 1', content='noi dung', order=1)
        self.client.login(username='member', password='pw')
        resp = self.client.get(reverse('course_lesson', args=['tin-12', lesson.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'quiz-attempt-row')
