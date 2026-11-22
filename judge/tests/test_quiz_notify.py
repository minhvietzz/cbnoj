from datetime import timedelta
from unittest import skipUnless

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from judge.models import BankQuestion, Notification, Profile, Quiz, QuizAttempt
from judge.tasks.quiz import notify_quiz_results, notify_upcoming_quizzes

# The pages only exist while local_settings.py has QUIZ_ENABLED = True (see dmoj/urls.py).
quiz_enabled = skipUnless(getattr(settings, 'QUIZ_ENABLED', False), 'the quiz feature is switched off')


def make_profile(username, **extra):
    user = get_user_model().objects.create_user(username, password='x', **extra)
    profile, _ = Profile.objects.get_or_create(user=user)
    return profile


class QuizNotificationTest(TestCase):
    def setUp(self):
        cache.clear()
        self.teacher = make_profile('notify_teacher')
        self.student = make_profile('notify_student')
        self.quiz = Quiz.objects.create(
            title='Notify exam', slug='notify-exam', mode='exam', is_public=True, time_limit=45,
            start_time=timezone.now() + timedelta(minutes=20), end_time=timezone.now() + timedelta(hours=2),
            creator=self.teacher,
        )

    def titles(self, profile):
        return list(Notification.objects.filter(recipient=profile).values_list('title', flat=True))

    def test_upcoming_exam_is_announced_once(self):
        notify_upcoming_quizzes()
        self.assertEqual(self.titles(self.student), ['Bài thi sắp bắt đầu'])
        note = Notification.objects.get(recipient=self.student)
        self.assertIn('Notify exam', note.body)
        self.assertIn('45 phút', note.body)
        self.assertEqual(note.url, self.quiz.get_absolute_url())
        notify_upcoming_quizzes()
        self.assertEqual(len(self.titles(self.student)), 1)

    def test_far_away_or_past_exams_are_not_announced(self):
        Quiz.objects.filter(pk=self.quiz.pk).update(start_time=timezone.now() + timedelta(hours=5))
        notify_upcoming_quizzes()
        Quiz.objects.filter(pk=self.quiz.pk).update(start_time=timezone.now() - timedelta(minutes=5))
        notify_upcoming_quizzes()
        self.assertEqual(self.titles(self.student), [])

    def test_private_exam_without_audience_notifies_nobody(self):
        Quiz.objects.filter(pk=self.quiz.pk).update(is_public=False)
        notify_upcoming_quizzes()
        self.assertEqual(self.titles(self.student), [])

    def test_results_notification_goes_to_finished_attempts_only(self):
        QuizAttempt.objects.create(quiz=self.quiz, user=self.student, finished=timezone.now(), seed=1)
        notify_quiz_results(self.quiz.id)
        self.assertEqual(self.titles(self.student), [], 'nothing before the results are published')
        Quiz.objects.filter(pk=self.quiz.pk).update(results_published=True)
        notify_quiz_results(self.quiz.id)
        self.assertEqual(self.titles(self.student), ['Đã có điểm bài thi'])
        self.assertEqual(self.titles(self.teacher), [])


@quiz_enabled
class BankMatrixTest(TestCase):
    def setUp(self):
        self.teacher = make_profile('matrix_teacher', is_superuser=True, is_staff=True)
        self.client.force_login(self.teacher.user)
        for level, count in ((1, 3), (2, 2), (3, 1)):
            for i in range(count):
                BankQuestion.objects.create(
                    kind='single', text='Matrix L%d #%d' % (level, i), level=level,
                    options=[{'text': 'a', 'correct': True}, {'text': 'b', 'correct': False}],
                    content_hash='matrix%d%d' % (level, i),
                )

    def picked(self):
        ids = next((v for v in self.client.session.values() if isinstance(v, list) and v and isinstance(v[0], int)),
                   [])
        found = BankQuestion.objects.filter(id__in=ids)
        return len(ids), {level: found.filter(level=level).count() for level in (1, 2, 3)}

    def post(self, **counts):
        data = {'action': 'matrix'}
        data.update(counts)
        return self.client.post(reverse('bank_compose'), data, follow=True)

    def test_form_is_rendered(self):
        response = self.client.get(reverse('bank_compose'))
        self.assertContains(response, 'name="n1"')

    def test_adds_requested_counts_per_level(self):
        self.post(n1='2', n2='1', n3='1')
        self.assertEqual(self.picked(), (4, {1: 2, 2: 1, 3: 1}))

    def test_shortage_adds_what_exists_and_never_duplicates(self):
        self.post(n1='2', n2='1', n3='1')
        self.post(n1='5')
        self.assertEqual(self.picked(), (5, {1: 3, 2: 1, 3: 1}))

    def test_empty_or_bad_input_changes_nothing(self):
        for counts in ({'n1': '0', 'n2': '0', 'n3': '0'}, {'n1': 'abc', 'n2': '-3', 'tag': 'x'}):
            response = self.post(**counts)
            self.assertEqual(response.status_code, 200)
        self.assertEqual(self.picked()[0], 0)
