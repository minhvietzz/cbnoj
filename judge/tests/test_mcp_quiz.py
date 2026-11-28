import json

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone

from judge.models import BankQuestion, ClassMember, Classroom, Organization, Quiz, RoleInClass
from judge.tests.test_mcp_core import make_token, make_user, rpc

GOOD = """[sec] Phần I
[qus] Thủ đô của Việt Nam là gì?
A. Huế
B. Hà Nội
C. Đà Nẵng
D. Cần Thơ
[ans] B
[pts] 0.5

[qus] Chọn các số chẵn
A. 1
B. 2
C. 4
D. 5
[ans] B, C
[pts] 0.5

[qus] 2 + 3 = ?
[ans] 5|năm
[pts] 1
"""
BAD = """[qus] Câu thiếu đáp án
A. x
B. y
"""


def call(client, token, name, arguments=None):
    r = rpc(client, token, 'tools/call', {'name': name, 'arguments': arguments or {}})
    result = r.json()['result']
    text = result['content'][0]['text']
    try:
        return result['isError'], json.loads(text)
    except ValueError:
        return result['isError'], text


@override_settings(MCP_ENABLED=True, MCP_RATE_LIMIT_PER_MINUTE=1000)
class McpQuizTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.teacher = make_user('quiz_teacher', ['add_quiz'])
        cls.tok = make_token(cls.teacher, 'quiz-teacher-token-0123456')
        cls.other = make_user('quiz_other_teacher', ['add_quiz'])
        cls.other_tok = make_token(cls.other, 'quiz-other-token-01234567')
        cls.org_admin = make_user('quiz_org_admin')
        cls.org = Organization.objects.create(name='School', slug='school', short_name='SC', about='x')
        cls.org.admins.add(cls.org_admin.profile)
        cls.org_tok = make_token(cls.org_admin, 'quiz-orgadmin-token-0123456')

    def setUp(self):
        cache.clear()

    def test_tools_are_listed(self):
        names = [t['name'] for t in rpc(self.client, self.tok, 'tools/list').json()['result']['tools']]
        for name in ('quiz_format_help', 'quiz_preview', 'quiz_create', 'quiz_configure', 'quiz_list_mine',
                     'quiz_results'):
            self.assertIn(name, names)

    def test_help(self):
        error, text = call(self.client, self.tok, 'quiz_format_help')
        self.assertFalse(error)
        self.assertIn('[qus]', text)

    def test_preview_good_and_bad(self):
        error, data = call(self.client, self.tok, 'quiz_preview', {'text': GOOD})
        self.assertFalse(error)
        self.assertTrue(data['ok'])
        self.assertEqual(data['question_count'], 3)
        self.assertEqual(data['total_points'], 2.0)
        self.assertEqual(data['by_kind'], {'single': 1, 'multi': 1, 'short': 1})
        self.assertEqual(data['first_questions_as_understood'][0]['correct'], ['B'])
        self.assertEqual(data['first_questions_as_understood'][1]['correct'], ['B', 'C'])
        self.assertEqual(data['first_questions_as_understood'][2]['accepted_answers'], ['5', 'năm'])
        error, data = call(self.client, self.tok, 'quiz_preview', {'text': BAD})
        self.assertFalse(error)
        self.assertFalse(data['ok'])
        self.assertTrue(data['errors'])
        self.assertEqual(Quiz.objects.count(), 0)

    def test_preview_empty_and_no_questions(self):
        self.assertTrue(call(self.client, self.tok, 'quiz_preview', {'text': '   '})[0])
        error, data = call(self.client, self.tok, 'quiz_preview', {'text': 'chỉ là chữ thường'})
        self.assertFalse(data['ok'])

    def test_create_private_quiz(self):
        error, data = call(self.client, self.tok, 'quiz_create', {
            'title': 'Kiểm tra  thử', 'text': GOOD, 'time_limit': 20, 'shuffle_questions': True})
        self.assertFalse(error, data)
        quiz = Quiz.objects.get(slug=data['slug'])
        self.assertEqual(quiz.title, 'Kiểm tra thử')
        self.assertEqual(quiz.creator_id, self.teacher.profile.id)
        self.assertFalse(quiz.is_public)
        self.assertEqual(quiz.mode, 'practice')
        self.assertEqual(quiz.time_limit, 20)
        self.assertTrue(quiz.shuffle_questions)
        self.assertEqual(quiz.source_name, 'MCP')
        self.assertEqual(quiz.questions.count(), 3)
        first = quiz.questions.get(order=1)
        self.assertEqual([o.text for o in first.options.filter(is_correct=True)], ['Hà Nội'])
        self.assertEqual(first.section, 'Phần I')
        self.assertEqual(float(quiz.total_points), 2.0)
        self.assertEqual(data['bank'], {'added': 3, 'already_existed': 0})
        self.assertEqual(BankQuestion.objects.count(), 3)
        self.assertTrue(data['url'].startswith('http://testserver/quiz/'))

    def test_create_refuses_bad_text_and_creates_nothing(self):
        error, text = call(self.client, self.tok, 'quiz_create', {'title': 'Hỏng', 'text': BAD})
        self.assertTrue(error)
        self.assertIn('lỗi', text)
        self.assertEqual(Quiz.objects.count(), 0)

    def test_create_is_idempotent_for_retries(self):
        args = {'title': 'Bài lặp', 'text': GOOD}
        _, first = call(self.client, self.tok, 'quiz_create', args)
        error, second = call(self.client, self.tok, 'quiz_create', args)
        self.assertFalse(error)
        self.assertEqual(second['id'], first['id'])
        self.assertIn('note', second)
        self.assertEqual(Quiz.objects.count(), 1)

    def test_organization_admin_without_global_permission(self):
        error, data = call(self.client, self.org_tok, 'quiz_create',
                           {'title': 'Thi tổ chức', 'text': GOOD, 'organization': 'school', 'time_limit': 30})
        self.assertFalse(error, data)
        quiz = Quiz.objects.get(slug=data['slug'])
        self.assertEqual(quiz.mode, 'exam')
        self.assertFalse(quiz.is_public)
        self.assertEqual(list(quiz.organizations.all()), [self.org])
        self.assertIsNotNone(quiz.start_time)
        self.assertGreater(quiz.start_time, timezone.now())

    def test_cannot_use_someone_elses_organization_or_class(self):
        error, _ = call(self.client, self.tok, 'quiz_create', {'title': 'x', 'text': GOOD, 'organization': 'school'})
        self.assertTrue(error)
        classroom = Classroom.objects.create(name='10A1', slug='10a1', organization=self.org, school_year='2026',
                                             join_code='J1')
        error, _ = call(self.client, self.tok, 'quiz_create', {'title': 'x', 'text': GOOD, 'class_id': classroom.id})
        self.assertTrue(error)
        self.assertEqual(Quiz.objects.count(), 0)

    def test_class_manager_can_create_for_class(self):
        classroom = Classroom.objects.create(name='10A2', slug='10a2', organization=self.org, school_year='2026',
                                             join_code='J2')
        homeroom = make_user('quiz_homeroom')
        ClassMember.objects.create(classroom=classroom, user=homeroom.profile, role=RoleInClass.HOMEROOM)
        token = make_token(homeroom, 'quiz-homeroom-token-012345')
        error, data = call(self.client, token, 'quiz_create',
                           {'title': 'Thi lớp', 'text': GOOD, 'class_id': classroom.id})
        self.assertFalse(error, data)
        quiz = Quiz.objects.get(slug=data['slug'])
        self.assertEqual(list(quiz.classes.all()), [classroom])
        self.assertEqual(quiz.mode, 'exam')

    def test_configure_exam_window_in_vietnam_time(self):
        _, data = call(self.client, self.tok, 'quiz_create', {'title': 'Cấu hình', 'text': GOOD})
        error, result = call(self.client, self.tok, 'quiz_configure', {
            'slug': data['slug'], 'mode': 'exam', 'start_time': '2030-12-05 07:30', 'end_time': '2030-12-05 09:00',
            'time_limit': 45, 'proctoring': 'strict', 'max_violations': 3, 'results_release': 'after_end'})
        self.assertFalse(error, result)
        quiz = Quiz.objects.get(slug=data['slug'])
        self.assertEqual(quiz.mode, 'exam')
        self.assertEqual(quiz.start_time.strftime('%Y-%m-%d %H:%M'), '2030-12-05 00:30')  # 07:30 +07 = 00:30 UTC
        self.assertEqual(quiz.end_time.strftime('%H:%M'), '02:00')
        self.assertEqual((quiz.time_limit, quiz.proctoring, quiz.results_release), (45, 'strict', 'after_end'))
        self.assertEqual(result['window_vn'], ['2030-12-05 07:30', '2030-12-05 09:00'])
        self.assertFalse(quiz.is_public)
        self.assertEqual(quiz.questions.count(), 3)

    def test_configure_rejects_bad_input_and_keeps_quiz(self):
        _, data = call(self.client, self.tok, 'quiz_create', {'title': 'Giữ nguyên', 'text': GOOD})
        slug = data['slug']
        for args in ({'mode': 'exam'},  # exam needs a window
                     {'mode': 'exam', 'start_time': '2030-12-05 09:00', 'end_time': '2030-12-05 08:00'},
                     {'start_time': 'ngày mai'},
                     {'proctoring': 'ultra'},
                     {'is_public': True}):
            error, _ = call(self.client, self.tok, 'quiz_configure', dict(args, slug=slug))
            self.assertTrue(error, args)
        quiz = Quiz.objects.get(slug=slug)
        self.assertEqual((quiz.mode, quiz.is_public, quiz.proctoring), ('practice', False, 'off'))

    def test_configure_and_results_need_manage_rights(self):
        _, data = call(self.client, self.tok, 'quiz_create', {'title': 'Của tôi', 'text': GOOD})
        error, _ = call(self.client, self.other_tok, 'quiz_configure', {'slug': data['slug'], 'time_limit': 5})
        self.assertTrue(error)
        error, _ = call(self.client, self.other_tok, 'quiz_results', {'slug': data['slug']})
        self.assertTrue(error)
        self.assertEqual(Quiz.objects.get(slug=data['slug']).time_limit, 0)
        error, _ = call(self.client, self.tok, 'quiz_configure', {'slug': 'khong-co', 'time_limit': 5})
        self.assertTrue(error)

    def test_list_mine_shows_only_own_quizzes(self):
        call(self.client, self.tok, 'quiz_create', {'title': 'A', 'text': GOOD})
        call(self.client, self.other_tok, 'quiz_create', {'title': 'B', 'text': GOOD})
        error, data = call(self.client, self.tok, 'quiz_list_mine')
        self.assertFalse(error)
        self.assertEqual([q['title'] for q in data['quizzes']], ['A'])
        self.assertEqual(data['quizzes'][0]['questions'], 3)

    def test_results_with_no_attempts(self):
        _, data = call(self.client, self.tok, 'quiz_create', {'title': 'Chưa ai làm', 'text': GOOD})
        error, result = call(self.client, self.tok, 'quiz_results', {'slug': data['slug']})
        self.assertFalse(error, result)
        self.assertEqual(result['candidates'], 0)
        self.assertIsNone(result['average_score10'])
