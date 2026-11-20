from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from judge.models import Course, CourseRole, Profile, Quiz, QuizAttempt, QuizOption, QuizQuestion, QuizViolation
from judge.views.quiz_exam import record_violation


from unittest import skipUnless

from django.conf import settings

# The pages only exist while local_settings.py has QUIZ_ENABLED = True (see dmoj/urls.py).
quiz_enabled = skipUnless(getattr(settings, 'QUIZ_ENABLED', False), 'the quiz feature is switched off')


@quiz_enabled
class ExamTestCase(TestCase):
    def make_user(self, name):
        user = get_user_model().objects.create_user(username=name, password='pw')
        return Profile.objects.create(user=user)

    def setUp(self):
        self.client.defaults['HTTP_ACCEPT_LANGUAGE'] = 'en'   # assertions below read the English text
        self.teacher = self.make_user('teacher')
        self.student = self.make_user('student')
        self.outsider = self.make_user('outsider')
        self.course = Course.objects.create(name='Tin 12', slug='tin-12')
        CourseRole.objects.create(course=self.course, user=self.teacher, role='TE')
        CourseRole.objects.create(course=self.course, user=self.student, role='ST')

        now = timezone.now()
        self.quiz = Quiz.objects.create(
            title='Thi thu 1', slug='thi-thu-1', mode='exam', course=self.course, proctoring='strict',
            max_violations=3, time_limit=50, start_time=now - timedelta(minutes=5),
            end_time=now + timedelta(minutes=60), creator=self.teacher)
        self.choice = self.add_question('single', 'Q1', 0.25, [('A', True), ('B', False)], 1, 'Phần I')
        self.tf = self.add_question('tf4', 'Q2', 1, [('a', True), ('b', False), ('c', True), ('d', False)], 2,
                                    'Phần II')

    def add_question(self, kind, text, points, options, order, section):
        question = QuizQuestion.objects.create(quiz=self.quiz, kind=kind, text=text, points=points, order=order,
                                               section=section)
        for index, (label, correct) in enumerate(options, 1):
            QuizOption.objects.create(question=question, order=index, text=label, is_correct=correct)
        return question

    def attempt(self, **kwargs):
        return QuizAttempt.objects.create(quiz=self.quiz, user=self.student, seed=7, **kwargs)

    def login(self, name):
        self.assertTrue(self.client.login(username=name, password='pw'))

    def quiet_heartbeat(self, attempt):
        """Pretend the last heartbeat was a while ago, so the 3 second rate limit does not interfere."""
        QuizAttempt.objects.filter(pk=attempt.pk).update(last_heartbeat=timezone.now() - timedelta(seconds=30))

    def age_violations(self):
        """Move logged violations into the past so the 3 second de-duplication window does not merge them."""
        QuizViolation.objects.update(created=timezone.now() - timedelta(minutes=5))


class AccessTest(ExamTestCase):
    def test_outsider_cannot_see_exam(self):
        self.login('outsider')
        self.assertEqual(self.client.get(self.quiz.get_absolute_url()).status_code, 404)

    def test_exam_is_never_public(self):
        self.quiz.is_public = True
        self.quiz.save()
        self.assertFalse(self.quiz.is_accessible_by(self.outsider.user))
        self.assertTrue(self.quiz.is_accessible_by(self.student.user))

    def test_course_teacher_manages_exam(self):
        self.assertTrue(self.quiz.is_manageable_by(self.teacher.user))
        self.assertFalse(self.quiz.is_manageable_by(self.student.user))

    def test_start_needs_rules_accepted(self):
        self.login('student')
        url = reverse('quiz_start', args=[self.quiz.slug])
        self.client.post(url)
        self.assertEqual(QuizAttempt.objects.count(), 0)
        resp = self.client.post(url, {'agree': '1'})
        attempt = QuizAttempt.objects.get()
        self.assertRedirects(resp, reverse('quiz_attempt', args=[self.quiz.slug, attempt.id]),
                             fetch_redirect_response=False)

    def test_cannot_start_outside_window(self):
        self.login('student')
        url = reverse('quiz_start', args=[self.quiz.slug])
        now = timezone.now()
        Quiz.objects.filter(pk=self.quiz.pk).update(start_time=now + timedelta(hours=1),
                                                    end_time=now + timedelta(hours=2))
        self.client.post(url, {'agree': '1'})
        Quiz.objects.filter(pk=self.quiz.pk).update(start_time=now - timedelta(hours=2),
                                                    end_time=now - timedelta(hours=1))
        self.client.post(url, {'agree': '1'})
        self.assertEqual(QuizAttempt.objects.count(), 0)

    def test_exam_can_be_taken_once(self):
        self.login('student')
        self.attempt().finish()
        self.client.post(reverse('quiz_start', args=[self.quiz.slug]), {'agree': '1'})
        self.assertEqual(QuizAttempt.objects.count(), 1)


class GradingTest(ExamTestCase):
    def test_deadline_is_earlier_of_limit_and_window_end(self):
        attempt = self.attempt()
        self.assertEqual(attempt.deadline, attempt.started + timedelta(minutes=50))
        Quiz.objects.filter(pk=self.quiz.pk).update(end_time=timezone.now() + timedelta(minutes=10))
        attempt = QuizAttempt.objects.get(pk=attempt.pk)
        self.assertLess(attempt.deadline, attempt.started + timedelta(minutes=11))

    def test_finish_scores_partial_true_false(self):
        attempt = self.attempt()
        options = list(self.tf.options.all())
        # three of four statements judged correctly -> 0.5 of 1 point
        verdicts = {str(options[0].id): True, str(options[1].id): False, str(options[2].id): True,
                    str(options[3].id): True}
        right = self.choice.options.get(is_correct=True)
        attempt.finish({str(self.choice.id): [right.id], str(self.tf.id): verdicts})
        self.assertAlmostEqual(attempt.score, 0.25 + 0.5)
        self.assertEqual(attempt.max_score, 1.25)
        self.assertEqual(attempt.correct_count, 1)
        self.assertEqual(attempt.scores[str(self.tf.id)], 0.5)

    def test_expired_attempts_are_finalized_by_command(self):
        attempt = self.attempt()
        QuizAttempt.objects.filter(pk=attempt.pk).update(started=timezone.now() - timedelta(hours=3))
        Quiz.objects.filter(pk=self.quiz.pk).update(end_time=timezone.now() - timedelta(hours=1))
        call_command('finalize_quiz_attempts', verbosity=0)
        attempt.refresh_from_db()
        self.assertTrue(attempt.is_finished)
        self.assertTrue(attempt.auto_submitted)


class ProctoringTest(ExamTestCase):
    def test_counted_violations_auto_submit_at_limit(self):
        attempt = self.attempt()
        for expected in (1, 2):
            attempt, counted = record_violation(attempt.id, 'tab_hidden')
            self.assertTrue(counted)
            self.assertEqual(attempt.violation_count, expected)
            self.assertFalse(attempt.is_finished)
            self.age_violations()
        attempt, counted = record_violation(attempt.id, 'fullscreen_exit')
        self.assertTrue(attempt.is_finished)
        self.assertTrue(attempt.auto_submitted)

    def test_simultaneous_events_count_once(self):
        attempt = self.attempt()
        record_violation(attempt.id, 'fullscreen_exit')
        attempt, counted = record_violation(attempt.id, 'tab_hidden')
        self.assertFalse(counted)
        self.assertEqual(attempt.violation_count, 1)
        self.assertEqual(attempt.violations.count(), 2)  # still kept as evidence

    def test_copy_is_logged_but_not_counted(self):
        attempt = self.attempt()
        attempt, counted = record_violation(attempt.id, 'copy')
        self.assertFalse(counted)
        self.assertEqual(attempt.violation_count, 0)
        self.assertEqual(attempt.violations.count(), 1)

    def test_light_proctoring_never_counts(self):
        Quiz.objects.filter(pk=self.quiz.pk).update(proctoring='light')
        attempt = self.attempt()
        attempt, counted = record_violation(attempt.id, 'tab_hidden')
        self.assertFalse(counted)
        self.assertEqual(attempt.violation_count, 0)

    def test_second_tab_supersedes_the_first(self):
        self.login('student')
        attempt = self.attempt()
        page = reverse('quiz_attempt', args=[self.quiz.slug, attempt.id])
        beat = reverse('quiz_attempt_heartbeat', args=[self.quiz.slug, attempt.id])
        self.assertEqual(self.client.get(page).status_code, 200)
        attempt.refresh_from_db()
        first_token = attempt.session_key
        self.assertTrue(first_token)
        self.quiet_heartbeat(attempt)
        self.assertEqual(self.client.post(beat, {'attempt_token': first_token}).status_code, 200)

        self.assertEqual(self.client.get(page).status_code, 200)  # a second tab
        attempt.refresh_from_db()
        self.assertNotEqual(attempt.session_key, first_token)
        resp = self.client.post(beat, {'attempt_token': first_token})
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json()['status'], 'superseded')
        self.assertTrue(attempt.violations.filter(kind='second_session', counted=True).exists())
        self.quiet_heartbeat(attempt)
        self.assertEqual(self.client.post(beat, {'attempt_token': attempt.session_key}).status_code, 200)

    def test_event_endpoint_rejects_unknown_kind_and_stale_token(self):
        self.login('student')
        attempt = self.attempt()
        self.client.get(reverse('quiz_attempt', args=[self.quiz.slug, attempt.id]))
        attempt.refresh_from_db()
        event = reverse('quiz_attempt_event', args=[self.quiz.slug, attempt.id])
        self.assertEqual(self.client.post(event, {'attempt_token': attempt.session_key, 'kind': 'nope'}).status_code,
                         400)
        self.assertEqual(self.client.post(event, {'attempt_token': 'stale', 'kind': 'copy'}).status_code, 409)
        resp = self.client.post(event, {'attempt_token': attempt.session_key, 'kind': 'tab_hidden'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['violations'], 1)

    def test_autosave_requires_current_token(self):
        self.login('student')
        attempt = self.attempt()
        self.client.get(reverse('quiz_attempt', args=[self.quiz.slug, attempt.id]))
        attempt.refresh_from_db()
        save = reverse('quiz_attempt_save', args=[self.quiz.slug, attempt.id])
        right = self.choice.options.get(is_correct=True)
        data = {'q%d' % self.choice.id: right.id}
        self.assertEqual(self.client.post(save, dict(data, attempt_token='old')).status_code, 409)
        self.assertEqual(self.client.post(save, dict(data, attempt_token=attempt.session_key)).status_code, 200)
        attempt.refresh_from_db()
        self.assertEqual(attempt.answers[str(self.choice.id)], [right.id])

    def test_late_submit_ignores_posted_answers(self):
        self.login('student')
        attempt = self.attempt()
        right = self.choice.options.get(is_correct=True)
        QuizAttempt.objects.filter(pk=attempt.pk).update(started=timezone.now() - timedelta(minutes=50, seconds=45))
        page = reverse('quiz_attempt', args=[self.quiz.slug, attempt.id])
        self.client.post(page, {'q%d' % self.choice.id: right.id})
        attempt.refresh_from_db()
        self.assertTrue(attempt.is_finished)
        self.assertTrue(attempt.auto_submitted)
        self.assertEqual(attempt.score, 0)


class ExamPageTest(ExamTestCase):
    def get_page(self):
        self.login('student')
        attempt = self.attempt()
        return attempt, self.client.get(reverse('quiz_attempt', args=[self.quiz.slug, attempt.id]))

    def test_page_renders_sections_lock_and_no_answer_key(self):
        attempt, resp = self.get_page()
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('Phần I', html)
        self.assertIn('Phần II', html)
        self.assertIn('id="qz-lock"', html)
        self.assertIn('name="attempt_token"', html)
        self.assertIn('no-store', resp['Cache-Control'])
        # nothing that reveals which option is right may reach the browser during the exam
        for marker in ('is_correct', 'is-correct', 'accepted_answers', 'explanation'):
            self.assertNotIn(marker, html)
        # a true/false question renders one True/False pair per statement
        self.assertEqual(html.count('value="T"'), 4)
        self.assertEqual(html.count('value="F"'), 4)

    def test_inline_scripts_are_valid_javascript(self):
        import re
        import shutil
        import subprocess
        import tempfile
        node = shutil.which('node')
        if node is None:
            self.skipTest('node is not installed')
        _, resp = self.get_page()
        scripts = [s for s in re.findall(r'<script>(.*?)</script>', resp.content.decode(), re.S) if 'qzApi' in s]
        self.assertEqual(len(scripts), 2)  # the exam page and the proctoring lock
        for script in scripts:
            with tempfile.NamedTemporaryFile('w', suffix='.js', delete=False) as f:
                f.write(script)
            result = subprocess.run([node, '--check', f.name], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_practice_quiz_has_no_lock(self):
        Quiz.objects.filter(pk=self.quiz.pk).update(mode='practice', proctoring='off', is_public=True)
        _, resp = self.get_page()
        html = resp.content.decode()
        self.assertNotIn('attempt_token', html)
        self.assertNotIn('qz-secure', html.replace('body.qz-secure', ''))


class ResultReleaseTest(ExamTestCase):
    def test_results_hidden_until_exam_ends(self):
        Quiz.objects.filter(pk=self.quiz.pk).update(results_release='after_end')
        self.quiz.refresh_from_db()
        attempt = self.attempt()
        attempt.finish()
        self.login('student')
        self.assertFalse(self.quiz.results_visible_to(self.student.user))
        self.assertTrue(self.quiz.results_visible_to(self.teacher.user))
        resp = self.client.get(reverse('quiz_result', args=[self.quiz.slug, attempt.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'has been submitted')
        Quiz.objects.filter(pk=self.quiz.pk).update(end_time=timezone.now() - timedelta(minutes=1))
        self.quiz.refresh_from_db()
        self.assertTrue(self.quiz.results_visible_to(self.student.user))
