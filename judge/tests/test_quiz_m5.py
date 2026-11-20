import io
import zipfile
from datetime import timedelta
from xml.etree import ElementTree

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from judge.models import (BankQuestion, BankTag, Course, CourseRole, Profile, Quiz, QuizAttempt, QuizOption,
                          QuizProfileStat, QuizQuestion, QuizTopicStat)
from judge.utils import quiz_stats, seb, xlsx


from unittest import skipUnless

from django.conf import settings

# The pages only exist while local_settings.py has QUIZ_ENABLED = True (see dmoj/urls.py).
quiz_enabled = skipUnless(getattr(settings, 'QUIZ_ENABLED', False), 'the quiz feature is switched off')


@quiz_enabled
class ExamFixture(TestCase):
    def make_user(self, name, **extra):
        user = get_user_model().objects.create_user(username=name, password='pw', **extra)
        return Profile.objects.create(user=user)

    def setUp(self):
        self.client.defaults['HTTP_ACCEPT_LANGUAGE'] = 'en'   # assertions below read the English text
        cache.clear()
        self.teacher = self.make_user('teacher')
        self.alice = self.make_user('alice')
        self.bob = self.make_user('bob')
        self.course = Course.objects.create(name='Tin 12', slug='tin-12')
        CourseRole.objects.create(course=self.course, user=self.teacher, role='TE')
        for student in (self.alice, self.bob):
            CourseRole.objects.create(course=self.course, user=student, role='ST')
        now = timezone.now()
        self.quiz = Quiz.objects.create(
            title='Thi thu', slug='thi-thu', mode='exam', course=self.course, proctoring='strict', time_limit=50,
            start_time=now - timedelta(minutes=10), end_time=now + timedelta(minutes=50), creator=self.teacher)
        self.tag = BankTag.objects.create(name='Mạng')
        self.questions = []
        for number in range(1, 4):
            bank = BankQuestion.objects.create(kind='single', text='q%d' % number, level=2, content_hash='h%d' % number,
                                               options=[{'text': 'A', 'correct': True}, {'text': 'B', 'correct': False}])
            bank.tags.add(self.tag)
            question = QuizQuestion.objects.create(quiz=self.quiz, order=number, kind='single', text='q%d' % number,
                                                   bank_question=bank, explanation='why %d' % number)
            QuizOption.objects.create(question=question, order=1, text='A', is_correct=True)
            QuizOption.objects.create(question=question, order=2, text='B', is_correct=False)
            self.questions.append(question)

    def login(self, name):
        self.client.logout()
        self.assertTrue(self.client.login(username=name, password='pw'))

    def attempt(self, profile, right=3, finish=True, **extra):
        attempt = QuizAttempt.objects.create(quiz=self.quiz, user=profile, seed=1, **extra)
        if finish:
            answers = {}
            for index, question in enumerate(self.questions):
                options = list(question.options.all())
                chosen = next(o for o in options if o.is_correct == (index < right))
                answers[str(question.id)] = [chosen.id]
            attempt.finish(answers)
        return attempt

    def result_url(self, attempt):
        return reverse('quiz_result', args=[self.quiz.slug, attempt.id])

    def act(self, action, ids=(), **data):
        return self.client.post(reverse('quiz_results_action', args=[self.quiz.slug]),
                                dict(data, action=action, ids=list(ids)))


class AnswerLeakTest(ExamFixture):
    def test_answers_stay_hidden_until_the_exam_closed_for_everyone(self):
        mine = self.attempt(self.alice)
        self.login('alice')
        resp = self.client.get(self.result_url(mine))
        self.assertContains(resp, 'will be shown once the exam has closed')
        self.assertNotContains(resp, 'why 1')
        self.assertNotContains(resp, 'is-correct')

        Quiz.objects.filter(pk=self.quiz.pk).update(end_time=timezone.now() - timedelta(minutes=1))
        resp = self.client.get(self.result_url(mine))
        self.assertContains(resp, 'why 1')   # closed and nobody is still writing

    def test_a_late_candidate_keeps_the_answers_hidden(self):
        mine = self.attempt(self.alice)
        self.attempt(self.bob, finish=False, extra_minutes=30)   # bob was granted 30 more minutes
        Quiz.objects.filter(pk=self.quiz.pk).update(end_time=timezone.now() - timedelta(minutes=1))
        QuizAttempt.objects.filter(user=self.bob).update(started=timezone.now() - timedelta(minutes=5))
        self.login('alice')
        self.assertContains(self.client.get(self.result_url(mine)), 'will be shown once the exam has closed')

    def test_teachers_and_practice_quizzes_are_not_held_back(self):
        mine = self.attempt(self.alice)
        self.login('teacher')
        self.assertContains(self.client.get(self.result_url(mine)), 'why 1')
        practice = Quiz.objects.create(title='P', slug='p', mode='practice', is_public=True)
        self.assertTrue(practice.answers_released())


class ExtraTimeTest(ExamFixture):
    def test_deadline_and_phase_include_extra_minutes(self):
        attempt = self.attempt(self.alice, finish=False)
        base = attempt.deadline
        Quiz.objects.filter(pk=self.quiz.pk).update(extra_minutes=15)
        QuizAttempt.objects.filter(pk=attempt.pk).update(extra_minutes=5)
        attempt = QuizAttempt.objects.get(pk=attempt.pk)
        self.assertEqual(attempt.deadline - base, timedelta(minutes=20))
        quiz = Quiz.objects.get(pk=self.quiz.pk)
        self.assertEqual(quiz.effective_end - quiz.end_time, timedelta(minutes=15))
        Quiz.objects.filter(pk=quiz.pk).update(end_time=timezone.now() - timedelta(minutes=10))
        self.assertEqual(Quiz.objects.get(pk=quiz.pk).phase(), 'running')   # still open thanks to the 15 minutes
        Quiz.objects.filter(pk=quiz.pk).update(end_time=timezone.now() - timedelta(minutes=20))
        self.assertEqual(Quiz.objects.get(pk=quiz.pk).phase(), 'ended')


class TeacherActionsTest(ExamFixture):
    def test_only_managers_can_act(self):
        self.login('alice')
        self.assertEqual(self.act('publish').status_code, 403)
        self.assertEqual(self.client.get(reverse('quiz_live', args=[self.quiz.slug])).status_code, 403)

    def test_extend_selected_adds_time_and_reopens_automatic_submission(self):
        attempt = self.attempt(self.alice, finish=False)
        QuizAttempt.objects.filter(pk=attempt.pk).update(started=timezone.now() - timedelta(minutes=52))
        attempt.refresh_from_db()
        self.assertTrue(attempt.finish_if_expired())            # the outage: closed automatically
        self.assertTrue(attempt.auto_submitted)
        self.assertEqual(QuizProfileStat.objects.get(user=self.alice).exams_taken, 1)

        self.login('teacher')
        resp = self.act('extend', [attempt.id], minutes=10)
        self.assertRedirects(resp, reverse('quiz_results', args=[self.quiz.slug]) + '?fresh=1',
                             fetch_redirect_response=False)
        attempt.refresh_from_db()
        self.assertEqual(attempt.extra_minutes, 10)
        self.assertFalse(attempt.is_finished)                     # reopened
        self.assertEqual(QuizProfileStat.objects.get(user=self.alice).exams_taken, 0)
        self.assertEqual(QuizTopicStat.objects.get(user=self.alice).answered, 0)

    def test_extend_does_not_reopen_what_the_student_submitted_himself(self):
        attempt = self.attempt(self.alice)
        self.login('teacher')
        self.act('extend', [attempt.id], minutes=10)
        attempt.refresh_from_db()
        self.assertTrue(attempt.is_finished)

    def test_extend_for_everyone_and_reopen(self):
        late = self.attempt(self.alice, finish=False)
        QuizAttempt.objects.filter(pk=late.pk).update(started=timezone.now() - timedelta(minutes=51))
        late.refresh_from_db()
        late.finish_if_expired()
        self.login('teacher')
        self.act('extend_all', minutes=20, reopen='1')
        self.quiz.refresh_from_db()
        late.refresh_from_db()
        self.assertEqual(self.quiz.extra_minutes, 20)
        self.assertFalse(late.is_finished)

    def test_extra_time_is_capped(self):
        self.login('teacher')
        for _ in range(5):
            self.act('extend_all', minutes=240)
        self.quiz.refresh_from_db()
        self.assertEqual(self.quiz.extra_minutes, 600)

    def test_force_submit_cancel_and_restore(self):
        running = self.attempt(self.alice, finish=False)
        done = self.attempt(self.bob)
        self.login('teacher')
        self.act('submit', [running.id])
        running.refresh_from_db()
        self.assertTrue(running.is_finished and running.auto_submitted)

        self.act('invalidate', [done.id])
        done.refresh_from_db()
        self.assertTrue(done.invalidated)
        self.assertEqual(QuizProfileStat.objects.get(user=self.bob).exams_taken, 0)
        self.act('restore', [done.id])
        done.refresh_from_db()
        self.assertFalse(done.invalidated)
        self.assertEqual(QuizProfileStat.objects.get(user=self.bob).exams_taken, 1)

    def test_actions_ignore_attempts_of_other_quizzes(self):
        other = Quiz.objects.create(title='Other', slug='other', mode='exam', course=self.course,
                                    start_time=timezone.now(), end_time=timezone.now() + timedelta(hours=1))
        foreign = QuizAttempt.objects.create(quiz=other, user=self.alice, seed=1)
        self.login('teacher')
        self.act('submit', [foreign.id])
        foreign.refresh_from_db()
        self.assertFalse(foreign.is_finished)

    def test_publish_results_for_manual_release(self):
        Quiz.objects.filter(pk=self.quiz.pk).update(results_release='manual')
        mine = self.attempt(self.alice)
        self.login('alice')
        self.assertContains(self.client.get(self.result_url(mine)), 'has been submitted')
        self.login('teacher')
        self.act('publish')
        self.login('alice')
        self.assertNotContains(self.client.get(self.result_url(mine)), 'has been submitted')

    def test_live_feed(self):
        running = self.attempt(self.alice, finish=False)
        QuizAttempt.objects.filter(pk=running.pk).update(last_heartbeat=timezone.now(), violation_count=2)
        expired = self.attempt(self.bob, finish=False)
        QuizAttempt.objects.filter(pk=expired.pk).update(started=timezone.now() - timedelta(hours=2))
        self.login('teacher')
        data = self.client.get(reverse('quiz_live', args=[self.quiz.slug])).json()
        self.assertEqual([r['user'] for r in data['in_progress']], ['alice'])
        row = data['in_progress'][0]
        self.assertTrue(row['online'])
        self.assertEqual(row['violations'], 2)
        self.assertEqual(data['finished'], 1)        # bob was closed on the spot
        self.assertEqual(data['phase'], 'running')

    def test_results_page_shows_the_action_panel(self):
        self.attempt(self.alice)
        self.login('teacher')
        resp = self.client.get(reverse('quiz_results', args=[self.quiz.slug]))
        self.assertContains(resp, 'Add time for everyone')
        self.assertContains(resp, 'id="live-box"')


class HeartbeatLimitTest(ExamFixture):
    def test_beats_closer_than_three_seconds_are_refused(self):
        attempt = self.attempt(self.alice, finish=False)
        self.login('alice')
        self.client.get(reverse('quiz_attempt', args=[self.quiz.slug, attempt.id]))
        attempt.refresh_from_db()
        beat = reverse('quiz_attempt_heartbeat', args=[self.quiz.slug, attempt.id])
        self.assertEqual(self.client.post(beat, {'attempt_token': attempt.session_key}).status_code, 429)
        QuizAttempt.objects.filter(pk=attempt.pk).update(last_heartbeat=timezone.now() - timedelta(seconds=20))
        self.assertEqual(self.client.post(beat, {'attempt_token': attempt.session_key}).status_code, 200)
        self.assertEqual(self.client.post(beat, {'attempt_token': attempt.session_key}).status_code, 429)


class SebTest(ExamFixture):
    KEY = 'secret-exam-key'

    def signed(self, url):
        return {'HTTP_X_SAFEEXAMBROWSER_REQUESTHASH': seb.expected_hash('http://testserver' + url, self.KEY)}

    def test_hash_formula(self):
        import hashlib
        self.assertEqual(seb.expected_hash('http://x/y', 'k'), hashlib.sha256(b'http://x/yk').hexdigest())

    def test_exam_refuses_other_browsers_but_not_teachers(self):
        Quiz.objects.filter(pk=self.quiz.pk).update(seb_browser_key=self.KEY)
        start = reverse('quiz_start', args=[self.quiz.slug])
        self.login('alice')
        self.assertEqual(self.client.post(start, {'agree': '1'}).status_code, 403)
        self.assertEqual(self.client.post(start, {'agree': '1'}, **self.signed(start)).status_code, 302)
        attempt = QuizAttempt.objects.get(user=self.alice)
        page = reverse('quiz_attempt', args=[self.quiz.slug, attempt.id])
        self.assertEqual(self.client.get(page).status_code, 403)
        self.assertEqual(self.client.get(page, **self.signed(page)).status_code, 200)
        bad = {'HTTP_X_SAFEEXAMBROWSER_REQUESTHASH': 'f' * 64}
        self.assertEqual(self.client.get(page, **bad).status_code, 403)
        self.login('teacher')
        self.assertEqual(self.client.get(self.quiz.get_absolute_url()).status_code, 200)

    def test_detail_page_is_readable_and_mentions_seb(self):
        Quiz.objects.filter(pk=self.quiz.pk).update(seb_browser_key=self.KEY)
        self.login('alice')
        self.assertContains(self.client.get(self.quiz.get_absolute_url()), 'Safe Exam Browser')


class XlsxTest(SimpleTestCase):
    def test_column_names(self):
        self.assertEqual([xlsx.column_name(i) for i in (0, 25, 26, 27, 701, 702)], ['A', 'Z', 'AA', 'AB', 'ZZ', 'AAA'])

    def test_workbook_is_well_formed(self):
        data = xlsx.build_xlsx(['Name', 'Score'], [['Nguyễn <A> & "B"', 9.5], ['bad\x00char', 7], [None, True]],
                               'Sheet: *1/')
        archive = zipfile.ZipFile(io.BytesIO(data))
        self.assertEqual(sorted(archive.namelist()), ['[Content_Types].xml', '_rels/.rels', 'xl/_rels/workbook.xml.rels',
                                                      'xl/styles.xml', 'xl/workbook.xml', 'xl/worksheets/sheet1.xml'])
        for name in archive.namelist():
            ElementTree.fromstring(archive.read(name))        # every part parses as XML
        ns = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
        sheet = ElementTree.fromstring(archive.read('xl/worksheets/sheet1.xml'))
        texts = [t.text for t in sheet.iterfind('.//m:t', ns)]
        self.assertIn('Nguyễn <A> & "B"', texts)
        self.assertIn('badchar', texts)
        self.assertEqual(len(list(sheet.iterfind('.//m:row', ns))), 4)
        self.assertEqual(sheet.find('.//m:row/m:c[@r="B2"]/m:v', ns).text, '9.5')
        workbook = ElementTree.fromstring(archive.read('xl/workbook.xml'))
        self.assertEqual(workbook.find('.//m:sheet', ns).get('name'), 'Sheet   1 ')


class ExportTest(ExamFixture):
    def test_results_export_as_xlsx(self):
        self.attempt(self.alice)
        self.login('teacher')
        resp = self.client.get(reverse('quiz_results', args=[self.quiz.slug]) + '?export=xlsx')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('spreadsheetml', resp['Content-Type'])
        archive = zipfile.ZipFile(io.BytesIO(resp.content))
        sheet = archive.read('xl/worksheets/sheet1.xml').decode()
        self.assertIn('alice', sheet)


class RankingCacheTest(ExamFixture):
    def test_cached_ranking_follows_new_attempts_and_cancellations(self):
        first = self.attempt(self.alice, right=2)
        rows = quiz_stats.cached_exam_ranking(self.quiz)
        self.assertEqual([r['user'].user.username for r in rows], ['alice'])
        self.attempt(self.bob, right=3)                     # finishing clears the cache
        rows = quiz_stats.cached_exam_ranking(self.quiz)
        self.assertEqual([r['user'].user.username for r in rows], ['bob', 'alice'])

        quiz_stats.cached_exam_ranking(self.quiz)           # warm again
        quiz_stats.set_invalidated(first, True)
        self.assertEqual([r['user'].user.username for r in quiz_stats.cached_exam_ranking(self.quiz)], ['bob'])

    def test_cache_never_serves_a_cancelled_attempt_even_without_invalidation(self):
        first = self.attempt(self.alice)
        quiz_stats.cached_exam_ranking(self.quiz)
        QuizAttempt.objects.filter(pk=first.pk).update(invalidated=True)    # changed behind the cache's back
        self.assertEqual(quiz_stats.cached_exam_ranking(self.quiz), [])

    def test_fresh_bypasses_the_cache(self):
        self.attempt(self.alice)
        quiz_stats.cached_exam_ranking(self.quiz)
        cache.set('quiz-ranking-%d' % self.quiz.id, [])
        self.assertEqual(quiz_stats.cached_exam_ranking(self.quiz), [])
        self.assertEqual(len(quiz_stats.cached_exam_ranking(self.quiz, fresh=True)), 1)


class TopicMatrixTest(ExamFixture):
    def test_matrix_and_trend(self):
        self.attempt(self.alice, right=3)
        self.attempt(self.bob, right=1)
        matrix = quiz_stats.course_topic_matrix(self.course)
        self.assertEqual([name for name, _avg in matrix['tags']], ['Mạng'])
        self.assertEqual(matrix['tags'][0][1], 67)          # 4 of 6 weighted answers right
        cells = {s.user.username: row[0] for s, row in matrix['rows']}
        self.assertEqual(cells['alice'], (100, 3))
        self.assertEqual(cells['bob'], (33, 3))
        trend = quiz_stats.course_exam_trend(self.course)
        self.assertEqual([(q.slug, n, avg) for q, n, avg in trend], [('thi-thu', 2, 6.67)])

    def test_course_page_shows_heatmap_to_teachers_only(self):
        self.attempt(self.alice)
        url = reverse('course_quizzes', args=[self.course.slug])
        self.login('teacher')
        self.assertContains(self.client.get(url), 'Strengths and weaknesses by topic')
        self.login('alice')
        self.assertNotContains(self.client.get(url), 'Strengths and weaknesses by topic')
