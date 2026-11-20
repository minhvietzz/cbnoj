from datetime import timedelta
from unittest import skipUnless

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from judge.models import (BankQuestion, BankTag, Course, CourseRole, Profile, Quiz, QuizAttempt, QuizOption,
                          QuizProfileStat, QuizQuestion)
from judge.utils import practice, quiz_stats


# The pages only exist while local_settings.py has QUIZ_ENABLED = True (see dmoj/urls.py).
quiz_enabled = skipUnless(getattr(settings, 'QUIZ_ENABLED', False), 'the quiz feature is switched off')


@quiz_enabled
class PracticeTestCase(TestCase):
    def make_user(self, name):
        user = get_user_model().objects.create_user(username=name, password='pw')
        return Profile.objects.create(user=user)

    def setUp(self):
        self.client.defaults['HTTP_ACCEPT_LANGUAGE'] = 'en'   # assertions below read the English text
        self.alice = self.make_user('alice')
        self.bob = self.make_user('bob')
        self.outsider = self.make_user('outsider')
        course = Course.objects.create(name='Tin 12', slug='tin-12')
        CourseRole.objects.create(course=course, user=self.alice, role='ST')
        CourseRole.objects.create(course=course, user=self.bob, role='ST')
        self.net = BankTag.objects.create(name='Mạng', group='topic')
        self.py = BankTag.objects.create(name='Python', group='topic')
        self.ict = BankTag.objects.create(name='Tin học ứng dụng', group='track')
        self.questions = []
        for number in range(1, 9):
            self.questions.append(self.bank('net-%d' % number, [self.net, self.ict], level=1 + number % 3))
        for number in range(1, 5):
            self.questions.append(self.bank('py-%d' % number, [self.py], level=2))
        self.tf = self.bank('tf', [self.net], kind='tf4', options=[('a', True), ('b', False), ('c', True),
                                                                   ('d', False)], explanation='Because.')

    def bank(self, text, tags, kind='single', level=1, options=None, explanation=''):
        options = options or [('A', True), ('B', False)]
        bank = BankQuestion.objects.create(
            kind=kind, text=text, level=level, content_hash=text, explanation=explanation,
            options=[{'text': t, 'correct': c} for t, c in options])
        bank.tags.add(*tags)
        return bank

    def login(self, name):
        self.assertTrue(self.client.login(username=name, password='pw'))

    def start(self, **data):
        self.login('alice')
        resp = self.client.post(reverse('practice'), dict({'count': 5, 'level': 0, 'kinds': ''}, **data))
        self.assertEqual(resp.status_code, 302, resp.content[:300])
        return resp

    def last_attempt(self):
        return QuizAttempt.objects.order_by('-id').first()

    def finish(self, attempt, right_texts):
        """Answer the attempt: questions whose text is in `right_texts` correctly, the rest wrongly."""
        answers = {}
        for question in attempt.quiz.questions.all():
            options = list(question.options.all())
            good = next(o for o in options if o.is_correct)
            bad = next(o for o in options if not o.is_correct)
            answers[str(question.id)] = [good.id if question.text in right_texts else bad.id]
        attempt.finish(answers)


class SetupTest(PracticeTestCase):
    def test_only_class_members_can_practice(self):
        self.login('outsider')
        self.assertEqual(self.client.get(reverse('practice')).status_code, 403)
        self.assertEqual(self.client.get(reverse('practice_mistakes')).status_code, 403)
        self.login('alice')
        self.assertEqual(self.client.get(reverse('practice')).status_code, 200)

    def test_setup_page_lists_tags(self):
        self.login('alice')
        resp = self.client.get(reverse('practice'))
        self.assertContains(resp, 'Mạng')
        self.assertContains(resp, 'Tin học ứng dụng')

    def test_builds_private_quiz_and_attempt_filtered_by_topic(self):
        resp = self.start(tags=[self.py.id], count=5)
        attempt = self.last_attempt()
        self.assertRedirects(resp, reverse('quiz_attempt', args=[attempt.quiz.slug, attempt.id]),
                             fetch_redirect_response=False)
        quiz = attempt.quiz
        self.assertEqual(quiz.mode, 'personal')
        self.assertEqual(quiz.creator, self.alice)
        self.assertFalse(quiz.is_public)
        self.assertEqual(quiz.questions.count(), 4)  # only 4 Python questions exist
        self.assertTrue(all(q.text.startswith('py-') for q in quiz.questions.all()))
        self.assertTrue(all(q.bank_question_id for q in quiz.questions.all()))

    def test_track_and_level_and_kind_filters(self):
        self.start(tracks=[self.ict.id], level=1, count=5)
        texts = [q.text for q in self.last_attempt().quiz.questions.all()]
        self.assertTrue(texts and all(t.startswith('net-') for t in texts))
        banks = BankQuestion.objects.filter(text__in=texts)
        self.assertTrue(all(b.level == 1 for b in banks))

        self.start(kinds='tf')
        self.assertEqual([q.kind for q in self.last_attempt().quiz.questions.all()], ['tf4'])

    def test_count_is_clamped_and_empty_selection_is_refused(self):
        self.start(count=999)
        self.assertLessEqual(self.last_attempt().quiz.questions.count(), practice.MAX_COUNT)
        before = Quiz.objects.count()
        self.login('alice')
        resp = self.client.post(reverse('practice'), {'tags': [self.py.id], 'level': 3, 'count': 5})
        self.assertRedirects(resp, reverse('practice'), fetch_redirect_response=False)
        self.assertEqual(Quiz.objects.count(), before)

    def test_unmastered_questions_come_first(self):
        net_questions = [q for q in self.questions if q.text.startswith('net-')]
        mastered = net_questions[:6]
        self.start(tags=[self.net.id], kinds='choice', count=8)
        self.finish(self.last_attempt(), {q.text for q in mastered})
        for _ in range(5):   # 8 net questions, 6 mastered: asking for 2 must return exactly the 2 unmastered ones
            picked = practice.pick_questions(self.alice, tag_ids=[self.net.id], kinds='choice', count=5,
                                             prefer_new=True)
            self.assertEqual(len(picked), 5)
            self.assertTrue({q.text for q in net_questions[6:]} <= {q.text for q in picked})

    def test_personal_quiz_is_private_and_unlisted(self):
        self.start(tags=[self.py.id])
        quiz = self.last_attempt().quiz
        self.login('bob')
        self.assertEqual(self.client.get(quiz.get_absolute_url()).status_code, 404)
        self.login('alice')
        self.assertEqual(self.client.get(quiz.get_absolute_url()).status_code, 200)
        self.assertNotContains(self.client.get(reverse('quiz_list')), quiz.title)

    def test_attempt_page_shows_check_buttons_but_not_the_key(self):
        self.start(tags=[self.net.id], kinds='tf')
        attempt = self.last_attempt()
        resp = self.client.get(reverse('quiz_attempt', args=[attempt.quiz.slug, attempt.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'qz-check')
        self.assertContains(resp, 'id="explain')          # explanation is in the page, hidden until checked
        self.assertNotContains(resp, 'is_correct')


class PageScriptTest(PracticeTestCase):
    def test_inline_scripts_are_valid_javascript(self):
        import re
        import shutil
        import subprocess
        import tempfile
        node = shutil.which('node')
        if node is None:
            self.skipTest('node is not installed')
        self.start(tags=[self.net.id], count=5)
        attempt = self.last_attempt()
        html = self.client.get(reverse('quiz_attempt', args=[attempt.quiz.slug, attempt.id])).content.decode()
        scripts = [s for s in re.findall(r'<script>(.*?)</script>', html, re.S) if 'checkUrl' in s]
        self.assertEqual(len(scripts), 1)
        with tempfile.NamedTemporaryFile('w', suffix='.js', delete=False) as f:
            f.write(scripts[0])
        result = subprocess.run([node, '--check', f.name], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


class CheckTest(PracticeTestCase):
    def check_url(self, attempt):
        return reverse('quiz_attempt_check', args=[attempt.quiz.slug, attempt.id])

    def test_check_single_choice_reveals_key_and_saves_answer(self):
        self.start(tags=[self.py.id])
        attempt = self.last_attempt()
        question = attempt.quiz.questions.first()
        good = question.options.get(is_correct=True)
        bad = question.options.get(is_correct=False)
        resp = self.client.post(self.check_url(attempt), {'question': question.id, 'q%d' % question.id: bad.id})
        data = resp.json()
        self.assertEqual((data['fraction'], data['correct']), (0.0, [good.id]))
        attempt.refresh_from_db()
        self.assertEqual(attempt.answers[str(question.id)], [bad.id])
        resp = self.client.post(self.check_url(attempt), {'question': question.id, 'q%d' % question.id: good.id})
        self.assertEqual(resp.json()['fraction'], 1.0)

    def test_check_true_false_partial_credit(self):
        self.start(tags=[self.net.id], kinds='tf')
        attempt = self.last_attempt()
        question = attempt.quiz.questions.get()
        options = list(question.options.all())
        post = {'question': question.id}
        for index, option in enumerate(options):   # judge 3 of 4 correctly: flip the first statement
            truth = option.is_correct if index else not option.is_correct
            post['q%d_%d' % (question.id, option.id)] = 'T' if truth else 'F'
        data = self.client.post(self.check_url(attempt), post).json()
        self.assertEqual(data['fraction'], 0.5)
        self.assertEqual(data['points'], 0.5)
        self.assertEqual(data['tf'], {str(o.id): o.is_correct for o in options})

    def test_check_is_refused_for_class_quizzes_finished_attempts_and_foreign_attempts(self):
        self.start(tags=[self.py.id])
        attempt = self.last_attempt()
        question = attempt.quiz.questions.first()
        self.login('bob')
        self.assertEqual(self.client.post(self.check_url(attempt), {'question': question.id}).status_code, 404)

        self.login('alice')
        Quiz.objects.filter(pk=attempt.quiz_id).update(mode='practice', is_public=True)
        self.assertEqual(self.client.post(self.check_url(attempt), {'question': question.id}).status_code, 400)

        Quiz.objects.filter(pk=attempt.quiz_id).update(mode='personal')
        attempt.refresh_from_db()
        attempt.finish()
        self.assertEqual(self.client.post(self.check_url(attempt), {'question': question.id}).status_code, 400)


class MistakeNotebookTest(PracticeTestCase):
    def test_wrong_answers_enter_the_notebook_and_leave_when_mastered(self):
        self.start(tags=[self.py.id])
        self.finish(self.last_attempt(), {'py-1', 'py-2'})        # py-3 and py-4 wrong
        rows = practice.mistakes(self.alice)
        self.assertEqual(sorted(r['bank'].text for r in rows), ['py-3', 'py-4'])
        self.assertEqual([r['wrong'] for r in rows], [1, 1])

        self.start(tags=[self.py.id])
        self.finish(self.last_attempt(), {'py-1', 'py-2', 'py-3'})   # py-3 mastered, py-4 wrong again
        rows = practice.mistakes(self.alice)
        self.assertEqual([(r['bank'].text, r['wrong']) for r in rows], [('py-4', 2)])

    def test_notebook_page_and_retry(self):
        self.start(tags=[self.py.id])
        self.finish(self.last_attempt(), {'py-1'})
        resp = self.client.get(reverse('practice_mistakes'))
        self.assertContains(resp, 'py-2')
        self.assertContains(resp, 'py-4')

        wanted = BankQuestion.objects.get(text='py-2')
        self.client.post(reverse('practice'), {'source': 'mistakes', 'ids': [wanted.id]})
        quiz = self.last_attempt().quiz
        self.assertEqual([q.text for q in quiz.questions.all()], ['py-2'])
        self.client.post(reverse('practice'), {'source': 'mistakes'})   # nothing ticked = all of them
        self.assertEqual(self.last_attempt().quiz.questions.count(), 3)

    def test_empty_notebook(self):
        self.login('alice')
        self.assertContains(self.client.get(reverse('practice_mistakes')), 'notebook is empty')

    def test_unreleased_exam_mistakes_stay_hidden(self):
        now = timezone.now()
        course = Course.objects.get(slug='tin-12')
        exam = Quiz.objects.create(title='Exam', slug='exam', mode='exam', course=course, results_release='manual',
                                   start_time=now - timedelta(hours=2), end_time=now + timedelta(hours=2))
        bank = BankQuestion.objects.get(text='py-1')
        question = QuizQuestion.objects.create(quiz=exam, kind='single', text='py-1', bank_question=bank)
        QuizOption.objects.create(question=question, order=1, text='A', is_correct=True)
        QuizOption.objects.create(question=question, order=2, text='B', is_correct=False)
        attempt = QuizAttempt.objects.create(quiz=exam, user=self.alice, seed=1)
        attempt.finish({str(question.id): [question.options.get(is_correct=False).id]})
        self.assertEqual(practice.mistakes(self.alice), [])
        Quiz.objects.filter(pk=exam.pk).update(results_published=True)
        self.assertEqual([r['bank'].text for r in practice.mistakes(self.alice)], ['py-1'])


class StatsAndCleanupTest(PracticeTestCase):
    def test_practice_counts_in_progress_statistics(self):
        self.start(tags=[self.net.id], count=9)
        attempt = self.last_attempt()
        self.assertEqual(attempt.quiz.questions.count(), 9)
        right = {q.text for q in attempt.quiz.questions.exclude(kind='tf4')}
        self.finish_with_tf(attempt, right)
        stat = QuizProfileStat.objects.get(user=self.alice)
        self.assertEqual((stat.practice_sessions, stat.exams_taken), (1, 0))
        names = [name for name, _acc, _n in quiz_stats.topic_breakdown(self.alice)]
        self.assertIn('Mạng', names)

    def finish_with_tf(self, attempt, right_texts):
        answers = {}
        for question in attempt.quiz.questions.all():
            options = list(question.options.all())
            if question.kind == 'tf4':
                answers[str(question.id)] = {str(o.id): o.is_correct for o in options}
            else:
                good = next(o for o in options if o.is_correct)
                answers[str(question.id)] = [good.id]
        attempt.finish(answers)
        attempt.refresh_from_db()
        self.assertEqual(attempt.correct_count, 9)

    def test_cleanup_deletes_only_old_unfinished_sets(self):
        self.start(tags=[self.py.id])
        unfinished = self.last_attempt().quiz
        self.start(tags=[self.py.id])
        finished_attempt = self.last_attempt()
        self.finish(finished_attempt, set())
        finished = finished_attempt.quiz
        self.start(tags=[self.py.id])
        recent = self.last_attempt().quiz
        old = timezone.now() - timedelta(days=40)
        Quiz.objects.filter(pk__in=[unfinished.pk, finished.pk]).update(created=old)
        call_command('cleanup_practice_quizzes', verbosity=0)
        self.assertFalse(Quiz.objects.filter(pk=unfinished.pk).exists())
        self.assertTrue(Quiz.objects.filter(pk=finished.pk).exists())
        self.assertTrue(Quiz.objects.filter(pk=recent.pk).exists())
