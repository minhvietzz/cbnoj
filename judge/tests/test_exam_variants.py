import re
from collections import Counter
from unittest import skipUnless

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from judge.models import ExamVariant, Profile, Quiz, QuizAttempt, QuizOption, QuizQuestion
from judge.utils import exam_variants as ev, quiz_stats

quiz_enabled = skipUnless(getattr(settings, 'QUIZ_ENABLED', False), 'the quiz feature is switched off')


class PinnedOptionTest(SimpleTestCase):
    def test_pinned_texts(self):
        for text in ('Cả A và B', 'cả A, B đều đúng', 'Tất cả các đáp án trên', 'Không có đáp án nào đúng',
                     'All of the above', 'None of the above', 'Both A and B', 'Cả hai ý trên'):
            self.assertTrue(ev.is_pinned_option(text), text)
        for text in ('Hà Nội', 'Tất cả học sinh lớp 10 đều đi học đầy đủ trong tuần vừa rồi của năm học này mà',
                     'x = 5'):
            self.assertFalse(ev.is_pinned_option(text), text)

    def test_codes(self):
        self.assertEqual(ev.next_codes('0101', 3), ['0101', '0102', '0103'])
        self.assertEqual(ev.next_codes('0109', 2), ['0109', '0110'])
        self.assertEqual(ev.next_codes('DE7', 2), ['DE7', 'DE8'])
        self.assertEqual(ev.next_codes('DE', 2), ['DE1', 'DE2'])
        with self.assertRaises(ev.VariantError):
            ev.next_codes('bad code', 2)


@quiz_enabled
class VariantTestCase(TestCase):
    def make_user(self, name, superuser=False):
        user = get_user_model().objects.create_user(username=name, password='pw', is_superuser=superuser)
        return Profile.objects.create(user=user)

    def add(self, order, kind, section, text, options, passage='', accepted=''):
        question = QuizQuestion.objects.create(quiz=self.quiz, kind=kind, order=order, section=section, text=text,
                                               passage=passage, accepted_answers=accepted)
        for index, (label, correct) in enumerate(options, 1):
            QuizOption.objects.create(question=question, order=index, text=label, is_correct=correct)
        return question

    def setUp(self):
        self.client.defaults['HTTP_ACCEPT_LANGUAGE'] = 'en'
        self.teacher = self.make_user('teacher', superuser=True)
        self.quiz = Quiz.objects.create(title='De thi thu', slug='de-thi-thu', mode='practice', is_public=True,
                                        creator=self.teacher)
        order, self.singles = 0, []
        # Part I: 12 single choice questions; #4-#6 share a passage; #7 ends with "both A and B".
        for n in range(1, 13):
            order += 1
            correct = (n - 1) % 4
            options = [('q%d-%s' % (n, 'ok' if i == correct else 'no%d' % i), i == correct) for i in range(4)]
            passage = 'Doan van chung' if n in (4, 5, 6) else ''
            if n == 7:
                options = [('q7-A1', True), ('q7-B1', False), ('q7-C1', False), ('Cả A và C', False)]
            self.singles.append(self.add(order, 'single', 'Phần I', 'Question %d' % n, options, passage))
        # Part II: tf4, Part III: short.
        self.tfs = []
        for n in (1, 2):
            order += 1
            self.tfs.append(self.add(order, 'tf4', 'Phần II', 'TF %d' % n,
                                     [('a%d' % n, True), ('b%d' % n, False), ('c%d' % n, True), ('d%d' % n, False)]))
        self.shorts = []
        for n in (1, 2):
            order += 1
            self.shorts.append(self.add(order, 'short', 'Phần III', 'Short %d' % n, [], accepted='42'))

    def sections_of(self, order):
        by_id = {q.id: q for q in QuizQuestion.objects.filter(quiz=self.quiz)}
        return [by_id[i].section for i in order]


@quiz_enabled
class GenerationTest(VariantTestCase):
    def test_unique_and_complete(self):
        data = ev.generate_variants(self.quiz, 6, seed=11)
        self.assertEqual([d['code'] for d in data], ['0101', '0102', '0103', '0104', '0105', '0106'])
        all_ids = {q.id for q in QuizQuestion.objects.filter(quiz=self.quiz)}
        signatures = set()
        for item in data:
            self.assertEqual(set(item['question_order']), all_ids)
            self.assertEqual(len(item['question_order']), len(all_ids))
            for question in QuizQuestion.objects.filter(quiz=self.quiz).prefetch_related('options'):
                self.assertEqual(sorted(item['option_orders'][str(question.id)]),
                                 sorted(o.id for o in question.options.all()))
            signatures.add(ev._signature(item['question_order'], item['option_orders']))
        self.assertEqual(len(signatures), 6)

    def test_sections_keep_order_and_passage_stays_together(self):
        passage_ids = [self.singles[i].id for i in (3, 4, 5)]
        for item in ev.generate_variants(self.quiz, 8, seed=3):
            order = item['question_order']
            sections = self.sections_of(order)
            compact = [s for i, s in enumerate(sections) if i == 0 or sections[i - 1] != s]
            self.assertEqual(compact, ['Phần I', 'Phần II', 'Phần III'])
            positions = [order.index(i) for i in passage_ids]
            self.assertEqual(positions, list(range(positions[0], positions[0] + 3)))   # adjacent, same inner order

    def test_questions_really_move(self):
        moved = [d['question_order'] for d in ev.generate_variants(self.quiz, 4, seed=5)]
        original = [q.id for q in QuizQuestion.objects.filter(quiz=self.quiz)]
        self.assertTrue(all(m != original for m in moved))

    def test_pinned_option_and_fixed_kinds(self):
        pinned = self.singles[6]
        original = [o.id for o in pinned.options.all()]
        for item in ev.generate_variants(self.quiz, 6, seed=9):
            # "Cả A và C" names letters: the whole question keeps its option order, so the text stays true.
            self.assertEqual(item['option_orders'][str(pinned.id)], original)
            for tf in self.tfs:
                self.assertEqual(item['option_orders'][str(tf.id)], [o.id for o in tf.options.all()])
            for short in self.shorts:
                self.assertEqual(item['option_orders'][str(short.id)], [])

    def test_all_of_the_above_keeps_last_position(self):
        question = self.singles[0]
        question.options.all().delete()
        for index, (text, ok) in enumerate([('x1', False), ('x2', True), ('x3', False),
                                            ('Tất cả các đáp án trên', False)], 1):
            QuizOption.objects.create(question=question, order=index, text=text, is_correct=ok)
        last = question.options.order_by('order').last().id
        seen = set()
        for item in ev.generate_variants(self.quiz, 8, seed=2):
            ids = item['option_orders'][str(question.id)]
            self.assertEqual(ids[-1], last)
            seen.add(tuple(ids))
        self.assertGreater(len(seen), 1)

    def test_answer_distribution_even(self):
        for item in ev.generate_variants(self.quiz, 6, seed=1):
            dist = item['distribution']
            self.assertEqual(dist['total'], 12)
            self.assertLessEqual(dist['deviation'], 25.0)
        # With 24 single questions the best of many tries is within the +-10 points tolerance.
        for n in range(13, 37):
            correct = n % 4
            self.add(100 + n, 'single', 'Phần I', 'Extra %d' % n,
                     [('e%d-%d' % (n, i), i == correct) for i in range(4)])
        for item in ev.generate_variants(self.quiz, 6, seed=1):
            self.assertTrue(item['distribution']['even'], item['distribution'])

    def test_deterministic_with_seed(self):
        self.assertEqual(ev.generate_variants(self.quiz, 3, seed=42), ev.generate_variants(self.quiz, 3, seed=42))

    def test_refuses_impossible(self):
        tiny = Quiz.objects.create(title='Tiny', slug='tiny', creator=self.teacher)
        question = QuizQuestion.objects.create(quiz=tiny, kind='short', text='x', accepted_answers='1')
        self.assertTrue(question.id)
        with self.assertRaises(ev.VariantError):
            ev.generate_variants(tiny, 3, seed=1)
        with self.assertRaises(ev.VariantError):
            ev.generate_variants(self.quiz, 1)
        with self.assertRaises(ev.VariantError):
            ev.generate_variants(self.quiz, 13)

    def test_refuses_when_drawing_subset(self):
        Quiz.objects.filter(pk=self.quiz.pk).update(questions_per_attempt=5)
        self.quiz.refresh_from_db()
        with self.assertRaises(ev.VariantError):
            ev.generate_variants(self.quiz, 4)

    def test_answer_key(self):
        item = ev.generate_variants(self.quiz, 2, seed=8)[0]
        questions = list(self.quiz.questions.prefetch_related('options'))
        rows = ev.answer_key(questions, item['question_order'], item['option_orders'])
        self.assertEqual(len(rows), 16)
        for row in rows:
            if row['kind'] == 'single':
                self.assertIn(row['key'], ('A', 'B', 'C', 'D'))
            elif row['kind'] == 'tf4':
                self.assertEqual(len(row['key']), 4)
            else:
                self.assertEqual(row['key'], '42')


@quiz_enabled
class SaveTest(VariantTestCase):
    def test_save_replaces_and_locks(self):
        first = ev.save_variants(self.quiz, 4, seed=1)
        self.assertEqual(len(first), 4)
        second = ev.save_variants(self.quiz, 3, start_code='A1', seed=2)
        self.assertEqual([v.code for v in second], ['A1', 'A2', 'A3'])
        self.assertEqual(ExamVariant.objects.filter(quiz=self.quiz).count(), 3)
        student = self.make_user('s1')
        QuizAttempt.objects.create(quiz=self.quiz, user=student, seed=1, variant=second[0])
        with self.assertRaises(ev.VariantError):
            ev.save_variants(self.quiz, 4, seed=3)
        self.assertEqual(ExamVariant.objects.filter(quiz=self.quiz).count(), 3)


@quiz_enabled
class OnlineTest(VariantTestCase):
    def start(self, profile):
        client = self.client_class()
        client.defaults['HTTP_ACCEPT_LANGUAGE'] = 'en'
        self.assertTrue(client.login(username=profile.user.username, password='pw'))
        response = client.post(reverse('quiz_start', args=(self.quiz.slug,)))
        self.assertEqual(response.status_code, 302)
        return client, QuizAttempt.objects.get(quiz=self.quiz, user=profile)

    def test_balanced_assignment(self):
        ev.save_variants(self.quiz, 4, seed=1)
        counts = Counter()
        for n in range(40):
            profile = self.make_user('st%d' % n)
            attempt = QuizAttempt.objects.create(quiz=self.quiz, user=profile, seed=1000 + n)
            counts[ev.assign_variant(attempt).code] += 1
        self.assertEqual(sorted(counts.values()), [10, 10, 10, 10])

    def test_page_follows_variant(self):
        Quiz.objects.filter(pk=self.quiz.pk).update(mode='exam')   # the paper code is shown on exam pages
        variants = ev.save_variants(self.quiz, 3, seed=4)
        profile = self.make_user('stu')
        client, attempt = self.start(profile)
        self.assertIsNotNone(attempt.variant)
        variant = attempt.variant
        page = client.get(reverse('quiz_attempt', args=(self.quiz.slug, attempt.id)))
        self.assertEqual(page.status_code, 200)
        html = page.content.decode()
        shown = [int(i) for i in re.findall(r'<section class="qz-question" id="q(\d+)"', html)]
        self.assertEqual(shown, variant.question_order)
        self.assertIn(variant.code, html)
        # options of one question appear in the variant's order
        question = self.singles[0]
        position = html.index('id="q%d"' % question.id)
        chunk = html[position:position + 6000]
        texts = [o.text for o in QuizOption.objects.filter(pk__in=variant.option_orders[str(question.id)])]
        indexes = {text: chunk.find(text) for text in texts}
        wanted = [QuizOption.objects.get(pk=i).text for i in variant.option_orders[str(question.id)]]
        self.assertEqual(sorted(indexes, key=indexes.get), wanted)
        self.assertEqual(len(variants), 3)

    def grade_by_content(self, attempt, wrong_every):
        """Choose by option text: the 'ok' option for most questions, a wrong one for every `wrong_every`th."""
        answers = {}
        for q in self.singles:
            options = list(q.options.all())
            if int(q.text.split()[-1]) % wrong_every == 0:
                chosen = [o for o in options if not o.is_correct][0]
            else:
                chosen = [o for o in options if o.is_correct][0]
            answers[str(q.id)] = [chosen.id]
        for q in self.tfs:
            answers[str(q.id)] = {str(o.id): o.is_correct for o in q.options.all()}
        for q in self.shorts:
            answers[str(q.id)] = '42'
        attempt.finish(answers)
        attempt.refresh_from_db()
        return attempt

    def test_same_content_same_score_in_every_variant(self):
        ev.save_variants(self.quiz, 4, seed=6)
        scores = set()
        for index, variant in enumerate(ExamVariant.objects.filter(quiz=self.quiz)):
            profile = self.make_user('g%d' % index)
            attempt = QuizAttempt.objects.create(quiz=self.quiz, user=profile, seed=index + 1, variant=variant)
            attempt = self.grade_by_content(attempt, 3)
            scores.add((attempt.score, attempt.correct_count))
        self.assertEqual(len(scores), 1)
        self.assertEqual(scores.pop(), (12.0, 12))   # 12 singles, 4 of them wrong -> 8 + 2 tf + 2 short

    def test_result_page_and_stats_by_original_id(self):
        ev.save_variants(self.quiz, 2, seed=7)
        variants = list(ExamVariant.objects.filter(quiz=self.quiz))
        for index, variant in enumerate(variants):
            profile = self.make_user('r%d' % index)
            attempt = QuizAttempt.objects.create(quiz=self.quiz, user=profile, seed=index + 5, variant=variant)
            self.grade_by_content(attempt, 4)
            client = self.client_class()
            client.defaults['HTTP_ACCEPT_LANGUAGE'] = 'en'
            client.login(username=profile.user.username, password='pw')
            response = client.get(reverse('quiz_result', args=(self.quiz.slug, attempt.id)))
            self.assertEqual(response.status_code, 200)
            html = response.content.decode()
            order = [int(n) for n in re.findall(r'<p>Question (\d+)</p>', html)]
            expected = [int(q.text.split()[-1]) for q in ev.questions_in_order(
                variant, list(self.quiz.questions.prefetch_related('options'))) if q.text.startswith('Question')]
            self.assertEqual(order, expected)
        rows = quiz_stats.exam_ranking(self.quiz)
        accuracy = quiz_stats.question_accuracy(self.quiz, rows)
        self.assertEqual(len(accuracy), 16)
        by_text = {q.text: percent for q, percent, _answered in accuracy}
        # Question 4, 8 and 12 were answered wrongly by both candidates whatever their code: 0 percent.
        self.assertEqual(by_text['Question 4'], 0)
        self.assertEqual(by_text['Question 1'], 100)

    def test_no_variant_keeps_old_behaviour(self):
        Quiz.objects.filter(pk=self.quiz.pk).update(mode='exam')
        profile = self.make_user('old')
        client, attempt = self.start(profile)
        self.assertIsNone(attempt.variant)
        html = client.get(reverse('quiz_attempt', args=(self.quiz.slug, attempt.id))).content.decode()
        shown = [int(i) for i in re.findall(r'<section class="qz-question" id="q(\d+)"', html)]
        self.assertEqual(sorted(shown), sorted(q.id for q in QuizQuestion.objects.filter(quiz=self.quiz)))
        self.assertEqual(shown, [q.id for q in attempt.ordered_questions()])
        self.assertIn(attempt.exam_code, html)

    def test_drawn_quiz_gets_no_variant(self):
        ev.save_variants(self.quiz, 2, seed=1)
        Quiz.objects.filter(pk=self.quiz.pk).update(questions_per_attempt=5)
        profile = self.make_user('drawn')
        client, attempt = self.start(profile)
        self.assertIsNone(attempt.variant)


@quiz_enabled
class PagesTest(VariantTestCase):
    def setUp(self):
        super().setUp()
        self.variants = ev.save_variants(self.quiz, 3, seed=2)
        self.student = self.make_user('plain')

    def login(self, name):
        self.assertTrue(self.client.login(username=name, password='pw'))

    def test_permissions(self):
        urls = [reverse('quiz_variants', args=(self.quiz.slug,)),
                reverse('quiz_variant_print', args=(self.quiz.slug, '0101')),
                reverse('quiz_variants_key_print', args=(self.quiz.slug,))]
        for url in urls:
            self.assertIn(self.client.get(url).status_code, (302, 403, 404))   # anonymous
        self.login('plain')
        for url in urls:
            self.assertIn(self.client.get(url).status_code, (403, 404))
        self.assertIn(self.client.post(urls[0], {'count': 3}).status_code, (403, 404))
        self.assertEqual(ExamVariant.objects.filter(quiz=self.quiz).count(), 3)

    def test_teacher_pages(self):
        self.login('teacher')
        response = self.client.get(reverse('quiz_variants', args=(self.quiz.slug,)))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        for variant in self.variants:
            self.assertIn(variant.code, html)
        response = self.client.get(reverse('quiz_variant_print', args=(self.quiz.slug, '0102')))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        for n in range(1, 13):
            self.assertIn('Question %d' % n, html)
        self.assertEqual(html.count('class="vx-q"'), 16)
        self.assertIn('window.print()', html)
        self.assertIn('@page', html)
        self.assertEqual(self.client.get(reverse('quiz_variant_print', args=(self.quiz.slug, '9999'))).status_code, 404)
        response = self.client.get(reverse('quiz_variants_key_print', args=(self.quiz.slug,)))
        self.assertEqual(response.status_code, 200)
        self.assertIn('0103', response.content.decode())

    def test_teacher_generates(self):
        self.login('teacher')
        response = self.client.post(reverse('quiz_variants', args=(self.quiz.slug,)),
                                    {'count': 5, 'start_code': '0201', 'shuffle_questions': '1',
                                     'shuffle_options': '1'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(list(ExamVariant.objects.filter(quiz=self.quiz).values_list('code', flat=True)),
                         ['0201', '0202', '0203', '0204', '0205'])
        self.client.post(reverse('quiz_variants', args=(self.quiz.slug,)), {'count': 99, 'start_code': '0201'})
        self.assertEqual(ExamVariant.objects.filter(quiz=self.quiz).count(), 5)
