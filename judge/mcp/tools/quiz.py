# flake8: noqa: E501  (long Vietnamese tool descriptions)
import re
from datetime import timedelta
from zoneinfo import ZoneInfo

from django.db.models import Count, Q
from django.forms.models import model_to_dict
from django.urls import reverse
from django.utils import timezone

from judge.mcp import places
from judge.mcp.registry import ToolError, tool
from judge.models import Classroom, Organization, Quiz
from judge.utils import quiz_stats
from judge.utils.question_bank import split_tags
from judge.utils.quiz_create import apply_quiz
from judge.utils.quiz_parser import QuizFormatError, parse_quiz_lines
from judge.views.quiz import DATETIME_INPUT, ManageForm, can_upload, can_upload_for_org

VN = ZoneInfo('Asia/Ho_Chi_Minh')
MAX_TEXT = 300000
TIME_RE = re.compile(r'^(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2})(:\d{2})?$')

FORMAT_HELP = """CÚ PHÁP ĐỀ TRẮC NGHIỆM CỦA CBNOJ (văn bản thuần, mỗi câu bắt đầu bằng dòng [qus]):

[qus] Nội dung câu hỏi (có thể xuống dòng)
A. Phương án A
B. Phương án B
C. Phương án C
D. Phương án D
[ans] B
[exp] Giải thích (tùy chọn)

Các dòng đánh dấu (không phân biệt hoa thường):
- [ans] một chữ cái = chọn một đáp án; nhiều chữ cái (ví dụ B, D) = chọn nhiều đáp án.
- Câu KHÔNG có phương án (A., B., ...) là câu trả lời ngắn: [ans] ghi các đáp án chấp nhận, cách nhau bằng dấu |
  (ví dụ [ans] 12|mười hai).
- Câu đúng/sai 4 ý: viết 4 ý bằng chữ thường a) b) c) d) rồi [ans] ghi các ý ĐÚNG (ví dụ [ans] a, c);
  nếu không ý nào đúng ghi [ans] none. Hoặc thêm dòng [type] tf.
- [pts] 0.25 = điểm của câu (mặc định 1).
- [tag] Chủ đề 1, Chủ đề 2 = chủ đề để lọc ngân hàng câu hỏi.
- [lvl] 1|2|3 = độ khó (dễ, vừa, khó).
- [sec] Phần I: Trắc nghiệm = tiêu đề phần, áp dụng cho các câu sau nó.
- [psg] Đoạn ngữ liệu dùng chung cho các câu sau; [psg] rỗng để kết thúc đoạn.

QUY TẮC KHI SOẠN: chỉ dùng đúng nội dung đề do giáo viên cung cấp, không tự bịa câu hỏi hay đáp án; câu nào không
chắc đáp án thì hỏi lại giáo viên. Công thức viết dạng chữ thường (x^2, sqrt(x)) vì hệ thống không có ô công thức.
Luôn gọi quiz_preview trước, cho giáo viên xem lỗi/cảnh báo và số câu rồi mới gọi quiz_create.

VÍ DỤ:
[sec] Phần I
[qus] Thủ đô của Việt Nam là gì?
A. Huế
B. Hà Nội
C. Đà Nẵng
D. Cần Thơ
[ans] B
[pts] 0.5

[qus] 2 + 3 = ?
[ans] 5
"""


def _absolute(ctx, path):
    return ctx.request.build_absolute_uri(path)


def _vn(value):
    return value.astimezone(VN).strftime('%Y-%m-%d %H:%M') if value else None


def _parse(text):
    text = (text or '').strip()
    if not text:
        raise ToolError('Chưa có nội dung đề. Hãy gửi đề theo cú pháp [qus]/[ans] (xem công cụ quiz_format_help).')
    if len(text) > MAX_TEXT:
        raise ToolError('Đề quá dài (tối đa %d ký tự mỗi lần). Hãy chia đề ra nhiều quiz.' % MAX_TEXT)
    try:
        return parse_quiz_lines(text.splitlines())
    except QuizFormatError as e:
        raise ToolError(str(e))


def _issues(items):
    lines = []
    for item in items[:40]:
        where = 'dòng %s' % item['line']
        if item.get('question'):
            where += ', câu %s' % item['question']
        lines.append('%s: %s' % (where, item['message']))
    if len(items) > 40:
        lines.append('... và %d mục nữa' % (len(items) - 40))
    return lines


def _summary(questions):
    kinds = {}
    for q in questions:
        kinds[q['kind']] = kinds.get(q['kind'], 0) + 1
    return {
        'question_count': len(questions),
        'total_points': round(sum(q['points'] for q in questions), 2),
        'by_kind': kinds,
        'kinds_legend': {'single': 'một đáp án', 'multi': 'nhiều đáp án', 'short': 'trả lời ngắn', 'tf4': 'đúng/sai 4 ý'},
    }


@tool(
    'quiz_format_help',
    'Trả về cú pháp văn bản của đề trắc nghiệm CBNoj ([qus], [ans], [pts]...) kèm ví dụ. '
    'Gọi trước khi soạn đề để viết đúng định dạng.',
    read_only=True, idempotent=True,
)
def quiz_format_help(ctx):
    return FORMAT_HELP


@tool(
    'quiz_preview',
    'Kiểm tra một đề trắc nghiệm viết theo cú pháp CBNoj mà KHÔNG lưu gì. Trả về số câu, tổng điểm, từng lỗi/cảnh báo '
    'và đáp án máy hiểu của vài câu đầu để đối chiếu với đề gốc.',
    {'text': {'type': 'string', 'description': 'Toàn bộ đề theo cú pháp [qus]/[ans] (xem quiz_format_help).'}},
    required=['text'], read_only=True, idempotent=True,
)
def quiz_preview(ctx, text):
    questions, errors, warnings = _parse(text)
    sample = []
    for number, q in enumerate(questions[:5], 1):
        item = {'number': number, 'kind': q['kind'], 'points': q['points'], 'text': q['text'][:120]}
        if q['options']:
            item['correct'] = [chr(65 + i) for i, o in enumerate(q['options']) if o['correct']]
        else:
            item['accepted_answers'] = q['answers']
        sample.append(item)
    result = _summary(questions)
    result.update({'ok': not errors and bool(questions), 'errors': _issues(errors), 'warnings': _issues(warnings),
                   'first_questions_as_understood': sample})
    if not questions and not errors:
        result['errors'] = ['Không tìm thấy câu hỏi nào. Mỗi câu phải bắt đầu bằng dòng [qus].']
        result['ok'] = False
    return result


def _find_org(value):
    value = str(value).strip()
    org = Organization.objects.filter(id=value).first() if value.isdigit() else None
    return org or Organization.objects.filter(slug=value).first()


def _target(ctx, organization, class_id):
    user = ctx.user
    org = classroom = None
    if organization and class_id:
        raise ToolError('Chỉ chọn một trong hai: organization hoặc class_id.')
    if class_id:
        classroom = Classroom.objects.filter(id=class_id).first()
        if classroom is None or not classroom.is_managed_by(user):
            raise ToolError('Không có lớp này hoặc bạn không quản lý lớp đó.')
    if organization:
        org = _find_org(organization)
        if org is None or not can_upload_for_org(user, org):
            raise ToolError('Không có tổ chức này hoặc bạn không phải quản trị của tổ chức đó.')
    if org is None and classroom is None and not can_upload(user):
        raise ToolError('Tài khoản của bạn chưa có quyền đăng quiz công khai trên CBNoj. '
                        'Hãy đăng trong tổ chức/lớp bạn quản lý (tham số organization hoặc class_id), '
                        'hoặc nhờ quản trị viên cấp quyền.')
    return org, classroom


@tool(
    'quiz_create',
    'Tạo một quiz từ đề viết theo cú pháp CBNoj. Quiz được tạo ở chế độ RIÊNG TƯ (chỉ người quản lý thấy), '
    'nếu đăng cho tổ chức/lớp thì thành bài thi riêng với khung giờ tạm (ngày mai), giáo viên chỉnh lại bằng '
    'quiz_configure hoặc trang quản lý. LUÔN gọi quiz_preview trước và chỉ tạo khi giáo viên đã đồng ý. '
    'NƠI ĐĂNG: xem where_can_post trong whoami; có nhiều nơi thì hỏi giáo viên rồi truyền organization hoặc class_id; '
    'tài khoản chỉ đăng được ở đúng một tổ chức/lớp thì bỏ trống, hệ thống tự đăng vào đó.',
    {
        'title': {'type': 'string', 'description': 'Tên quiz, tối đa 200 ký tự.'},
        'text': {'type': 'string', 'description': 'Toàn bộ đề theo cú pháp [qus]/[ans].'},
        'description': {'type': 'string', 'description': 'Mô tả ngắn (tùy chọn).'},
        'time_limit': {'type': 'integer', 'minimum': 0, 'maximum': 600, 'description': 'Số phút làm bài, 0 = không giới hạn.'},
        'max_attempts': {'type': 'integer', 'minimum': 0, 'maximum': 100, 'description': 'Số lần làm tối đa, 0 = không giới hạn.'},
        'shuffle_questions': {'type': 'boolean', 'description': 'Xáo thứ tự câu hỏi.'},
        'shuffle_options': {'type': 'boolean', 'description': 'Xáo thứ tự phương án.'},
        'show_answers': {'type': 'boolean', 'description': 'Cho xem đáp án sau khi nộp (mặc định true).'},
        'to_bank': {'type': 'boolean', 'description': 'Đồng thời thêm câu hỏi vào ngân hàng câu hỏi (mặc định true).'},
        'bank_tags': {'type': 'string', 'description': 'Thẻ ngân hàng thêm vào mọi câu, cách nhau bằng dấu phẩy.'},
        'organization': {'type': 'string', 'description': 'Slug hoặc id tổ chức (bạn phải là quản trị tổ chức) để đăng thành bài thi của tổ chức.'},
        'class_id': {'type': 'integer', 'description': 'Id lớp (bạn phải quản lý lớp) để đăng thành bài thi của lớp.'},
    },
    required=['title', 'text'],
)
def quiz_create(ctx, title, text, description='', time_limit=0, max_attempts=0, shuffle_questions=False,
                shuffle_options=False, show_answers=True, to_bank=True, bank_tags='', organization=None, class_id=None):
    title = ' '.join(str(title).split())
    if not title or len(title) > 200:
        raise ToolError('Tên quiz phải từ 1 đến 200 ký tự.')
    if not isinstance(time_limit, int) or not 0 <= time_limit <= 600:
        raise ToolError('time_limit phải là số phút từ 0 đến 600.')
    if not isinstance(max_attempts, int) or not 0 <= max_attempts <= 100:
        raise ToolError('max_attempts phải từ 0 đến 100.')
    auto = None
    if not organization and not class_id:
        auto = places.default_destination(ctx, 'quiz')
        if auto is not None:
            organization, class_id = (auto[1].slug, None) if auto[0] == 'organization' else (None, auto[1].id)
    org, classroom = _target(ctx, organization, class_id)
    questions, errors, warnings = _parse(text)
    if errors:
        raise ToolError('Đề còn lỗi, chưa tạo quiz:\n' + '\n'.join(_issues(errors)))
    if not questions:
        raise ToolError('Không tìm thấy câu hỏi nào. Mỗi câu phải bắt đầu bằng dòng [qus].')

    # Models (and people) retry: a same-titled quiz with the same number of questions made a moment ago is the same job.
    recent = Quiz.objects.filter(creator=ctx.profile, title=title, created__gte=timezone.now() - timedelta(minutes=5))
    for quiz in recent:
        if quiz.questions.count() == len(questions):
            return _created(ctx, quiz, questions, warnings, duplicate=True)

    quiz, bank_result = apply_quiz(
        ctx.profile, questions, title=title, description=str(description or ''), time_limit=time_limit,
        max_attempts=max_attempts, shuffle_questions=bool(shuffle_questions), shuffle_options=bool(shuffle_options),
        show_answers=bool(show_answers), is_public=False, source='MCP', org=org, classroom=classroom,
        to_bank=bool(to_bank), bank_tags=split_tags(bank_tags))
    result = _created(ctx, quiz, questions, warnings, bank_result=bank_result)
    if auto is not None:
        result['placed'] = places.where_note(*auto)
    return result


def _created(ctx, quiz, questions, warnings, duplicate=False, bank_result=None):
    result = {
        'id': quiz.id, 'slug': quiz.slug, 'title': quiz.title,
        'url': _absolute(ctx, quiz.get_absolute_url()),
        'manage_url': _absolute(ctx, reverse('quiz_manage', args=(quiz.slug,))),
        'mode': quiz.mode, 'is_public': quiz.is_public,
        'window_vn': [_vn(quiz.start_time), _vn(quiz.end_time)] if quiz.start_time else None,
        'warnings': _issues(warnings),
    }
    result.update(_summary(questions))
    if bank_result is not None:
        result['bank'] = {'added': bank_result[0], 'already_existed': bank_result[1]}
    if duplicate:
        result['note'] = 'Quiz cùng tên vừa được tạo cách đây ít phút nên không tạo trùng; trả về quiz đó.'
    else:
        result['next'] = ('Quiz đang ở chế độ riêng tư. Giáo viên mở manage_url để xem lại, đặt giờ thi / công khai; '
                          'hoặc dùng quiz_configure.')
    return result


def _to_form_data(quiz):
    data = model_to_dict(quiz, fields=ManageForm.Meta.fields)
    for key in ('start_time', 'end_time'):
        data[key] = data[key].astimezone(VN).strftime(DATETIME_INPUT) if data.get(key) else ''
    data['organizations'] = [o.id for o in quiz.organizations.all()]
    for key in ('course', 'lesson', 'track'):
        data[key] = data.get(key) or ''
    return data


def _time_value(name, value):
    if value in (None, ''):
        return ''
    match = TIME_RE.match(str(value).strip())
    if not match:
        raise ToolError('%s phải có dạng "YYYY-MM-DD HH:MM" theo giờ Việt Nam (ví dụ 2026-12-05 07:30).' % name)
    return '%sT%s' % (match.group(1), match.group(2))


@tool(
    'quiz_configure',
    'Đổi cấu hình của quiz bạn quản lý: chế độ luyện tập/thi, giờ mở-đóng (giờ Việt Nam), thời gian làm bài, giám sát, '
    'số câu rút ngẫu nhiên, cách công bố điểm... Chỉ gửi những trường muốn đổi. Không thể đặt công khai bằng công cụ này; '
    'giáo viên bấm công khai trên web. Cẩn thận khi đổi giờ/thời lượng của bài thi đang diễn ra.',
    {
        'slug': {'type': 'string', 'description': 'Slug của quiz (lấy từ quiz_list_mine hoặc quiz_create).'},
        'title': {'type': 'string'},
        'description': {'type': 'string'},
        'mode': {'type': 'string', 'enum': ['practice', 'exam'], 'description': 'practice = luyện tập, exam = bài thi có giờ mở/đóng.'},
        'start_time': {'type': 'string', 'description': 'Giờ mở, "YYYY-MM-DD HH:MM" giờ Việt Nam. Bắt buộc với mode exam.'},
        'end_time': {'type': 'string', 'description': 'Giờ đóng, cùng định dạng.'},
        'time_limit': {'type': 'integer', 'minimum': 0, 'maximum': 600, 'description': 'Số phút làm bài, 0 = không giới hạn.'},
        'max_attempts': {'type': 'integer', 'minimum': 0, 'maximum': 100},
        'questions_per_attempt': {'type': 'integer', 'minimum': 0, 'description': 'Mỗi bài rút ngẫu nhiên N câu, 0 = tất cả.'},
        'proctoring': {'type': 'string', 'enum': ['off', 'light', 'strict'], 'description': 'off = không giám sát, light = chặn copy/chuột phải, strict = khóa toàn màn hình.'},
        'max_violations': {'type': 'integer', 'minimum': 0, 'maximum': 50},
        'results_release': {'type': 'string', 'enum': ['immediate', 'after_end', 'manual'], 'description': 'Khi nào học sinh thấy điểm/đáp án.'},
        'rules_text': {'type': 'string', 'description': 'Nội quy hiển thị trước khi thi.'},
        'shuffle_questions': {'type': 'boolean'},
        'shuffle_options': {'type': 'boolean'},
        'show_answers': {'type': 'boolean'},
    },
    required=['slug'], idempotent=True,
)
def quiz_configure(ctx, slug, **changes):
    quiz = Quiz.objects.filter(slug=slug).first()
    if quiz is None or not quiz.is_manageable_by(ctx.user):
        raise ToolError('Không có quiz này hoặc bạn không có quyền quản lý nó.')
    if not changes:
        raise ToolError('Chưa có trường nào để đổi.')
    data = _to_form_data(quiz)
    for key, value in changes.items():
        data[key] = _time_value(key, value) if key in ('start_time', 'end_time') else value
    with timezone.override(VN):
        form = ManageForm(data, instance=quiz, user=ctx.user)
        if not form.is_valid():
            problems = ['%s: %s' % (field, ' '.join(errs)) for field, errs in form.errors.items()]
            raise ToolError('Cấu hình không hợp lệ, chưa lưu:\n' + '\n'.join(problems))
        form.save()
    quiz.refresh_from_db()
    return {
        'slug': quiz.slug, 'title': quiz.title, 'mode': quiz.mode, 'window_vn': [_vn(quiz.start_time), _vn(quiz.end_time)],
        'time_limit': quiz.time_limit, 'max_attempts': quiz.max_attempts,
        'questions_per_attempt': quiz.questions_per_attempt, 'proctoring': quiz.proctoring,
        'max_violations': quiz.max_violations, 'results_release': quiz.results_release,
        'is_public': quiz.is_public, 'manage_url': _absolute(ctx, reverse('quiz_manage', args=(quiz.slug,))),
    }


@tool(
    'quiz_list_mine',
    'Liệt kê các quiz do bạn tạo hoặc quản lý (mới nhất trước): id, slug, chế độ, công khai hay không, số câu, số lượt làm.',
    {'limit': {'type': 'integer', 'minimum': 1, 'maximum': 50, 'description': 'Số quiz tối đa, mặc định 20.'}},
    read_only=True, idempotent=True,
)
def quiz_list_mine(ctx, limit=20):
    limit = max(1, min(int(limit or 20), 50))
    quizzes = Quiz.objects.all()
    if not ctx.user.is_superuser:
        quizzes = quizzes.filter(Q(creator=ctx.profile) | Q(organizations__admins=ctx.profile)).distinct()
    rows = []
    for quiz in quizzes.annotate(n_questions=Count('questions', distinct=True),
                                 n_attempts=Count('attempts', distinct=True)).order_by('-id')[:limit]:
        rows.append({
            'id': quiz.id, 'slug': quiz.slug, 'title': quiz.title, 'mode': quiz.mode, 'is_public': quiz.is_public,
            'questions': quiz.n_questions, 'attempts': quiz.n_attempts,
            'window_vn': [_vn(quiz.start_time), _vn(quiz.end_time)] if quiz.start_time else None,
            'url': _absolute(ctx, quiz.get_absolute_url()),
        })
    return {'count': len(rows), 'quizzes': rows}


@tool(
    'quiz_results',
    'Tóm tắt kết quả một quiz bạn quản lý: số thí sinh, điểm trung bình (thang 10), phân bố điểm, các câu sai nhiều nhất '
    'và 10 bạn điểm cao nhất. Dữ liệu học sinh là thông tin riêng tư, chỉ dùng cho giáo viên.',
    {'slug': {'type': 'string'}},
    required=['slug'], read_only=True, idempotent=True,
)
def quiz_results(ctx, slug):
    quiz = Quiz.objects.filter(slug=slug).first()
    if quiz is None or not quiz.is_manageable_by(ctx.user):
        raise ToolError('Không có quiz này hoặc bạn không có quyền quản lý nó.')
    rows = quiz_stats.exam_ranking(quiz)
    accuracy = quiz_stats.question_accuracy(quiz, rows)
    hardest = sorted(((q, p, a) for q, p, a in accuracy), key=lambda x: x[1])[:5] if rows else []
    average = round(sum(r['score10'] for r in rows) / len(rows), 2) if rows else None
    return {
        'title': quiz.title, 'candidates': len(rows), 'average_score10': average,
        'distribution_score10': [{'from': lo, 'to': hi, 'count': c} for lo, hi, c in quiz_stats.score_distribution(rows)],
        'hardest_questions': [{'order': q.order, 'text': q.text[:100], 'percent_correct': p} for q, p, _ in hardest],
        'top10': [{'rank': r['rank'], 'username': r['user'].user.username, 'score10': r['score10'],
                   'minutes': round(r['seconds'] / 60, 1)} for r in rows[:10]],
        'results_url': _absolute(ctx, reverse('quiz_manage', args=(quiz.slug,))),
    }
