# flake8: noqa: E501  (long Vietnamese tool descriptions)
"""Automatic test generation: the assistant picks block types and parameters (never code), the server generates the
inputs, runs the reference solution in the judge sandbox for the outputs and stores the tests."""
import secrets

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from judge.mcp.registry import ToolError, tool
from judge.mcp.tools.problem import _editable, CHECKERS, check_tests_writable, MAX_SOURCE
from judge.models import Contest, Quiz, Submission
from judge.tasks.test_gen import gen_job_key, gen_lock_key, GEN_LOCK_TTL, GEN_STATE_TTL, generate_problem_tests
from judge.utils.run_service import RUN_LANGUAGES
from judge.utils.test_gen import generate_preview, HELP_TEXT, Limits, SpecError, validate_spec


def _enabled():
    return bool(getattr(settings, 'MCP_GEN_ENABLED', False))


def _spec(spec):
    try:
        return validate_spec(spec)
    except SpecError as e:
        raise ToolError('Spec chưa hợp lệ: %s\nSửa spec rồi gọi lại. Nếu bài không thể mô tả bằng các khối (xem problem_generate_help), '
                        'hãy báo người dùng là không sinh được test tự động và để họ tải test ở test_data_url.' % e.message)


def _program(value, label):
    if not isinstance(value, dict) or set(value) != {'language', 'source'}:
        raise ToolError('%s phải là {"language": "PY3|CPP17|...", "source": "<mã nguồn>"}.' % label)
    language, source = value['language'], value['source']
    if language not in RUN_LANGUAGES:
        raise ToolError('%s: ngôn ngữ "%s" chưa hỗ trợ chạy tự động (dùng: %s).' % (label, language, ', '.join(sorted(RUN_LANGUAGES))))
    if not isinstance(source, str) or not source.strip() or len(source.encode()) > MAX_SOURCE:
        raise ToolError('%s: mã nguồn trống hoặc dài quá %d byte.' % (label, MAX_SOURCE))
    return {'language': language, 'source': source}


@tool(
    'problem_generate_help',
    'Hướng dẫn cách mô tả bộ sinh test ngẫu nhiên theo cấu hình (spec JSON, các khối int/array/tree/graph/...) cùng ví dụ và giới hạn. '
    'Gọi TRƯỚC khi dùng problem_generate_preview / problem_generate_tests. Nếu bài không diễn đạt được bằng các khối, đừng ép: báo không sinh được.',
    {}, read_only=True, idempotent=True, enabled=_enabled,
)
def problem_generate_help(ctx):
    limits = Limits()
    return {
        'help': HELP_TEXT.strip(),
        'limits': {'max_tests': limits.max_tests, 'max_elements_per_test': limits.max_elements,
                   'max_test_mb': limits.max_test_bytes // (1024 * 1024), 'max_total_mb': limits.max_total_bytes // (1024 * 1024),
                   'solution_languages': sorted(RUN_LANGUAGES), 'max_time_limit_seconds': 5, 'max_memory_mb': 512},
        'workflow': ['problem_generate_preview(code, spec) để xem input mẫu',
                     'problem_generate_tests(code, spec, solution, brute?) rồi hỏi problem_generate_status(job_id) vài giây một lần',
                     'problem_submit_check để thử lại bằng lời giải mẫu sau khi có test'],
    }


@tool(
    'problem_generate_preview',
    'Kiểm tra spec và cho xem input mẫu (test đầu của mỗi nhóm, cắt ngắn) cùng kích thước ước tính. Không chạy lời giải, không lưu gì.',
    {
        'code': {'type': 'string', 'description': 'Mã bài tập.'},
        'spec': {'type': 'object', 'description': 'Bản mô tả bộ sinh test, xem problem_generate_help.'},
    },
    required=['code', 'spec'], read_only=True, idempotent=True, enabled=_enabled,
)
def problem_generate_preview(ctx, code, spec):
    _editable(ctx, code)
    compiled = _spec(spec)
    try:
        preview = generate_preview(compiled)
    except SpecError as e:
        raise ToolError('Không sinh được input mẫu: %s' % e.message)
    return {'ok': True, 'tests': sum(g['count'] for g in compiled['groups']), 'groups': preview,
            'next': 'Nếu input đúng ý, gọi problem_generate_tests kèm lời giải mẫu (và nên có lời giải vét cạn "brute" để kiểm tra chéo).'}


def _exam_running():
    now = timezone.now()
    return (Contest.objects.filter(start_time__lte=now, end_time__gte=now).exists() or
            Quiz.objects.filter(mode='exam', start_time__lte=now, end_time__gte=now).exists())


@tool(
    'problem_generate_tests',
    'Sinh test cho bài: server sinh input theo spec, chạy LỜI GIẢI MẪU trong sandbox để lấy output rồi THAY THẾ toàn bộ test của bài. '
    'Chạy nền; lấy job_id rồi gọi problem_generate_status. Nên kèm "brute" (lời giải vét cạn đơn giản) để so kết quả trên các nhóm "small": '
    'nếu hai lời giải khác nhau thì KHÔNG lưu test nào. Chỉ dùng khi người dùng muốn bạn làm test và bài đơn giản, mô tả được bằng spec.',
    {
        'code': {'type': 'string', 'description': 'Mã bài tập.'},
        'spec': {'type': 'object', 'description': 'Bản mô tả bộ sinh test, xem problem_generate_help.'},
        'solution': {'type': 'object', 'description': 'Lời giải mẫu ĐÚNG và đủ nhanh: {"language": "PY3", "source": "..."}.',
                     'properties': {'language': {'type': 'string'}, 'source': {'type': 'string'}}},
        'brute': {'type': 'object', 'description': 'Tùy chọn: lời giải vét cạn độc lập để kiểm tra chéo trên nhóm small. {"language","source"}.',
                  'properties': {'language': {'type': 'string'}, 'source': {'type': 'string'}}},
        'checker': {'type': 'string', 'enum': list(CHECKERS), 'description': 'Cách so output của bài (mặc định standard). Bài có nhiều đáp án đúng cần checker riêng: không dùng công cụ này.'},
        'float_precision': {'type': 'integer', 'minimum': 0, 'maximum': 12, 'description': 'Số chữ số thập phân khi dùng checker floats*.'},
    },
    required=['code', 'spec', 'solution'], enabled=_enabled,
)
def problem_generate_tests(ctx, code, spec, solution, brute=None, checker='standard', float_precision=6):
    problem = _editable(ctx, code)
    check_tests_writable(problem)
    if checker not in CHECKERS:
        raise ToolError('checker phải là một trong: %s.' % ', '.join(CHECKERS))
    compiled = _spec(spec)
    solution = _program(solution, 'solution')
    brute = _program(brute, 'brute') if brute else None
    if problem.time_limit > 5 or problem.memory_limit > 512 * 1024:
        raise ToolError('Bài có giới hạn thời gian > 5 giây hoặc bộ nhớ > 512 MB: không sinh test tự động được. Hãy để người dùng tải test ở test_data_url.')
    if getattr(settings, 'MCP_GEN_BLOCK_DURING_EXAMS', False) and _exam_running():
        raise ToolError('Đang có kỳ thi (contest hoặc quiz thi) diễn ra nên tạm không sinh test tự động để không tranh CPU với máy chấm. Thử lại sau khi kỳ thi kết thúc.')
    waiting = Submission.objects.filter(status__in=('QU', 'P', 'G')).count()
    if waiting > int(getattr(settings, 'MCP_GEN_MAX_QUEUE', 5)):
        raise ToolError('Máy chấm đang bận (%d bài nộp đang chờ chấm) nên tạm không sinh test tự động để không làm chậm thí sinh. Thử lại sau vài phút.' % waiting)

    count_key = 'mcp:gen:count:%d' % ctx.user.id
    cache.add(count_key, 0, 3600)
    if cache.incr(count_key) > int(getattr(settings, 'MCP_GEN_JOBS_PER_HOUR', 5)):
        raise ToolError('Bạn đã sinh test quá %d lần trong một giờ. Thử lại sau.' % int(getattr(settings, 'MCP_GEN_JOBS_PER_HOUR', 5)))
    job_id = secrets.token_urlsafe(9)
    if not cache.add(gen_lock_key(), job_id, GEN_LOCK_TTL):
        raise ToolError('Máy đang sinh test cho người khác, thử lại sau ít phút.')
    cache.set(gen_job_key(job_id), {'user': ctx.user.id, 'problem': problem.code, 'state': 'queued', 'stage': 'queued',
                                    'tests': sum(g['count'] for g in compiled['groups'])}, GEN_STATE_TTL)
    try:
        generate_problem_tests.delay(job_id, ctx.user.id, problem.code, spec, solution, brute, checker, int(float_precision))
    except Exception:
        cache.delete(gen_lock_key())
        cache.delete(gen_job_key(job_id))
        raise ToolError('Không đưa được việc sinh test vào hàng đợi; thử lại sau hoặc báo quản trị viên.')
    return {'job_id': job_id, 'state': 'queued', 'tests': sum(g['count'] for g in compiled['groups']),
            'next': 'Gọi problem_generate_status với job_id này sau vài giây, lặp lại cho tới khi state là done hoặc failed.'}


@tool(
    'problem_generate_status',
    'Xem tiến độ/kết quả của một lần sinh test: queued, running (stage), done (có thống kê) hoặc failed (code + message). Chỉ xem được job của chính bạn.',
    {'job_id': {'type': 'string', 'description': 'job_id do problem_generate_tests trả về.'}},
    required=['job_id'], read_only=True, idempotent=True, enabled=_enabled,
)
def problem_generate_status(ctx, job_id):
    state = cache.get(gen_job_key(str(job_id)))
    if not state or state.get('user') != ctx.user.id:
        raise ToolError('Không có job này (hoặc đã hết hạn sau 1 giờ).')
    out = {'job_id': job_id, 'problem': state['problem'], 'state': state['state'], 'stage': state.get('stage')}
    if state['state'] == 'done':
        out.update(state['result'])
        out['test_data_url'] = ctx.request.build_absolute_uri('/problem/%s/test_data' % state['problem'])
        out['next'] = 'Gọi problem_submit_check với lời giải mẫu để xác nhận chấm đúng, rồi báo người dùng kiểm tra bài trước khi công khai.'
    elif state['state'] == 'failed':
        out.update(code=state.get('code'), message=state.get('message'), can_generate=state.get('can_generate', False))
        out['next'] = ('Không có test nào được ghi (test cũ của bài giữ nguyên). ' + (
            'Có thể sửa lời giải/spec rồi gọi lại problem_generate_tests.' if state.get('can_generate') else
            'Báo người dùng không sinh được test tự động cho bài này và nói họ tải test ở test_data_url.'))
    return out
