# flake8: noqa: E501
import json
from unittest import mock

from django.core.cache import cache
from django.test import SimpleTestCase, TestCase, override_settings

from judge.models import Language, Problem, ProblemData, ProblemGroup, ProblemTestCase, ProblemType
from judge.tasks.test_gen import generate_problem_tests
from judge.tests.test_mcp_core import make_token, make_user
from judge.tests.test_mcp_quiz import call
from judge.utils.test_gen import (generate_all, generate_preview, HELP_TEXT, Limits, SpecError,  # noqa: I101
                                  validate_spec)
from judge.utils.test_gen.job import JobError, outputs_match, run_job

ARRAY_SPEC = {
    'seed': 1,
    'lines': [{'type': 'int', 'name': 'n', 'min': 1, 'max': 'N'},
              {'type': 'array', 'len': 'n', 'min': -1000, 'max': 1000}],
    'groups': [{'name': 'nhỏ', 'count': 3, 'params': {'N': [1, 5]}, 'small': True},
               {'name': 'lớn', 'count': 2, 'params': {'N': 1000}}],
}


def gen(spec, **limits):
    return generate_all(validate_spec(spec, Limits(**limits) if limits else None))


class SpecTest(SimpleTestCase):
    def test_deterministic_and_shape(self):
        first, second = gen(ARRAY_SPEC), gen(ARRAY_SPEC)
        self.assertEqual(first, second)
        self.assertEqual(len(first), 5)
        for test in first:
            lines = test['input'].split('\n')
            self.assertEqual(len(lines[1].split()), int(lines[0]))
        self.assertLessEqual(int(first[-1]['input'].split('\n')[0]), 1000)
        other = dict(ARRAY_SPEC, seed=2)
        self.assertNotEqual(gen(other)[-1]['input'], first[-1]['input'])

    def test_points(self):
        self.assertEqual([t['points'] for t in gen(ARRAY_SPEC)], [20] * 5)
        spec = json.loads(json.dumps(ARRAY_SPEC))
        spec['groups'][0]['points'] = 30
        spec['groups'][1]['points'] = 70
        self.assertEqual([t['points'] for t in gen(spec)], [10, 10, 10, 35, 35])
        spec['groups'][1].pop('points')
        with self.assertRaises(SpecError):
            validate_spec(spec)

    def test_array_options(self):
        spec = {'lines': [{'type': 'array', 'len': 50, 'min': 1, 'max': 50, 'distinct': True, 'sorted': 'desc'}],
                'groups': [{'count': 1, 'params': {}}]}
        values = list(map(int, gen(spec)[0]['input'].split()))
        self.assertEqual(values, list(range(50, 0, -1)))
        spec['lines'][0].update(distinct=False, sorted='none', bias='extreme', min=0, max=9)
        self.assertEqual(set(map(int, gen(spec)[0]['input'].split())), {0, 9})
        spec['lines'][0].update(distinct=True, bias='random', min=1, max=10)
        with self.assertRaises(SpecError):
            gen(spec)

    def test_permutation_string_matrix_queries(self):
        spec = {'lines': [{'type': 'permutation', 'len': 20, 'layout': 'column'},
                          {'type': 'string', 'len': 30, 'alphabet': 'ab'},
                          {'type': 'matrix', 'rows': 3, 'cols': 4, 'min': 5, 'max': 5},
                          {'type': 'queries', 'count': 10, 'fields': [{'min': 1, 'max': 100}, {'min': 1, 'max': 100},
                                                                       {'choice': [7]}], 'sorted_pair': True}],
                'groups': [{'count': 1, 'params': {}}]}
        lines = gen(spec)[0]['input'].split('\n')
        self.assertEqual(sorted(map(int, lines[:20])), list(range(1, 21)))
        self.assertEqual(set(lines[20]), {'a', 'b'})
        self.assertEqual(lines[21:24], ['5 5 5 5'] * 3)
        for q in lines[24:34]:
            a, b, c = map(int, q.split())
            self.assertLessEqual(a, b)
            self.assertEqual(c, 7)

    def test_trees_and_graphs(self):
        for shape in ('random', 'path', 'star', 'binary'):
            spec = {'lines': [{'type': 'int', 'name': 'n', 'min': 2, 'max': 'N'},
                              {'type': 'tree', 'n': 'n', 'shape': shape, 'weight': [1, 9]}],
                    'groups': [{'count': 5, 'params': {'N': [2, 40]}}]}
            for test in gen(spec):
                lines = test['input'].strip().split('\n')
                n = int(lines[0])
                self.assertEqual(len(lines), n)
                self._assert_connected(n, [tuple(map(int, line.split()))[:2] for line in lines[1:]])
        spec = {'lines': [{'type': 'ints', 'items': [{'name': 'n', 'min': 2, 'max': 'N'},
                                                     {'name': 'm', 'min': 'n-1', 'max': 'min(n*(n-1)//2, 3*n)'}]},
                          {'type': 'graph', 'n': 'n', 'm': 'm', 'connected': True, 'weight': [1, 5]}],
                'groups': [{'count': 25, 'params': {'N': [2, 7]}}, {'count': 3, 'params': {'N': [2000, 3000]}}]}
        for test in gen(spec):
            lines = test['input'].strip().split('\n')
            n, m = map(int, lines[0].split())
            edges = [tuple(map(int, line.split())) for line in lines[1:]]
            self.assertEqual(len(edges), m)
            keys = {tuple(sorted(e[:2])) for e in edges}
            self.assertEqual(len(keys), m)
            self.assertTrue(all(u != v for u, v, _w in edges))
            self._assert_connected(n, [e[:2] for e in edges])

    def _assert_connected(self, n, edges):
        parent = list(range(n + 1))

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x
        for u, v in edges:
            parent[find(u)] = find(v)
        self.assertEqual(len({find(i) for i in range(1, n + 1)}), 1)

    def test_complete_directed_graph(self):
        spec = {'lines': [{'type': 'ints', 'items': [{'name': 'n', 'min': 4, 'max': 4}, {'name': 'm', 'min': 12, 'max': 12}]},
                          {'type': 'graph', 'n': 'n', 'm': 'm', 'directed': True}],
                'groups': [{'count': 1, 'params': {}}]}
        edges = [tuple(map(int, line.split())) for line in gen(spec)[0]['input'].strip().split('\n')[1:]]
        self.assertEqual(len(set(edges)), 12)
        spec['lines'][0]['items'][1].update(min=13, max=13)
        with self.assertRaises(SpecError):
            gen(spec)

    def test_multitest_scope(self):
        spec = {'lines': [{'type': 'int', 'name': 't', 'min': 3, 'max': 3},
                          {'type': 'repeat', 'count': 't', 'body': [{'type': 'int', 'name': 'n', 'min': 1, 'max': 4},
                                                                    {'type': 'array', 'len': 'n', 'min': 1, 'max': 9}]}],
                'groups': [{'count': 4, 'params': {}}]}
        for test in gen(spec):
            lines = test['input'].strip().split('\n')
            self.assertEqual(lines[0], '3')
            for i in range(3):
                self.assertEqual(len(lines[2 + 2 * i].split()), int(lines[1 + 2 * i]))
        spec['lines'][1]['body'].append({'type': 'repeat', 'count': 1, 'body': [{'type': 'repeat', 'count': 1, 'body': [
            {'type': 'int', 'min': 1, 'max': 1}]}]})
        with self.assertRaises(SpecError):
            validate_spec(spec)

    def test_expressions_are_safe(self):
        for bad in ("__import__('os').system('id')", 'n.real', '[1]', '2**99', 'abs(n)', '1 if n else 2', 'lambda: 1',
                    '(n)(1)', 'n' * 100, '1.5', 'True'):
            spec = {'lines': [{'type': 'int', 'min': 1, 'max': bad}], 'groups': [{'count': 1, 'params': {'n': 5}}]}
            with self.assertRaises(SpecError, msg=bad):
                gen(spec)
        spec = {'lines': [{'type': 'int', 'min': '-n', 'max': 'min(n*2, 10**3) + n % 3 - n // 2'}],
                'groups': [{'count': 2, 'params': {'n': [4, 8]}}]}
        self.assertEqual(len(gen(spec)), 2)

    def test_bad_specs_rejected(self):
        group = [{'count': 1, 'params': {}}]
        bad = [
            None, {}, {'lines': [], 'groups': group}, {'lines': [{'type': 'int', 'min': 1, 'max': 2}]},
            {'lines': [{'type': 'nope'}], 'groups': group},
            {'lines': [{'type': 'int', 'min': 1, 'max': 2, 'extra': 1}], 'groups': group},
            {'lines': [{'type': 'int', 'min': 1}], 'groups': group},
            {'lines': [{'type': 'int', 'min': 1, 'max': 'zz'}], 'groups': group},
            {'lines': [{'type': 'int', 'min': 5, 'max': 1}], 'groups': group},
            {'lines': [{'type': 'int', 'min': 1, 'max': 2}], 'groups': [{'count': 31, 'params': {}}]},
            {'lines': [{'type': 'int', 'min': 1, 'max': 2}], 'groups': [{'count': 1, 'params': {'n': 1.5}}]},
            {'lines': [{'type': 'int', 'name': 'min', 'min': 1, 'max': 2}], 'groups': group},
            {'lines': [{'type': 'array', 'len': 5, 'min': 1, 'max': 2, 'sorted': 'weird'}], 'groups': group},
            {'lines': [{'type': 'string', 'len': 5, 'alphabet': 'a b'}], 'groups': group},
            {'lines': [{'type': 'graph', 'n': 5, 'm': 2, 'connected': True}], 'groups': group},
            {'seed': 'x', 'lines': [{'type': 'int', 'min': 1, 'max': 2}], 'groups': group},
        ]
        for spec in bad:
            with self.assertRaises(SpecError, msg=str(spec)):
                gen(spec)

    def test_size_limits(self):
        spec = {'lines': [{'type': 'array', 'len': 1000, 'min': 1, 'max': 10}], 'groups': [{'count': 1, 'params': {}}]}
        with self.assertRaises(SpecError) as ctx:
            gen(spec, max_elements=500)
        self.assertEqual(ctx.exception.code, 'too_big')
        with self.assertRaises(SpecError) as ctx:
            gen(spec, max_test_bytes=100)
        self.assertEqual(ctx.exception.code, 'too_big')
        spec['groups'][0]['count'] = 5
        with self.assertRaises(SpecError) as ctx:
            gen(spec, max_total_bytes=3000)
        self.assertEqual(ctx.exception.code, 'too_big')

    def test_preview_and_help(self):
        preview = generate_preview(validate_spec(ARRAY_SPEC))
        self.assertEqual([p['group'] for p in preview], ['nhỏ', 'lớn'])
        self.assertTrue(preview[1]['sample'].endswith('...'))
        self.assertIn('spec', HELP_TEXT)

    def test_help_examples_are_valid(self):
        examples = [json.loads(chunk) for chunk in _json_chunks(HELP_TEXT)]
        self.assertGreaterEqual(len(examples), 4)
        for example in examples:
            example.setdefault('seed', 1)
            self.assertTrue(gen(example), example)


def _json_chunks(text):
    """The JSON objects that start a line with '{"seed"' or '{"lines"' in the help text (the examples)."""
    chunks, current = [], None
    for line in text.split('\n'):
        if current is None and (line.startswith('{"seed"') or line.startswith('{"lines"')):
            current = line
        elif current is not None:
            current += ' ' + line.strip()
        if current is not None and current.count('{') == current.count('}'):
            chunks.append(current)
            current = None
    return chunks


SUM = 'SUM'
BAD = 'BAD'


def fake_runner(language, source, inputs, time_limit, memory_kb):
    """Stands in for the sandbox: the 'source' names a behaviour instead of being compiled."""
    if source == 'CE':
        return {'compile_error': 'error: boom', 'results': []}
    results = []
    failed = False
    for text in inputs:
        res = {'status': 'OK', 'stdout': '', 'stderr': '', 'time': 0.01, 'memory': 100, 'truncated': False}
        if failed:
            res['status'] = 'SKIP'
        else:
            numbers = list(map(int, text.split()[1:]))
            if source == 'TLE':
                res['status'] = 'TLE'
                failed = True
            elif source == 'EMPTY':
                res['stdout'] = ''
            elif source == SUM:
                res['stdout'] = '%d\n' % sum(numbers)
            elif source == BAD:       # wrong when the array has more than one element
                res['stdout'] = '%d\n' % (sum(numbers) + (1 if len(numbers) > 1 else 0))
            elif source == 'BRUTE':
                res['stdout'] = '%d' % sum(numbers)    # no trailing newline, like many programs
        results.append(res)
    return {'compile_error': None, 'results': results}


def run(spec=ARRAY_SPEC, solution=SUM, brute=None, checker='standard', **kwargs):
    return run_job(spec, {'language': 'PY3', 'source': solution}, {'language': 'PY3', 'source': brute} if brute else None,
                   checker, 6, 1.0, 262144, runner=fake_runner, **kwargs)


class JobTest(SimpleTestCase):
    def test_success(self):
        cases = run()
        self.assertEqual(len(cases), 5)
        for text_in, text_out, points in cases:
            self.assertEqual(int(text_out), sum(map(int, text_in.split()[1:])))
            self.assertEqual(points, 20)

    def test_brute_agrees_and_adds_newline(self):
        cases = run(brute='BRUTE')
        self.assertTrue(all(c[1].endswith('\n') for c in cases))

    def test_brute_mismatch_blocks_everything(self):
        with self.assertRaises(JobError) as ctx:
            run(solution=BAD, brute='BRUTE')
        self.assertEqual(ctx.exception.code, 'crosscheck_mismatch')
        self.assertIn('nhỏ #', ctx.exception.message)

    def test_failures(self):
        for source, code in (('CE', 'compile_error'), ('TLE', 'solution_failed'), ('EMPTY', 'solution_failed')):
            with self.assertRaises(JobError, msg=source) as ctx:
                run(solution=source)
            self.assertEqual(ctx.exception.code, code, source)
        with self.assertRaises(JobError) as ctx:
            run(brute='TLE')
        self.assertEqual(ctx.exception.code, 'brute_failed')

    def test_brute_needs_small_group(self):
        spec = json.loads(json.dumps(ARRAY_SPEC))
        for g in spec['groups']:
            g['small'] = False
        with self.assertRaises(JobError) as ctx:
            run(spec=spec, brute='BRUTE')
        self.assertEqual(ctx.exception.code, 'unsupported')

    def test_limits_and_bad_spec(self):
        with self.assertRaises(JobError) as ctx:
            run_job(ARRAY_SPEC, {'language': 'PY3', 'source': SUM}, None, 'standard', 6, 9.0, 262144, runner=fake_runner)
        self.assertEqual(ctx.exception.code, 'unsupported')
        with self.assertRaises(JobError) as ctx:
            run(spec={'lines': [], 'groups': []})
        self.assertEqual(ctx.exception.code, 'unsupported')

    def test_outputs_match(self):
        self.assertTrue(outputs_match('1 2\n3\n', '1\n2   3', 'standard'))
        self.assertFalse(outputs_match('1 2', '1 3', 'standard'))
        self.assertFalse(outputs_match('1 2', '1', 'standard'))
        self.assertTrue(outputs_match('1.0000001', '1.0000002', 'floats', 6))
        self.assertFalse(outputs_match('1.01', '1.02', 'floats', 6))
        self.assertFalse(outputs_match('abc', '1', 'floats', 6))
        self.assertTrue(outputs_match('1\n', '1\n\n', 'identical'))
        self.assertFalse(outputs_match('1 ', '1', 'identical'))


@override_settings(MCP_ENABLED=True, MCP_RATE_LIMIT_PER_MINUTE=1000, MCP_GEN_ENABLED=True)
class GenToolsTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        ProblemGroup.objects.get_or_create(name='Uncategorized', defaults={'full_name': 'Uncategorized'})
        ProblemType.objects.get_or_create(name='uncategorized', defaults={'full_name': 'Uncategorized'})
        Language.objects.update(include_in_problem=False)
        py, _created = Language.objects.get_or_create(key='PY3', defaults={
            'name': 'Python 3', 'short_name': 'PY3', 'common_name': 'Python', 'ace': 'python', 'pygments': 'python',
            'extension': 'py'})
        Language.objects.filter(id=py.id).update(include_in_problem=True, file_only=False)
        cls.author = make_user('gen_author', ['add_problem', 'edit_own_problem'])
        cls.tok = make_token(cls.author, 'gen-author-token-0123456789')
        cls.other = make_user('gen_other', ['add_problem', 'edit_own_problem'])
        cls.other_tok = make_token(cls.other, 'gen-other-token-0123456789a')
        cls.student = make_user('gen_student', [])
        cls.student_tok = make_token(cls.student, 'gen-student-token-01234567')

    def setUp(self):
        cache.clear()
        error, data = call(self.client, self.tok, 'problem_create', {
            'code': 'tong', 'name': 'Tổng', 'statement': 'In tổng các số.'})
        self.assertFalse(error, data)
        patcher = mock.patch('judge.mcp.tools.problem_gen.generate_problem_tests.delay',
                             side_effect=lambda *a, **k: generate_problem_tests(*a, **k))
        runner_patch = mock.patch('judge.tasks.test_gen.run_job',
                                  side_effect=lambda *a, **k: run_job(*a, runner=fake_runner, **k))
        patcher.start()
        runner_patch.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(runner_patch.stop)

    def start(self, token=None, **extra):
        args = {'code': 'tong', 'spec': ARRAY_SPEC, 'solution': {'language': 'PY3', 'source': SUM}}
        args.update(extra)
        return call(self.client, token or self.tok, 'problem_generate_tests', args)

    def status(self, job_id, token=None):
        return call(self.client, token or self.tok, 'problem_generate_status', {'job_id': job_id})

    def test_help_preview(self):
        error, data = call(self.client, self.tok, 'problem_generate_help', {})
        self.assertFalse(error)
        self.assertIn('max_tests', data['limits'])
        error, data = call(self.client, self.tok, 'problem_generate_preview', {'code': 'tong', 'spec': ARRAY_SPEC})
        self.assertFalse(error, data)
        self.assertEqual(data['tests'], 5)
        error, text = call(self.client, self.tok, 'problem_generate_preview', {'code': 'tong', 'spec': {'lines': []}})
        self.assertTrue(error)
        self.assertIn('Spec chưa hợp lệ', text)

    def test_tools_hidden_when_disabled(self):
        from judge.tests.test_mcp_core import rpc
        names = [t['name'] for t in rpc(self.client, self.tok, 'tools/list').json()['result']['tools']]
        self.assertIn('problem_generate_tests', names)
        with override_settings(MCP_GEN_ENABLED=False):
            names = [t['name'] for t in rpc(self.client, self.tok, 'tools/list').json()['result']['tools']]
            self.assertNotIn('problem_generate_tests', names)
            self.assertNotIn('problem_generate_help', names)
            error, _text = call(self.client, self.tok, 'problem_generate_help', {})
            self.assertTrue(error)
            _error, data = call(self.client, self.tok, 'problem_create', {
                'code': 'khac', 'name': 'Khác', 'statement': 'x'})
            self.assertNotIn('problem_generate', data['next'])

    def test_generate_success(self):
        error, data = self.start()
        self.assertFalse(error, data)
        error, status = self.status(data['job_id'])
        self.assertFalse(error, status)
        self.assertEqual(status['state'], 'done', status)
        self.assertEqual((status['test_count'], status['total_points']), (5, 100))
        problem = Problem.objects.get(code='tong')
        self.assertEqual(problem.cases.count(), 5)
        self.assertTrue(ProblemData.objects.get(problem=problem).zipfile)
        self.assertEqual(ProblemTestCase.objects.filter(dataset=problem).first().input_file, '1.in')
        self.assertIsNone(cache.get('mcp:gen:lock'), 'lock released')

    def test_failure_keeps_old_tests(self):
        error, first = self.start()
        self.assertFalse(error, first)
        before = list(Problem.objects.get(code='tong').cases.values_list('id', flat=True))
        error, data = self.start(solution={'language': 'PY3', 'source': BAD}, brute={'language': 'PY3', 'source': 'BRUTE'})
        self.assertFalse(error, data)
        _error, status = self.status(data['job_id'])
        self.assertEqual((status['state'], status['code']), ('failed', 'crosscheck_mismatch'))
        self.assertTrue(status['can_generate'])
        self.assertEqual(list(Problem.objects.get(code='tong').cases.values_list('id', flat=True)), before)
        self.assertIsNone(cache.get('mcp:gen:lock'))

    def test_unsupported_reports_cannot_generate(self):
        Problem.objects.filter(code='tong').update(time_limit=10)
        error, text = self.start()
        self.assertTrue(error)
        self.assertIn('test_data_url', text)

    def test_validation_errors(self):
        for extra in ({'spec': {'lines': []}}, {'solution': {'language': 'COBOL', 'source': 'x'}},
                      {'solution': {'language': 'PY3', 'source': ''}}, {'solution': 'print(1)'},
                      {'brute': {'language': 'PY3'}}, {'checker': 'weird'}, {'code': 'khong-co'}):
            error, _text = self.start(**extra)
            self.assertTrue(error, extra)
        self.assertEqual(Problem.objects.get(code='tong').cases.count(), 0)

    def test_permissions(self):
        error, _text = self.start(token=self.other_tok)
        self.assertTrue(error, 'not the author')
        from judge.tests.test_mcp_core import rpc
        self.assertEqual(rpc(self.client, self.student_tok, 'tools/list').status_code, 403)
        error, data = self.start()
        self.assertFalse(error)
        error, _text = self.status(data['job_id'], token=self.other_tok)
        self.assertTrue(error, "another user's job")

    def test_manual_problem_refused(self):
        Problem.objects.filter(code='tong').update(is_manually_managed=True)
        error, text = self.start()
        self.assertTrue(error)
        self.assertIn('tự quản lý', text)

    def test_rate_limit_and_lock(self):
        with override_settings(MCP_GEN_JOBS_PER_HOUR=2):
            self.assertFalse(self.start()[0])
            self.assertFalse(self.start()[0])
            error, text = self.start()
            self.assertTrue(error)
            self.assertIn('quá', text)
        cache.clear()
        cache.set('mcp:gen:lock', 'someone-else', 300)
        error, text = self.start()
        self.assertTrue(error)
        self.assertIn('người khác', text)

    def test_blocked_during_exam_only_when_configured(self):
        from datetime import timedelta

        from django.utils import timezone
        from judge.models import Contest
        now = timezone.now()
        Contest.objects.create(key='livecontest', name='Live', start_time=now - timedelta(hours=1),
                               end_time=now + timedelta(hours=1), time_limit=None)
        self.assertFalse(self.start()[0], 'a running contest alone does not block by default')
        cache.clear()
        with override_settings(MCP_GEN_BLOCK_DURING_EXAMS=True):
            error, text = self.start()
            self.assertTrue(error)
            self.assertIn('kỳ thi', text)

    def test_blocked_when_judges_are_busy(self):
        with mock.patch('judge.mcp.tools.problem_gen.Submission.objects') as objects:
            objects.filter.return_value.count.return_value = 9
            error, text = self.start()
        self.assertTrue(error)
        self.assertIn('bận', text)
        self.assertIsNone(cache.get('mcp:gen:lock'))

    def test_queue_failure_releases_lock(self):
        with mock.patch('judge.mcp.tools.problem_gen.generate_problem_tests.delay', side_effect=OSError('broker down')):
            error, _text = self.start()
        self.assertTrue(error)
        self.assertIsNone(cache.get('mcp:gen:lock'))

    def test_unknown_job(self):
        error, _text = self.status('nope')
        self.assertTrue(error)
