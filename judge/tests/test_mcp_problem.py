import json
import zipfile
from unittest import mock

from django.core.cache import cache
from django.test import TestCase, override_settings

from judge.models import (Language, Organization, Problem, ProblemData, ProblemGroup, ProblemType, Submission,
                          problem_data_storage)
from judge.tests.test_mcp_core import make_token, make_user
from judge.tests.test_mcp_quiz import call

CASES = [{'input': '1 2', 'output': '3'}, {'input': '5 7', 'output': '12'}, {'input': '0 0', 'output': '0'}]
PY_SOURCE = 'a, b = map(int, input().split())\nprint(a + b)\n'


@override_settings(MCP_ENABLED=True, MCP_RATE_LIMIT_PER_MINUTE=1000)
class McpProblemTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        ProblemGroup.objects.get_or_create(name='Uncategorized', defaults={'full_name': 'Uncategorized'})
        ProblemType.objects.get_or_create(name='uncategorized', defaults={'full_name': 'Uncategorized'})
        ProblemType.objects.get_or_create(name='math', defaults={'full_name': 'Toán học'})
        Language.objects.update(include_in_problem=False)
        cls.python, _created = Language.objects.get_or_create(key='PY3', defaults={
            'name': 'Python 3', 'short_name': 'PY3', 'common_name': 'Python', 'ace': 'python', 'pygments': 'python',
            'extension': 'py'})
        Language.objects.filter(id=cls.python.id).update(include_in_problem=True, file_only=False, name='Python 3')
        cls.org = Organization.objects.create(name='School', slug='school', short_name='SC', about='x')
        cls.author = make_user('prob_author', ['add_problem', 'edit_own_problem'])
        cls.author_tok = make_token(cls.author, 'prob-author-token-012345678')
        cls.other = make_user('prob_other', ['add_problem', 'edit_own_problem'])
        cls.other_tok = make_token(cls.other, 'prob-other-token-0123456789')
        cls.org_admin = make_user('prob_org_admin', ['create_organization_problem', 'edit_own_problem'])
        cls.org.admins.add(cls.org_admin.profile)
        cls.org_tok = make_token(cls.org_admin, 'prob-orgadmin-token-01234567')
        cls.quiz_only = make_user('prob_quiz_only', ['add_quiz'])
        cls.quiz_only_tok = make_token(cls.quiz_only, 'prob-quizonly-token-0123456')

    def setUp(self):
        cache.clear()

    def create(self, token=None, **extra):
        args = {'code': 'tong2so', 'name': 'Tổng hai số', 'statement': 'Cho a, b. In ra a + b.\n\n**Input**: a b'}
        args.update(extra)
        return call(self.client, token or self.author_tok, 'problem_create', args)

    def test_tools_listed(self):
        from judge.tests.test_mcp_core import rpc
        names = [t['name'] for t in rpc(self.client, self.author_tok, 'tools/list').json()['result']['tools']]
        for name in ('problem_create', 'problem_update', 'problem_set_tests', 'problem_languages',
                     'problem_submit_check', 'problem_check_result', 'problem_list_mine'):
            self.assertIn(name, names)

    def test_create_global_problem_is_private(self):
        error, data = self.create(time_limit_seconds=2, memory_limit_mb=128, points=1.5)
        self.assertFalse(error, data)
        problem = Problem.objects.get(code='tong2so')
        self.assertFalse(problem.is_public)
        self.assertEqual((problem.time_limit, problem.memory_limit, problem.points), (2.0, 131072, 1.5))
        self.assertEqual(list(problem.curators.all()), [self.author.profile])
        self.assertEqual(list(problem.allowed_languages.all()), [self.python])
        self.assertIn('a + b', problem.description)
        self.assertEqual(data['memory_limit_mb'], 128)
        self.assertEqual(list(problem.types.values_list('name', flat=True)), ['uncategorized'])

    def test_create_with_types_and_group(self):
        error, data = self.create(types=['math'])
        self.assertFalse(error, data)
        self.assertEqual(list(Problem.objects.get(code='tong2so').types.values_list('name', flat=True)), ['math'])
        self.assertTrue(self.create(code='b2', types=['khong-co'])[0])
        self.assertTrue(self.create(code='b3', group='khong-co')[0])

    def test_create_needs_permission_and_valid_input(self):
        error, text = self.create(token=self.quiz_only_tok)
        self.assertTrue(error)
        self.assertIn('quyền', text)
        for extra in ({'code': 'HoaThuong'}, {'code': 'có dấu'}, {'name': ''}, {'statement': '  '},
                      {'time_limit_seconds': 60}, {'memory_limit_mb': -1}):
            self.assertTrue(self.create(**extra)[0], extra)
        self.assertEqual(Problem.objects.count(), 0)
        self.assertFalse(self.create()[0])
        self.assertTrue(self.create()[0], 'duplicate code')

    def test_create_needs_edit_own_problem_too(self):
        creator = make_user('prob_create_only', ['add_problem'])
        error, text = self.create(token=make_token(creator, 'prob-createonly-token-0123456'))
        self.assertTrue(error)
        self.assertIn('edit_own_problem', text)
        self.assertEqual(Problem.objects.count(), 0)

    def test_create_in_organization(self):
        error, text = self.create(token=self.org_tok, organization='school')
        self.assertTrue(error)
        self.assertIn('school_', text)
        with mock.patch('judge.mcp.tools.problem.on_new_problem') as hook:
            error, data = self.create(token=self.org_tok, organization='school', code='school_tong')
        self.assertFalse(error, data)
        hook.delay.assert_called_once_with('school_tong')
        problem = Problem.objects.get(code='school_tong')
        self.assertTrue(problem.is_organization_private)
        self.assertEqual(problem.organization, self.org)
        self.assertEqual(list(problem.authors.all()), [self.org_admin.profile])
        self.assertFalse(problem.is_public)
        self.assertTrue(self.create(token=self.author_tok, organization='school', code='school_x')[0])

    def test_update(self):
        self.create()
        error, data = call(self.client, self.author_tok, 'problem_update',
                           {'code': 'tong2so', 'statement': 'Đề mới', 'points': 2, 'time_limit_seconds': 3})
        self.assertFalse(error, data)
        problem = Problem.objects.get(code='tong2so')
        self.assertEqual((problem.description, problem.points, problem.time_limit), ('Đề mới', 2.0, 3.0))
        self.assertEqual(problem.name, 'Tổng hai số')
        self.assertTrue(problem.partial)
        self.assertEqual(list(problem.types.values_list('name', flat=True)), ['uncategorized'])
        error, _ = call(self.client, self.other_tok, 'problem_update', {'code': 'tong2so', 'name': 'hack'})
        self.assertTrue(error)
        self.assertTrue(call(self.client, self.author_tok, 'problem_update', {'code': 'tong2so'})[0])

    def test_set_tests(self):
        self.create()
        error, data = call(self.client, self.author_tok, 'problem_set_tests', {'code': 'tong2so', 'cases': CASES})
        self.assertFalse(error, data)
        self.assertEqual((data['test_count'], data['total_points']), (3, 100))
        problem = Problem.objects.get(code='tong2so')
        self.assertEqual(list(problem.cases.order_by('order').values_list('points', flat=True)), [33, 33, 34])
        data_row = ProblemData.objects.get(problem=problem)
        self.assertEqual(data_row.feedback, '')
        with zipfile.ZipFile(data_row.zipfile.path) as archive:
            self.assertEqual(sorted(archive.namelist()), ['1.in', '1.out', '2.in', '2.out', '3.in', '3.out'])
            self.assertEqual(archive.read('2.in'), b'5 7\n')
            self.assertEqual(archive.read('2.out'), b'12\n')
        self.assertTrue(problem_data_storage.exists('tong2so/init.yml'))
        yml = problem_data_storage.open('tong2so/init.yml').read().decode()
        self.assertIn('1.in', yml)
        self.assertIn('archive', yml)

        # replacing: fewer cases, explicit points, a floats checker
        error, data = call(self.client, self.author_tok, 'problem_set_tests', {
            'code': 'tong2so', 'checker': 'floats', 'float_precision': 3,
            'cases': [{'input': '1', 'output': '1.0', 'points': 40}, {'input': '2', 'output': '2.0', 'points': 60}]})
        self.assertFalse(error, data)
        problem.refresh_from_db()
        self.assertEqual(problem.cases.count(), 2)
        data_row = ProblemData.objects.get(problem=problem)
        self.assertEqual((data_row.checker, json.loads(data_row.checker_args)), ('floats', {'precision': 3}))
        with zipfile.ZipFile(data_row.zipfile.path) as archive:
            self.assertEqual(sorted(archive.namelist()), ['1.in', '1.out', '2.in', '2.out'])
        self.assertEqual(data_row.zipfile.name.count('/'), 1)

    def test_set_tests_validation(self):
        self.create()
        bad_inputs = [
            [],
            [{'input': '1'}],
            [{'input': 1, 'output': '1'}],
            [{'input': '1', 'output': '1', 'points': 10}, {'input': '2', 'output': '2'}],
            [{'input': '1', 'output': '1', 'points': -5}],
            [{'input': '1', 'output': '1', 'points': 0}],
            [{'input': 'x' * (900 * 1024), 'output': '1'}],
            [{'input': '1', 'output': '1'}] * 51,
        ]
        for cases in bad_inputs:
            error, _ = call(self.client, self.author_tok, 'problem_set_tests', {'code': 'tong2so', 'cases': cases})
            self.assertTrue(error, str(cases)[:60])
        self.assertTrue(call(self.client, self.author_tok, 'problem_set_tests',
                             {'code': 'tong2so', 'cases': CASES, 'checker': 'nope'})[0])
        self.assertFalse(Problem.objects.get(code='tong2so').cases.exists())
        self.assertTrue(call(self.client, self.other_tok, 'problem_set_tests', {'code': 'tong2so', 'cases': CASES})[0])
        self.assertTrue(call(self.client, self.author_tok, 'problem_set_tests',
                             {'code': 'khong-co', 'cases': CASES})[0])

    def test_languages(self):
        self.create()
        error, data = call(self.client, self.author_tok, 'problem_languages', {'code': 'tong2so'})
        self.assertFalse(error)
        self.assertEqual(data['languages'], [{'key': 'PY3', 'name': 'Python 3'}])

    def test_submit_check_and_result(self):
        self.create()
        args = {'code': 'tong2so', 'language': 'PY3', 'source': PY_SOURCE}
        error, text = call(self.client, self.author_tok, 'problem_submit_check', args)
        self.assertTrue(error)
        self.assertIn('test', text)
        call(self.client, self.author_tok, 'problem_set_tests', {'code': 'tong2so', 'cases': CASES})
        self.assertTrue(call(self.client, self.author_tok, 'problem_submit_check', dict(args, language='COBOL'))[0])
        self.assertTrue(call(self.client, self.author_tok, 'problem_submit_check', dict(args, source=' '))[0])
        self.assertTrue(call(self.client, self.other_tok, 'problem_submit_check', args)[0])
        with mock.patch.object(Submission, 'judge') as judge:
            error, data = call(self.client, self.author_tok, 'problem_submit_check', args)
        self.assertFalse(error, data)
        judge.assert_called_once_with(force_judge=True)
        submission = Submission.objects.get(id=data['submission_id'])
        self.assertEqual((submission.user, submission.language, submission.source.source),
                         (self.author.profile, self.python, PY_SOURCE))

        error, result = call(self.client, self.author_tok, 'problem_check_result', {'submission_id': submission.id})
        self.assertFalse(error)
        self.assertFalse(result['finished'])
        Submission.objects.filter(id=submission.id).update(status='D', result='AC', points=100, case_points=100,
                                                           case_total=100, time=0.02, memory=9000)
        submission.test_cases.create(case=1, status='AC', time=0.01, points=33, total=33)
        error, result = call(self.client, self.author_tok, 'problem_check_result', {'submission_id': submission.id})
        self.assertTrue(result['finished'])
        self.assertEqual((result['result'], result['points']), ('AC', 100))
        self.assertEqual(result['cases'][0]['status'], 'AC')
        self.assertTrue(call(self.client, self.other_tok, 'problem_check_result', {'submission_id': submission.id})[0])

    def test_list_mine(self):
        self.create()
        self.create(token=self.other_tok, code='cua_nguoi_khac')
        error, data = call(self.client, self.author_tok, 'problem_list_mine')
        self.assertFalse(error)
        self.assertEqual([p['code'] for p in data['problems']], ['tong2so'])
        self.assertEqual(data['problems'][0]['test_count'], 0)
