from datetime import timedelta
from types import SimpleNamespace
from unittest import skipUnless

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from judge.models import (BankQuestion, BankTag, Course, CourseRole, Profile, Quiz, QuizAttempt, QuizOption,
                          QuizProfileStat, QuizQuestion, QuizTopicStat)
from judge.utils import quiz_stats


# The pages only exist while local_settings.py has QUIZ_ENABLED = True (see dmoj/urls.py).
quiz_enabled = skipUnless(getattr(settings, 'QUIZ_ENABLED', False), 'the quiz feature is switched off')


@quiz_enabled
class StatsTestCase(TestCase):
    def make_user(self, name, superuser=False):
        user = get_user_model().objects.create_user(username=name, password='pw', is_superuser=superuser,
                                                    is_staff=superuser)
        return Profile.objects.create(user=user)

    def setUp(self):
        self.client.defaults['HTTP_ACCEPT_LANGUAGE'] = 'en'   # assertions below read the English text
        self.teacher = self.make_user('teacher')
        self.admin = self.make_user('admin', superuser=True)
        self.alice = self.make_user('alice')
        self.bob = self.make_user('bob')
        self.carol = self.make_user('carol')
        self.dave = self.make_user('dave')
        self.course = Course.objects.create(name='Tin 12', slug='tin-12')
        CourseRole.objects.create(course=self.course, user=self.teacher, role='TE')
        for student in (self.alice, self.bob, self.carol):
            CourseRole.objects.create(course=self.course, user=student, role='ST')
        self.tag = BankTag.objects.create(name='Mạng máy tính')
        self.hard_tag = BankTag.objects.create(name='Python')

    def make_quiz(self, slug, count=4, mode='exam', level=2, tag=None, **extra):
        defaults = {}
        if mode == 'exam':
            now = timezone.now()
            defaults = dict(course=self.course, start_time=now - timedelta(hours=2),
                            end_time=now + timedelta(hours=2))
        quiz = Quiz.objects.create(title=slug, slug=slug, mode=mode, creator=self.teacher, **dict(defaults, **extra))
        tag = tag or self.tag
        for number in range(1, count + 1):
            bank = BankQuestion.objects.create(
                kind='single', text='%s-%d' % (slug, number), level=level, content_hash='%s-%d' % (slug, number),
                options=[{'text': 'A', 'correct': True}, {'text': 'B', 'correct': False}])
            bank.tags.add(tag)
            question = QuizQuestion.objects.create(quiz=quiz, order=number, kind='single', text=bank.text,
                                                   bank_question=bank)
            QuizOption.objects.create(question=question, order=1, text='A', is_correct=True)
            QuizOption.objects.create(question=question, order=2, text='B', is_correct=False)
        return quiz

    def take(self, quiz, profile, right, seconds=600):
        """Finish an attempt answering the first `right` questions correctly, `seconds` after it started."""
        attempt = QuizAttempt.objects.create(quiz=quiz, user=profile, seed=1)
        answers = {}
        for index, question in enumerate(quiz.questions.all()):
            options = list(question.options.all())
            good = next(o for o in options if o.is_correct)
            bad = next(o for o in options if not o.is_correct)
            answers[str(question.id)] = [good.id if index < right else bad.id]
        started = timezone.now() - timedelta(seconds=seconds)
        QuizAttempt.objects.filter(pk=attempt.pk).update(started=started)
        attempt.refresh_from_db()
        attempt.finish(answers)
        return attempt


class StatsTest(StatsTestCase):
    def test_level_needs_enough_questions(self):
        quiz = self.make_quiz('few', count=4, mode='practice')
        self.take(quiz, self.alice, right=4)
        stat = QuizProfileStat.objects.get(user=self.alice)
        self.assertEqual(stat.level, '')
        self.assertEqual(stat.practice_sessions, 1)
        self.assertEqual(stat.exams_taken, 0)

    def test_level_from_topic_accuracy_and_exams(self):
        practice = self.make_quiz('practice', count=20, mode='practice', level=3, tag=self.hard_tag)
        self.take(practice, self.alice, right=20)
        stat = QuizProfileStat.objects.get(user=self.alice)
        self.assertEqual((stat.level, stat.level_score), ('excellent', 10.0))

        exam = self.make_quiz('exam', count=4)
        self.take(exam, self.alice, right=2)  # 5/10 on the exam drags the level down
        stat = QuizProfileStat.objects.get(user=self.alice)
        self.assertEqual(stat.exams_taken, 1)
        self.assertEqual(stat.avg_exam_score, 5.0)
        self.assertEqual(stat.questions_answered, 24)
        self.assertLess(stat.level_score, 10)
        self.assertEqual(stat.level, quiz_stats.level_for(stat.level_score))

    def test_topic_stats_weight_difficulty(self):
        quiz = self.make_quiz('topics', count=2, mode='practice', level=3)  # hard -> weight 2
        self.take(quiz, self.alice, right=1)
        topic = QuizTopicStat.objects.get(user=self.alice, tag=self.tag)
        self.assertEqual((topic.answered, topic.correct), (2, 1))
        self.assertEqual((topic.weighted_answered, topic.weighted_correct), (4.0, 2.0))
        self.assertAlmostEqual(topic.accuracy, 0.5)
        self.assertEqual(quiz_stats.topic_breakdown(self.alice), [('Mạng máy tính', 0.5, 2)])

    def test_level_bands(self):
        self.assertEqual([quiz_stats.level_for(v) for v in (0, 4.99, 5, 6.49, 6.5, 7.99, 8, 10)],
                         ['weak', 'weak', 'average', 'average', 'good', 'good', 'excellent', 'excellent'])

    def test_invalidating_reverts_statistics_and_restoring_reapplies_them(self):
        quiz = self.make_quiz('revert', count=4)
        attempt = self.take(quiz, self.alice, right=4)
        self.assertEqual(QuizTopicStat.objects.get(user=self.alice).answered, 4)
        quiz_stats.set_invalidated(attempt, True)
        self.assertEqual(QuizTopicStat.objects.get(user=self.alice).answered, 0)
        stat = QuizProfileStat.objects.get(user=self.alice)
        self.assertEqual((stat.exams_taken, stat.questions_answered), (0, 0))
        quiz_stats.set_invalidated(attempt, False)
        self.assertEqual(QuizTopicStat.objects.get(user=self.alice).answered, 4)
        self.assertEqual(QuizProfileStat.objects.get(user=self.alice).exams_taken, 1)

    def test_invalidated_attempt_frees_the_retake(self):
        quiz = self.make_quiz('retake', count=2)
        attempt = self.take(quiz, self.alice, right=2)
        self.client.login(username='alice', password='pw')
        start = reverse('quiz_start', args=[quiz.slug])
        self.client.post(start)
        self.assertEqual(QuizAttempt.objects.filter(user=self.alice).count(), 1)
        quiz_stats.set_invalidated(attempt, True)
        self.client.post(start)
        self.assertEqual(QuizAttempt.objects.filter(user=self.alice).count(), 2)

    def test_rebuild_matches_incremental_updates(self):
        quiz = self.make_quiz('rebuild', count=5)
        self.take(quiz, self.alice, right=3)
        self.take(self.make_quiz('rebuild2', count=3, mode='practice'), self.alice, right=3)
        before = list(QuizTopicStat.objects.filter(user=self.alice).values('answered', 'correct',
                                                                           'weighted_answered', 'weighted_correct'))
        profile_before = QuizProfileStat.objects.filter(user=self.alice).values().get()
        QuizTopicStat.objects.all().delete()
        QuizProfileStat.objects.all().delete()
        self.assertEqual(quiz_stats.rebuild_all(), 1)
        after = list(QuizTopicStat.objects.filter(user=self.alice).values('answered', 'correct',
                                                                          'weighted_answered', 'weighted_correct'))
        self.assertEqual(before, after)
        profile_after = QuizProfileStat.objects.filter(user=self.alice).values().get()
        for key in ('exams_taken', 'practice_sessions', 'questions_answered', 'avg_exam_score', 'level_score'):
            self.assertEqual(profile_before[key], profile_after[key], key)


class RankingTest(StatsTestCase):
    def test_ranking_orders_by_score_then_time_and_shares_ties(self):
        quiz = self.make_quiz('rank', count=4)
        self.take(quiz, self.alice, right=3, seconds=900)
        self.take(quiz, self.bob, right=4, seconds=1200)
        self.take(quiz, self.carol, right=3, seconds=900)
        self.take(quiz, self.teacher, right=4, seconds=60)  # previewing the paper: never ranked
        rows = quiz_stats.exam_ranking(quiz)
        self.assertEqual([(r['user'].user.username, r['rank']) for r in rows],
                         [('bob', 1), ('alice', 2), ('carol', 2)])
        self.assertEqual(rows[0]['score10'], 10.0)

    def test_invalidated_attempts_are_not_ranked(self):
        quiz = self.make_quiz('rank2', count=2)
        attempt = self.take(quiz, self.alice, right=2)
        self.take(quiz, self.bob, right=1)
        quiz_stats.set_invalidated(attempt, True)
        self.assertEqual([r['user'].user.username for r in quiz_stats.exam_ranking(quiz)], ['bob'])

    def test_distribution_and_question_accuracy(self):
        quiz = self.make_quiz('dist', count=2)
        self.take(quiz, self.alice, right=2)
        self.take(quiz, self.bob, right=1)
        rows = quiz_stats.exam_ranking(quiz)
        bins = quiz_stats.score_distribution(rows)
        self.assertEqual(sum(c for _lo, _hi, c in bins), 2)
        self.assertEqual(bins[-1][2], 1)   # 10/10
        self.assertEqual(bins[5][2], 1)    # 5/10
        accuracy = quiz_stats.question_accuracy(quiz, rows)
        self.assertEqual([percent for _q, percent, _n in accuracy], [100, 50])

    @staticmethod
    def fake_rows(question_ids, count, answer):
        """count fake candidates, best first; answer(rank, position) says whether they got that question right."""
        return [{'score': count - rank, 'attempt': SimpleNamespace(
            results={str(q): answer(rank, i) for i, q in enumerate(question_ids)})} for rank in range(count)]

    def test_question_review_flags_inverse_and_hard_questions(self):
        quiz = self.make_quiz('review', count=3)
        ids = [q.id for q in quiz.questions.all()]
        rows = self.fake_rows(ids, 12, lambda rank, i: [rank < 6, rank >= 6, False][i])
        review = quiz_stats.question_review(quiz, rows)
        good, inverse, hard = (review[q] for q in ids)
        self.assertGreater(good['discrimination'], 0)
        self.assertIsNone(good['flag'])
        self.assertLess(inverse['discrimination'], 0)
        self.assertEqual(inverse['flag'], 'inverse')
        self.assertEqual(hard['flag'], 'hard')

    def test_question_review_needs_enough_candidates(self):
        quiz = self.make_quiz('review-small', count=1)
        ids = [q.id for q in quiz.questions.all()]
        review = quiz_stats.question_review(quiz, self.fake_rows(ids, 6, lambda rank, i: rank >= 3))
        self.assertIsNone(review[ids[0]]['discrimination'])
        self.assertIsNone(review[ids[0]]['flag'])


class ReportViewsTest(StatsTestCase):
    def setUp(self):
        super().setUp()
        self.quiz = self.make_quiz('report', count=4)
        self.take(self.quiz, self.alice, right=4)
        self.take(self.quiz, self.bob, right=2)

    def get(self, name, url):
        self.client.logout()
        if name:
            self.assertTrue(self.client.login(username=name, password='pw'))
        return self.client.get(url)

    def test_results_only_for_managers(self):
        url = reverse('quiz_results', args=[self.quiz.slug])
        self.assertEqual(self.get('alice', url).status_code, 403)
        self.assertEqual(self.get('dave', url).status_code, 403)
        self.assertEqual(self.get(None, url).status_code, 302)
        resp = self.get('teacher', url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'alice')
        self.assertContains(resp, 'bob')

    def test_results_csv_export(self):
        resp = self.get('teacher', reverse('quiz_results', args=[self.quiz.slug]) + '?export=csv')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('text/csv', resp['Content-Type'])
        lines = resp.content.decode('utf-8-sig').strip().splitlines()
        self.assertEqual(len(lines), 3)
        self.assertTrue(lines[1].startswith('1,alice,4.0'))

    def test_my_progress_page(self):
        resp = self.get('alice', reverse('quiz_me'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Mạng máy tính')
        self.assertEqual(self.get(None, reverse('quiz_me')).status_code, 302)
        self.assertContains(self.get('dave', reverse('quiz_me')), 'not finished any quiz')

    def test_course_report_teacher_sees_everyone_student_only_self(self):
        url = reverse('course_quizzes', args=[self.course.slug])
        resp = self.get('teacher', url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'alice')
        self.assertContains(resp, 'bob')
        resp = self.get('bob', url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'bob')
        self.assertNotContains(resp, '>alice<')
        self.assertEqual(self.get('dave', url).status_code, 404)

    def test_course_report_numbers(self):
        rows = {r['user'].user.username: r for r in quiz_stats.course_report(self.course)}
        self.assertEqual(rows['alice']['avg'], 10.0)
        self.assertEqual(rows['bob']['avg'], 5.0)
        self.assertEqual(rows['carol']['exams'], 0)
        self.assertIsNone(rows['carol']['avg'])


class AdminTest(StatsTestCase):
    def setUp(self):
        super().setUp()
        self.quiz = self.make_quiz('adm', count=2)
        self.attempt = self.take(self.quiz, self.alice, right=2)
        self.client.login(username='admin', password='pw')

    def test_changelists_render(self):
        for name in ('quiz', 'quizattempt', 'quizprofilestat', 'banktag', 'bankquestion', 'quizquestion'):
            resp = self.client.get(reverse('admin:judge_%s_changelist' % name))
            self.assertEqual(resp.status_code, 200, name)

    def test_attempt_page_and_quiz_filter_render(self):
        resp = self.client.get(reverse('admin:judge_quizattempt_change', args=[self.attempt.id]))
        self.assertEqual(resp.status_code, 200)
        resp = self.client.get(reverse('admin:judge_quizattempt_changelist') + '?quiz__id__exact=%d' % self.quiz.id)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'alice')
        self.assertEqual(self.client.get(reverse('admin:judge_quiz_change', args=[self.quiz.id])).status_code, 200)

    def test_invalidate_action(self):
        resp = self.client.post(reverse('admin:judge_quizattempt_changelist'), {
            'action': 'invalidate_attempts', '_selected_action': [self.attempt.id]})
        self.assertEqual(resp.status_code, 302)
        self.attempt.refresh_from_db()
        self.assertTrue(self.attempt.invalidated)
        self.assertEqual(QuizProfileStat.objects.get(user=self.alice).exams_taken, 0)

    def test_publish_results_action(self):
        self.client.post(reverse('admin:judge_quiz_changelist'), {
            'action': 'publish_results', '_selected_action': [self.quiz.id]})
        self.quiz.refresh_from_db()
        self.assertTrue(self.quiz.results_published)

    def test_attempts_cannot_be_added_by_hand(self):
        self.assertEqual(self.client.get(reverse('admin:judge_quizattempt_add')).status_code, 403)
