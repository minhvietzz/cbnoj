from io import StringIO
from unittest import skipUnless

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import CommandError, call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from judge.models import (BankQuestion, BankTag, Course, CourseRole, Profile, Quiz, QuizAttempt, QuizOption,
                          QuizQuestion, QuizTopicStat, Subject)
from judge.utils import practice

quiz_enabled = skipUnless(getattr(settings, 'QUIZ_ENABLED', False), 'the quiz feature is switched off')


def make_profile(name):
    return Profile.objects.create(user=get_user_model().objects.create_user(username=name, password='pw'))


def make_quiz(slug, title, texts, mode='practice', track='', creator=None, kind='single'):
    quiz = Quiz.objects.create(title=title, slug=slug, mode=mode, track=track, creator=creator)
    for number, text in enumerate(texts, 1):
        question = QuizQuestion.objects.create(quiz=quiz, order=number, kind=kind, text=text)
        if kind == 'short':
            question.accepted_answers = 'ok'
            question.save()
        else:
            QuizOption.objects.create(question=question, order=1, text='yes', is_correct=True)
            QuizOption.objects.create(question=question, order=2, text='no', is_correct=False)
    return quiz


class ImportCommandTests(TestCase):
    def setUp(self):
        self.teacher = make_profile('teacher')
        self.home = Subject.objects.get(slug='tin-hoc')
        self.math = Subject.objects.create(name='Toán', slug='toan')
        self.q1 = make_quiz('mang', 'Mạng máy tính', ['one', 'two'], track='ict', creator=self.teacher)
        self.q2 = make_quiz('thuat-toan', 'Thuật toán', ['two', 'three'], creator=self.teacher)   # 'two' repeats
        self.personal = make_quiz('luyen-tap-1', 'Personal', ['secret'], mode='personal')
        make_quiz('ngan', 'Ngắn', ['short one'], kind='short', creator=self.teacher)

    def run_cmd(self, *args):
        out = StringIO()
        call_command('import_quizzes_to_bank', *args, stdout=out)
        return out.getvalue()

    def test_dry_run_writes_nothing(self):
        output = self.run_cmd('--dry-run')
        self.assertEqual(BankQuestion.objects.count(), 0)
        self.assertEqual(BankTag.objects.count(), 0)
        self.assertIn('[dry run]', output)
        self.assertIn('4 would be added', output)

    def test_import(self):
        output = self.run_cmd()
        self.assertIn('4 added, 1 duplicates skipped', output)
        self.assertEqual(BankQuestion.objects.count(), 4)
        self.assertFalse(BankQuestion.objects.filter(text='secret').exists())
        self.assertTrue(all(b.subject_id == self.home.id for b in BankQuestion.objects.all()))
        one = BankQuestion.objects.get(text='one')
        self.assertEqual(sorted(t.name for t in one.tags.all()), ['Mạng máy tính', 'Tin học ứng dụng'])
        self.assertEqual(BankTag.objects.get(name='Tin học ứng dụng').group, 'track')
        self.assertEqual([o['correct'] for o in one.options], [True, False])
        self.assertEqual(BankQuestion.objects.get(text='short one').accepted_list(), ['ok'])
        self.assertEqual(one.creator_id, self.teacher.id)
        # the repeated question carries the tags of both quizzes
        self.assertEqual(sorted(t.name for t in BankQuestion.objects.get(text='two').tags.all()),
                         ['Mạng máy tính', 'Thuật toán', 'Tin học ứng dụng'])
        # quiz questions are left alone unless --link is given
        self.assertFalse(QuizQuestion.objects.filter(bank_question__isnull=False).exists())
        # running again adds nothing
        self.assertIn('0 added', self.run_cmd())
        self.assertEqual(BankQuestion.objects.count(), 4)

    def test_options_quiz_subject_link(self):
        self.run_cmd('--quiz', 'thuat-toan', '--subject', 'toan', '--link')
        self.assertEqual(BankQuestion.objects.count(), 2)
        self.assertTrue(all(b.subject_id == self.math.id for b in BankQuestion.objects.all()))
        self.assertEqual(QuizQuestion.objects.filter(quiz=self.q2, bank_question__isnull=False).count(), 2)
        with self.assertRaises(CommandError):
            self.run_cmd('--quiz', 'luyen-tap-1')
        with self.assertRaises(CommandError):
            self.run_cmd('--subject', 'nope')


@quiz_enabled
class SubjectPracticeTests(TestCase):
    def setUp(self):
        self.client.defaults['HTTP_ACCEPT_LANGUAGE'] = 'en'
        self.alice = make_profile('alice')
        course = Course.objects.create(name='Tin 12', slug='tin-12')
        CourseRole.objects.create(course=course, user=self.alice, role='ST')
        self.home = Subject.objects.get(slug='tin-hoc')
        self.math = Subject.objects.create(name='Toán', slug='toan', order=2)
        self.tag = BankTag.objects.create(name='Chương 1')
        self.items = {}
        for name, subject in (('info-a', self.home), ('info-b', None), ('math-a', self.math), ('math-b', self.math)):
            bank = BankQuestion.objects.create(
                kind='single', text=name, content_hash=name, subject=subject, level=2,
                options=[{'text': 'A', 'correct': True}, {'text': 'B', 'correct': False}])
            bank.tags.add(self.tag)
            self.items[name] = bank

    def texts(self, subject, **kwargs):
        return {q.text for q in practice.pick_questions(self.alice, subject=subject, count=50, **kwargs)}

    def test_subject_filter_treats_blank_as_tin_hoc(self):
        self.assertEqual(self.texts(self.home), {'info-a', 'info-b'})
        self.assertEqual(self.texts(self.math), {'math-a', 'math-b'})
        self.assertEqual(self.texts(None), set(self.items))

    def make_attempt(self, bank_ids, wrong_ids):
        quiz = Quiz.objects.create(title='old', slug='old', mode='practice')
        results = {}
        for number, bank_id in enumerate(bank_ids, 1):
            question = QuizQuestion.objects.create(quiz=quiz, order=number, text='q', bank_question_id=bank_id)
            results[str(question.id)] = bank_id not in wrong_ids
        QuizAttempt.objects.create(quiz=quiz, user=self.alice, seed=1, finished=timezone.now(), results=results,
                                   score=1, max_score=2)

    def test_prefer_wrong_puts_mistakes_first(self):
        banks = [self.items[n].id for n in ('info-a', 'info-b')]
        extra = []
        for number in range(8):
            bank = BankQuestion.objects.create(kind='single', text='more-%d' % number, content_hash='m%d' % number,
                                               subject=self.home, options=[{'text': 'A', 'correct': True}])
            extra.append(bank.id)
        self.make_attempt(banks, wrong_ids={self.items['info-b'].id})
        for _ in range(10):
            picked = practice.pick_questions(self.alice, subject=self.home, count=5, prefer_new=False,
                                             prefer_wrong=True)
            self.assertEqual(len(picked), 5)
            self.assertEqual(picked[0].text, 'info-b')

    def test_weak_topics_and_summary(self):
        other = BankTag.objects.create(name='Chương 2')
        QuizTopicStat.objects.create(user=self.alice, tag=self.tag, answered=10, correct=4)
        QuizTopicStat.objects.create(user=self.alice, tag=other, answered=20, correct=19)
        weak = practice.weak_topics(self.alice)
        self.assertEqual([w['name'] for w in weak], ['Chương 1', 'Chương 2'])
        self.assertEqual(weak[0]['pct'], 40)
        self.assertEqual(weak[0]['n'], 10)
        self.assertEqual(practice.summary(self.alice)['answered'], 0)
        self.make_attempt([self.items['info-a'].id], wrong_ids=set())
        self.assertEqual(practice.summary(self.alice)['streak'], 1)

    def test_page_and_post(self):
        QuizTopicStat.objects.create(user=self.alice, tag=self.tag, answered=10, correct=4)
        self.client.login(username='alice', password='pw')
        page = self.client.get(reverse('practice'))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'Your weak topics')
        self.assertContains(page, '40% correct')
        self.assertContains(page, 'name="subject"')
        resp = self.client.post(reverse('practice'), {'subject': self.math.id, 'count': 5, 'level': 0, 'kinds': ''})
        self.assertEqual(resp.status_code, 302)
        quiz = Quiz.objects.get(mode='personal')
        self.assertEqual({q.text for q in quiz.questions.all()}, {'math-a', 'math-b'})
        resp = self.client.post(reverse('practice'), {'subject': self.home.id, 'count': 5, 'level': 3})
        self.assertEqual(resp.status_code, 302)    # nothing at level 3: back to the form with a warning
        self.assertEqual(Quiz.objects.filter(mode='personal').count(), 1)

    def test_mistakes_page(self):
        self.client.login(username='alice', password='pw')
        self.assertContains(self.client.get(reverse('practice_mistakes')), 'mistake notebook is empty')
        self.make_attempt([self.items['info-a'].id], wrong_ids={self.items['info-a'].id})
        page = self.client.get(reverse('practice_mistakes'))
        self.assertContains(page, 'info-a')
        self.assertContains(page, 'today')
        self.assertContains(self.client.get(reverse('practice')), 'info-a')
