# flake8: noqa: E501  (long Vietnamese tool descriptions)
import io
import json
import logging
import zipfile

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone
from reversion import revisions

from judge.forms import ProblemEditForm
from judge.mcp import audit, places
from judge.mcp.registry import ToolError, tool
from judge.models import (Language, Organization, Problem, ProblemData, ProblemGroup, ProblemTestCase, ProblemType,
                          Submission, SubmissionSource)
from judge.tasks.webhook import on_new_problem
from judge.utils.test_gen import store

logger = logging.getLogger('judge.mcp')

MAX_STATEMENT = 100000
MAX_TEST_BYTES = 800 * 1024  # the whole MCP request body is capped at 1 MB
MAX_SOURCE = 65536
CHECKERS = ('standard', 'identical', 'linecount', 'floats', 'floatsabs', 'floatsrel')
FLOAT_CHECKERS = ('floats', 'floatsabs', 'floatsrel')


def _find_org(value):
    value = str(value).strip()
    org = Organization.objects.filter(id=value).first() if value.isdigit() else None
    return org or Organization.objects.filter(slug=value).first()


def _info(ctx, problem):
    absolute = ctx.request.build_absolute_uri
    return {
        'code': problem.code, 'name': problem.name, 'is_public': problem.is_public,
        'organization': problem.organization.slug if problem.organization_id else None,
        'time_limit_seconds': problem.time_limit, 'memory_limit_mb': problem.memory_limit // 1024,
        'points': problem.points,
        'url': absolute(reverse('problem_detail', args=(problem.code,))),
        'edit_url': absolute(reverse('problem_edit', args=(problem.code,))),
        'test_data_url': absolute(reverse('problem_data', args=(problem.code,))),
    }


def _editable(ctx, code):
    problem = Problem.objects.filter(code=str(code)).first()
    if problem is None or not problem.is_editable_by(ctx.user):
        raise ToolError('Không có bài tập này hoặc bạn không có quyền sửa nó.')
    return problem


def _form_errors(form):
    return ['%s: %s' % (field, ' '.join(errs)) for field, errs in form.errors.items()]


def _statement(value):
    value = str(value or '').strip()
    if not value:
        raise ToolError('Đề bài (statement) đang trống.')
    if len(value) > MAX_STATEMENT:
        raise ToolError('Đề bài quá dài (tối đa %d ký tự).' % MAX_STATEMENT)
    return value


def _memory_kb(memory_mb):
    if not isinstance(memory_mb, (int, float)) or memory_mb <= 0:
        raise ToolError('memory_limit_mb phải là số MB dương, ví dụ 256.')
    return int(memory_mb * 1024)


@tool(
    'problem_create',
    'Tạo bài tập lập trình mới ở chế độ RIÊNG TƯ (chưa ai làm được). Chưa có test; sau đó gọi problem_set_tests để thêm test. '
    'Có organization thì tạo bài riêng của tổ chức (bạn phải là quản trị tổ chức; mã bài bắt buộc bắt đầu bằng "<slug tổ chức không dấu gạch>_"); '
    'không có thì cần quyền tạo bài toàn trang. NƠI ĐĂNG: xem where_can_post trong whoami; có nhiều nơi thì hỏi giáo viên; '
    'chỉ đăng được ở đúng một tổ chức thì bỏ trống organization, hệ thống tự đăng vào đó (nhớ mã bài phải bắt đầu bằng "<slug>_"). '
    'Đề bài viết bằng Markdown, có thể dùng $...$ cho công thức.',
    {
        'code': {'type': 'string', 'description': 'Mã bài: chữ thường a-z, số và dấu gạch dưới, tối đa 32 ký tự, ví dụ "tong2so".'},
        'name': {'type': 'string', 'description': 'Tên bài hiển thị, ví dụ "Tổng hai số".'},
        'statement': {'type': 'string', 'description': 'Đề bài Markdown: nội dung, định dạng Input/Output, ví dụ mẫu, ràng buộc.'},
        'time_limit_seconds': {'type': 'number', 'description': 'Giới hạn thời gian (giây), mặc định 1.'},
        'memory_limit_mb': {'type': 'number', 'description': 'Giới hạn bộ nhớ (MB), mặc định 256.'},
        'points': {'type': 'number', 'description': 'Điểm của bài (độ khó), mặc định 1.'},
        'partial': {'type': 'boolean', 'description': 'Cho điểm từng phần theo số test đúng (mặc định true).'},
        'organization': {'type': 'string', 'description': 'Slug hoặc id tổ chức (tùy chọn).'},
        'group': {'type': 'string', 'description': 'Tên nhóm bài (tùy chọn, mặc định Uncategorized).'},
        'types': {'type': 'array', 'items': {'type': 'string'}, 'description': 'Tên các dạng bài (tùy chọn, chỉ cho bài toàn trang).'},
    },
    required=['code', 'name', 'statement'],
)
def problem_create(ctx, code, name, statement, time_limit_seconds=1.0, memory_limit_mb=256, points=1.0, partial=True,
                   organization=None, group=None, types=None):
    user, profile = ctx.user, ctx.profile
    org = None
    if not user.has_perm('judge.edit_own_problem'):
        raise ToolError('Tài khoản của bạn chưa có quyền sửa bài tập của chính mình (edit_own_problem), '
                        'nên tạo xong cũng không thêm test được. Hãy nhờ quản trị viên cấp quyền.')
    auto = None
    if not organization:
        auto = places.default_destination(ctx, 'problem')
        if auto is not None:
            organization = auto[1].slug
    if organization:
        org = _find_org(organization)
        if org is None or not org.is_admin(profile):
            raise ToolError('Không có tổ chức này hoặc bạn không phải quản trị của tổ chức đó.')
        if not user.has_perm('judge.create_organization_problem'):
            raise ToolError('Tài khoản của bạn chưa có quyền tạo bài trong tổ chức. Hãy nhờ quản trị viên cấp quyền.')
        if settings.VNOJ_QUOTA_ENFORCEMENT_ENABLED and not org.can_create_problem():
            raise ToolError('Tổ chức đã hết hạn mức số bài tập.')
    elif not user.has_perm('judge.add_problem'):
        raise ToolError('Tài khoản của bạn chưa có quyền tạo bài tập toàn trang. '
                        'Hãy tạo trong tổ chức bạn quản trị (tham số organization) hoặc nhờ quản trị viên cấp quyền.')

    code = str(code).strip()
    if org is not None and not code.startswith(''.join(x for x in org.slug.lower() if x.isalnum()) + '_'):
        raise ToolError('Mã bài trong tổ chức phải bắt đầu bằng "%s_".' % ''.join(x for x in org.slug.lower() if x.isalnum()))

    group_obj = (ProblemGroup.objects.filter(name__iexact=str(group)).first() if group else None) or \
        ProblemGroup.objects.filter(name='Uncategorized').first() or ProblemGroup.objects.order_by('id').first()
    if group and ProblemGroup.objects.filter(name__iexact=str(group)).first() is None:
        raise ToolError('Không có nhóm bài "%s".' % group)
    type_objs = []
    for type_name in (types or []):
        found = ProblemType.objects.filter(Q(name__iexact=str(type_name)) | Q(full_name__iexact=str(type_name))).first()
        if found is None:
            raise ToolError('Không có dạng bài "%s".' % type_name)
        type_objs.append(found)
    if not type_objs:
        default_type = ProblemType.objects.filter(name='uncategorized').first() or ProblemType.objects.order_by('id').first()
        type_objs = [default_type] if default_type else []

    data = {
        'code': code, 'name': ' '.join(str(name).split()), 'time_limit': time_limit_seconds,
        'memory_limit': _memory_kb(memory_limit_mb), 'points': points, 'description': _statement(statement),
        'group': group_obj.id if group_obj else '',
        'submission_source_visibility_mode': Problem._meta.get_field('submission_source_visibility_mode').get_default(),
        'testcase_visibility_mode': Problem._meta.get_field('testcase_visibility_mode').get_default(),
    }
    if partial:
        data['partial'] = 'on'
    if org is None:
        data['types'] = [t.id for t in type_objs]
    form = ProblemEditForm(data, user=user, org_pk=org.pk if org else None)
    if not form.is_valid():
        raise ToolError('Bài tập không hợp lệ, chưa tạo:\n' + '\n'.join(_form_errors(form)))

    with revisions.create_revision(atomic=True):
        problem = form.save()
        if org is None:
            problem.curators.add(profile)
        else:
            problem.authors.add(profile)
            problem.is_organization_private = True
            problem.organization = org
        problem.allowed_languages.set(Language.objects.filter(include_in_problem=True))
        problem.date = timezone.now()
        problem.save()
        revisions.set_comment('Created via MCP')
        revisions.set_user(user)
    if org is not None:
        try:
            on_new_problem.delay(problem.code)
        except Exception:
            logger.exception('on_new_problem failed for %s', problem.code)
    result = _info(ctx, problem)
    if auto is not None:
        result['placed'] = places.where_note(*auto)
    result['next'] = (
        'Bài đã được tạo (riêng tư), CHƯA có test. Nếu người dùng chỉ yêu cầu tạo bài thì dừng ở đây và nói họ vào '
        'test_data_url để tải file test (zip) lên. Chỉ khi người dùng muốn bạn làm test: test nhỏ gõ tay dùng '
        'problem_set_tests%s; sau đó problem_submit_check để thử lời giải mẫu.' % (
            '; test ngẫu nhiên theo cấu hình (nhiều test, test lớn) dùng problem_generate_help'
            if getattr(settings, 'MCP_GEN_ENABLED', False) else ''))
    return result


@tool(
    'problem_update',
    'Sửa tên, đề bài, giới hạn hoặc điểm của bài tập bạn có quyền sửa. Chỉ gửi những trường muốn đổi. Lịch sử chỉnh sửa vẫn được lưu.',
    {
        'code': {'type': 'string'},
        'name': {'type': 'string'},
        'statement': {'type': 'string', 'description': 'Toàn bộ đề bài Markdown mới (thay thế đề cũ).'},
        'time_limit_seconds': {'type': 'number'},
        'memory_limit_mb': {'type': 'number'},
        'points': {'type': 'number'},
        'partial': {'type': 'boolean'},
    },
    required=['code'], idempotent=True,
)
def problem_update(ctx, code, name=None, statement=None, time_limit_seconds=None, memory_limit_mb=None, points=None,
                   partial=None):
    problem = _editable(ctx, code)
    if all(v is None for v in (name, statement, time_limit_seconds, memory_limit_mb, points, partial)):
        raise ToolError('Chưa có trường nào để đổi.')
    org_pk = problem.organization_id if problem.is_organization_private else None
    data = {
        'code': problem.code, 'name': problem.name, 'time_limit': problem.time_limit, 'memory_limit': problem.memory_limit,
        'points': problem.points, 'description': problem.description, 'group': problem.group_id,
        'submission_source_visibility_mode': problem.submission_source_visibility_mode,
        'testcase_visibility_mode': problem.testcase_visibility_mode, 'source': problem.source,
        'testers': [p.id for p in problem.testers.all()],
    }
    if org_pk is None:
        data['types'] = [t.id for t in problem.types.all()]
    else:
        data['tags'] = [t.id for t in problem.tags.all()]
        if problem.is_public:
            data['is_public'] = 'on'
    if (problem.partial if partial is None else partial):
        data['partial'] = 'on'
    if name is not None:
        data['name'] = ' '.join(str(name).split())
    if statement is not None:
        data['description'] = _statement(statement)
    if time_limit_seconds is not None:
        data['time_limit'] = time_limit_seconds
    if memory_limit_mb is not None:
        data['memory_limit'] = _memory_kb(memory_limit_mb)
    if points is not None:
        data['points'] = points
    form = ProblemEditForm(data, instance=problem, user=ctx.user, org_pk=org_pk)
    if not form.is_valid():
        raise ToolError('Không hợp lệ, chưa lưu:\n' + '\n'.join(_form_errors(form)))
    with revisions.create_revision(atomic=True):
        problem = form.save()
        revisions.set_comment('Edited via MCP')
        revisions.set_user(ctx.user)
    return _info(ctx, problem)


def _clean_cases(ctx, cases):
    if not isinstance(cases, list) or not cases:
        raise ToolError('cases phải là danh sách ít nhất 1 test, mỗi test có "input" và "output" (và có thể "points").')
    limit = 9999 if ctx.user.has_perm('judge.create_mass_testcases') else settings.VNOJ_TESTCASE_SOFT_LIMIT
    if len(cases) > limit:
        raise ToolError('Tối đa %d test mỗi lần. Test nhiều hơn/lớn hơn hãy tải zip lên trang test_data.' % limit)
    cleaned, total = [], 0
    for number, case in enumerate(cases, 1):
        if not isinstance(case, dict) or not isinstance(case.get('input'), str) or not isinstance(case.get('output'), str):
            raise ToolError('Test %d: cần "input" và "output" là chuỗi.' % number)
        text_in, text_out = case['input'], case['output']
        if not text_in.endswith('\n'):
            text_in += '\n'
        if text_out and not text_out.endswith('\n'):
            text_out += '\n'
        total += len(text_in.encode()) + len(text_out.encode())
        points = case.get('points')
        if points is not None and (isinstance(points, bool) or not isinstance(points, int) or points < 0):
            raise ToolError('Test %d: points phải là số nguyên không âm.' % number)
        cleaned.append((text_in, text_out, points))
    if total > MAX_TEST_BYTES:
        raise ToolError('Tổng dung lượng test vượt %d KB. Hãy tải zip lên trang test_data.' % (MAX_TEST_BYTES // 1024))
    given = [c[2] is not None for c in cleaned]
    if any(given) and not all(given):
        raise ToolError('Hoặc test nào cũng có points, hoặc không test nào có (khi đó điểm chia đều tổng 100).')
    if not any(given):
        base = 100 // len(cleaned)
        cleaned = [(i, o, base + (100 - base * len(cleaned) if n == len(cleaned) - 1 else 0))
                   for n, (i, o, _) in enumerate(cleaned)]
    if sum(c[2] for c in cleaned) <= 0:
        raise ToolError('Tổng điểm các test phải lớn hơn 0.')
    return cleaned


def check_tests_writable(problem):
    """Raise ToolError unless the tests of this problem may be replaced through MCP (shared by set_tests and the generator)."""
    try:
        store.check_tests_writable(problem)
    except store.StoreError as e:
        raise ToolError(str(e))


def write_tests(problem, cleaned, checker='standard', float_precision=6):
    try:
        return store.write_tests(problem, cleaned, checker, float_precision)
    except store.StoreError as e:
        raise ToolError(str(e))


@tool(
    'problem_set_tests',
    'THAY THẾ toàn bộ test của một bài tập bằng danh sách test dạng chữ (input/output). Tối đa ~50 test và ~800 KB; test lớn hơn hãy '
    'tải file zip lên trang test_data của bài. Nếu không ghi points, điểm được chia đều tổng 100. Sau khi đặt, hệ thống tự sinh '
    'init.yml; nếu lỗi sẽ báo lý do.',
    {
        'code': {'type': 'string', 'description': 'Mã bài tập.'},
        'cases': {
            'type': 'array',
            'description': 'Danh sách test theo thứ tự.',
            'items': {
                'type': 'object',
                'properties': {
                    'input': {'type': 'string', 'description': 'Nội dung file input của test.'},
                    'output': {'type': 'string', 'description': 'Output đúng mong đợi.'},
                    'points': {'type': 'integer', 'minimum': 0, 'description': 'Điểm của test (tùy chọn).'},
                },
                'required': ['input', 'output'],
            },
        },
        'checker': {'type': 'string', 'enum': list(CHECKERS), 'description': 'Cách so output: standard (bỏ qua khoảng trắng thừa, mặc định), identical, linecount, hoặc floats* cho số thực.'},
        'float_precision': {'type': 'integer', 'minimum': 0, 'maximum': 12, 'description': 'Số chữ số thập phân khi dùng checker floats* (mặc định 6).'},
    },
    required=['code', 'cases'], idempotent=True,
)
def problem_set_tests(ctx, code, cases, checker='standard', float_precision=6):
    problem = _editable(ctx, code)
    check_tests_writable(problem)
    if checker not in CHECKERS:
        raise ToolError('checker phải là một trong: %s.' % ', '.join(CHECKERS))
    cleaned = _clean_cases(ctx, cases)
    data = write_tests(problem, cleaned, checker, float_precision)
    return {
        'code': problem.code, 'test_count': len(cleaned), 'total_points': sum(c[2] for c in cleaned),
        'checker': checker, 'zip_bytes': data.zipfile_size,
        'test_data_url': ctx.request.build_absolute_uri(reverse('problem_data', args=(problem.code,))),
        'next': 'Gọi problem_submit_check với lời giải mẫu để xác nhận chấm đúng.',
    }


@tool(
    'problem_languages',
    'Liệt kê mã ngôn ngữ lập trình (key) hợp lệ để dùng với problem_submit_check, ví dụ PY3, CPP17.',
    {'code': {'type': 'string', 'description': 'Mã bài tập (tùy chọn): chỉ liệt kê ngôn ngữ bài đó cho phép.'}},
    read_only=True, idempotent=True,
)
def problem_languages(ctx, code=None):
    languages = Language.objects.filter(include_in_problem=True, file_only=False)
    if code:
        problem = _editable(ctx, code)
        languages = problem.allowed_languages.filter(file_only=False)
    return {'languages': [{'key': lang.key, 'name': lang.name} for lang in languages.order_by('key')]}


@tool(
    'problem_submit_check',
    'Nộp thử một lời giải mẫu vào bài tập của bạn để xác nhận test chấm đúng. Việc chấm chạy nền: lấy submission_id từ kết quả '
    'rồi gọi problem_check_result sau vài giây. Bài nộp này nằm trong danh sách bài nộp của bài. Tối đa 2 bài nộp chưa chấm xong cùng lúc.',
    {
        'code': {'type': 'string', 'description': 'Mã bài tập.'},
        'language': {'type': 'string', 'description': 'Mã ngôn ngữ, lấy từ problem_languages (ví dụ PY3, CPP17).'},
        'source': {'type': 'string', 'description': 'Mã nguồn lời giải mẫu.'},
    },
    required=['code', 'language', 'source'],
)
def problem_submit_check(ctx, code, language, source):
    problem = _editable(ctx, code)
    source = str(source)
    if not source.strip() or len(source) > MAX_SOURCE:
        raise ToolError('Mã nguồn trống hoặc quá dài (tối đa %d ký tự).' % MAX_SOURCE)
    lang = Language.objects.filter(key=str(language), file_only=False).first()
    if lang is None or not problem.allowed_languages.filter(id=lang.id).exists():
        raise ToolError('Ngôn ngữ "%s" không hợp lệ cho bài này (gọi problem_languages để xem).' % language)
    if not hasattr(problem, 'data_files') or not problem.cases.exists():
        raise ToolError('Bài chưa có test. Hãy gọi problem_set_tests trước.')
    if audit.rate_limited('check:%d' % ctx.user.id, 6):
        raise ToolError('Bạn nộp thử quá nhanh, hãy đợi một phút.')
    if not ctx.user.has_perm('judge.spam_submission') and \
            Submission.objects.filter(user=ctx.profile, rejudged_date__isnull=True) \
            .exclude(status__in=['D', 'IE', 'CE', 'AB']).count() >= settings.DMOJ_SUBMISSION_LIMIT:
        raise ToolError('Bạn đang có quá nhiều bài nộp chưa chấm xong, hãy đợi chúng chấm xong rồi nộp tiếp.')
    if settings.VNOJ_ENABLE_ORGANIZATION_CREDIT_LIMITATION and problem.is_organization_private and \
            problem.organization is not None and not problem.organization.has_credit_left():
        raise ToolError('Tổ chức đã hết credit chấm bài.')
    with transaction.atomic():
        submission = Submission(user=ctx.profile, problem=problem, language=lang)
        submission.save()
        submission.source = SubmissionSource.objects.create(submission=submission, source=source)
    submission.judge(force_judge=True)
    return {
        'submission_id': submission.id,
        'url': ctx.request.build_absolute_uri(reverse('submission_status', args=(submission.id,))),
        'next': 'Đang chấm. Gọi problem_check_result với submission_id này sau 5-10 giây.',
    }


FINAL = ('D', 'IE', 'CE', 'AB')


@tool(
    'problem_check_result',
    'Xem kết quả chấm của một bài nộp thử (status, kết quả, điểm, thời gian, từng test). Nếu status chưa phải kết thúc (D/CE/IE/AB) thì gọi lại sau vài giây.',
    {'submission_id': {'type': 'integer'}},
    required=['submission_id'], read_only=True, idempotent=True,
)
def problem_check_result(ctx, submission_id):
    submission = Submission.objects.filter(id=submission_id).select_related('problem', 'language').first()
    if submission is None or not (submission.user_id == ctx.profile.id or submission.problem.is_editable_by(ctx.user)):
        raise ToolError('Không có bài nộp này hoặc bạn không có quyền xem.')
    cases = [{'case': c.case, 'status': c.status, 'points': c.points, 'total': c.total,
              'time_s': round(c.time, 3) if c.time is not None else None}
             for c in submission.test_cases.order_by('case')[:100]]
    return {
        'submission_id': submission.id, 'problem': submission.problem.code, 'language': submission.language.key,
        'status': submission.status, 'finished': submission.status in FINAL, 'result': submission.result,
        'points': submission.points, 'case_points': submission.case_points, 'case_total': submission.case_total,
        'time_s': round(submission.time, 3) if submission.time is not None else None,
        'memory_kb': submission.memory, 'compile_error': (submission.error or '')[:1500] or None, 'cases': cases,
        'legend': 'status: QU=đang xếp hàng, P=đang chuẩn bị, G=đang chấm, D=chấm xong, CE=lỗi biên dịch, IE=lỗi hệ thống; '
                  'result: AC=đúng hết, WA=sai, TLE=quá giờ, MLE=quá bộ nhớ, RTE=lỗi chạy, PAC=đúng một phần',
    }


@tool(
    'problem_list_mine',
    'Liệt kê các bài tập bạn là tác giả/người quản lý (mới nhất trước), kèm số test.',
    {'limit': {'type': 'integer', 'minimum': 1, 'maximum': 50, 'description': 'Mặc định 20.'}},
    read_only=True, idempotent=True,
)
def problem_list_mine(ctx, limit=20):
    limit = max(1, min(int(limit or 20), 50))
    problems = Problem.objects.filter(Q(authors=ctx.profile) | Q(curators=ctx.profile)).distinct().order_by('-id')[:limit]
    rows = []
    for problem in problems:
        row = _info(ctx, problem)
        row['test_count'] = problem.cases.count()
        rows.append(row)
    return {'count': len(rows), 'problems': rows}
