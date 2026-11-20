from django.test import SimpleTestCase

from judge.utils import quiz_grading
from judge.utils.quiz_parser import parse_quiz_lines

TF_OPTIONS = [(1, True), (2, False), (3, True), (4, False)]


class TF4GradingTest(SimpleTestCase):
    def grade(self, verdicts):
        return quiz_grading.score_fraction('tf4', verdicts, options=TF_OPTIONS)

    def test_ladder(self):
        # right answers: 1 true, 2 false, 3 true, 4 false
        self.assertEqual(self.grade({'1': True, '2': False, '3': True, '4': False}), 1.0)
        self.assertEqual(self.grade({'1': True, '2': False, '3': True, '4': True}), 0.5)
        self.assertEqual(self.grade({'1': True, '2': False, '3': False, '4': True}), 0.25)
        self.assertEqual(self.grade({'1': True, '2': True, '3': False, '4': True}), 0.1)
        self.assertEqual(self.grade({'1': False, '2': True, '3': False, '4': True}), 0.0)

    def test_unanswered_statements_are_wrong(self):
        self.assertEqual(self.grade({'1': True}), 0.1)
        self.assertEqual(self.grade({}), 0.0)
        self.assertEqual(self.grade(None), 0.0)

    def test_garbage_is_ignored(self):
        self.assertEqual(self.grade({'x': True, '1': True, '2': False, '3': True, '4': False}), 1.0)
        self.assertEqual(self.grade(['1', '3']), 0.0)

    def test_standard_paper_adds_up_to_ten(self):
        # THPTQG 2025: 24 x 0.25 + 4 x 1.0
        self.assertEqual(24 * 0.25 + 4 * 1.0, 10.0)


class ChoiceGradingTest(SimpleTestCase):
    OPTIONS = [(1, False), (2, True), (3, True)]

    def test_single_and_multi_are_all_or_nothing(self):
        self.assertEqual(quiz_grading.score_fraction('multi', [2, 3], options=self.OPTIONS), 1.0)
        self.assertEqual(quiz_grading.score_fraction('multi', [2], options=self.OPTIONS), 0.0)
        self.assertEqual(quiz_grading.score_fraction('multi', [], options=self.OPTIONS), 0.0)
        self.assertEqual(quiz_grading.score_fraction('single', ['2'], options=[(1, False), (2, True)]), 1.0)

    def test_short_answer(self):
        self.assertEqual(quiz_grading.score_fraction('short', '  Bảy ', accepted=['7', 'bảy']), 1.0)
        self.assertEqual(quiz_grading.score_fraction('short', '8', accepted=['7']), 0.0)
        self.assertEqual(quiz_grading.score_fraction('short', '', accepted=['']), 0.0)

    def test_is_answered(self):
        self.assertTrue(quiz_grading.is_answered('tf4', {'1': False}))
        self.assertFalse(quiz_grading.is_answered('tf4', {}))
        self.assertTrue(quiz_grading.is_answered('single', [1]))
        self.assertFalse(quiz_grading.is_answered('short', '  '))


class TF4ParserTest(SimpleTestCase):
    def parse(self, text):
        return parse_quiz_lines(text.strip().splitlines())

    def test_lowercase_four_statements_is_tf4(self):
        questions, errors, _ = self.parse('''
[sec] Phần II
[qus] Phát biểu nào đúng?
a) Một
b) Hai
c) Ba
d) Bốn
[ans] a, c
''')
        self.assertEqual(errors, [])
        q = questions[0]
        self.assertEqual(q['kind'], 'tf4')
        self.assertEqual(q['section'], 'Phần II')
        self.assertEqual([o['correct'] for o in q['options']], [True, False, True, False])

    def test_explicit_type_and_none_true(self):
        questions, errors, _ = self.parse('''
[qus] Tất cả đều sai
[type] tf
A. Một
B. Hai
C. Ba
D. Bốn
[ans] không
''')
        self.assertEqual(errors, [])
        self.assertEqual(questions[0]['kind'], 'tf4')
        self.assertFalse(any(o['correct'] for o in questions[0]['options']))

    def test_tf_needs_exactly_four_statements(self):
        _, errors, _ = self.parse('''
[qus] Thiếu ý
[type] tf
a) Một
b) Hai
c) Ba
[ans] a
''')
        self.assertTrue(any('exactly 4' in e['message'] for e in errors))

    def test_uppercase_four_options_stay_single_choice(self):
        questions, errors, _ = self.parse('''
[qus] Trắc nghiệm thường
A. Một
B. Hai
C. Ba
D. Bốn
[ans] B
''')
        self.assertEqual(errors, [])
        self.assertEqual(questions[0]['kind'], 'single')

    def test_section_is_sticky(self):
        questions, _, _ = self.parse('''
[sec] Phần I
[qus] Câu 1
A. x
B. y
[ans] A
[qus] Câu 2
A. x
B. y
[ans] B
''')
        self.assertEqual([q['section'] for q in questions], ['Phần I', 'Phần I'])
