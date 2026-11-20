"""
Parser for quiz files.

Format (Word .docx, or plain .txt/.md). Every question starts with a marker line:

    [qus] Question text (can continue on the next lines)
    A. First option
    B. Second option
    [ans] B                 <- one letter = single choice, several letters (B, D) = multiple choice
    [exp] Optional explanation
    [pts] 2                 <- optional points, default 1
    [tag] Đại số, Hàm số    <- optional topics, used to filter the question bank
    [lvl] 2                 <- optional difficulty: 1 easy, 2 medium, 3 hard
    [psg] Reading text      <- optional shared passage (several lines); applies to the questions that follow
                               until the next [psg]; an empty [psg] ends it

A question without options is a short-answer question: [ans] holds the accepted answers separated by |.
Marker names are case-insensitive; a few aliases are accepted (see MARKERS).
"""
import io
import re
import unicodedata
import zipfile
from xml.sax.saxutils import escape

from defusedxml import ElementTree

MARKERS = {
    'qus': 'question', 'q': 'question', 'question': 'question', 'cau': 'question',
    'ans': 'answer', 'a': 'answer', 'answer': 'answer', 'dapan': 'answer',
    'exp': 'explanation', 'explain': 'explanation', 'giaithich': 'explanation',
    'pts': 'points', 'point': 'points', 'points': 'points', 'diem': 'points',
    'tag': 'tags', 'tags': 'tags', 'chude': 'tags',
    'lvl': 'level', 'level': 'level', 'dokho': 'level',
    'type': 'qtype', 'loai': 'qtype', 'sec': 'section', 'section': 'section', 'phan': 'section',
    'psg': 'passage', 'passage': 'passage', 'doan': 'passage', 'ngulieu': 'passage',
}
TF_WORDS = {'tf', 'dungsai', 'ds', 'truefalse', 'tf4'}
NO_TRUE_WORDS = {'none', 'khong', 'null', 'nil'}
LEVEL_WORDS = {'1': 1, 'de': 1, 'easy': 1, '2': 2, 'tb': 2, 'trungbinh': 2, 'medium': 2, '3': 3, 'kho': 3, 'hard': 3}
MARKER_RE = re.compile(r'^\s*\[\s*([A-Za-z]+)\s*\]\s*(.*)$')
OPTION_RE = re.compile(r'^\s*(\*?)\s*([A-Za-z])\s*[\.\)]\s+(.*)$')
LETTERS_RE = re.compile(r'[A-Za-z]')
MAX_QUESTIONS = 500
MAX_OPTIONS = 10

W_NS = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'


class QuizFormatError(Exception):
    pass


def _ascii(text):
    """Strip Vietnamese diacritics so 'Đúng sai' and 'dung sai' compare equal."""
    text = (text or '').replace('đ', 'd').replace('Đ', 'D')
    return unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('ascii')


def docx_to_lines(data):
    """Return the text of a .docx as a list of lines (one per paragraph, soft line breaks split too)."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            if 'word/document.xml' not in archive.namelist():
                raise QuizFormatError('word/document.xml is missing')
            if archive.getinfo('word/document.xml').file_size > 20 * 1024 * 1024:
                raise QuizFormatError('document is too large')
            xml = archive.read('word/document.xml')
    except zipfile.BadZipFile:
        raise QuizFormatError('not a valid .docx file (save the document as .docx, not .doc)')
    try:
        root = ElementTree.fromstring(xml)
    except Exception:  # ParseError, or defusedxml refusing entities / external references
        raise QuizFormatError('cannot read the document content')

    lines = []
    for paragraph in root.iter(W_NS + 'p'):
        buffer = []
        for node in paragraph.iter():
            if node.tag == W_NS + 't':
                buffer.append(node.text or '')
            elif node.tag == W_NS + 'tab':
                buffer.append(' ')
            elif node.tag in (W_NS + 'br', W_NS + 'cr'):
                buffer.append('\n')
        lines.extend(''.join(buffer).split('\n'))
    return lines


def text_to_lines(data):
    for encoding in ('utf-8-sig', 'utf-16', 'cp1258', 'latin-1'):
        try:
            return data.decode(encoding).splitlines()
        except (UnicodeDecodeError, UnicodeError):
            continue
    raise QuizFormatError('cannot decode the file')


def file_to_lines(name, data):
    lowered = (name or '').lower()
    if lowered.endswith('.docx'):
        return docx_to_lines(data)
    if lowered.endswith(('.txt', '.md')):
        return text_to_lines(data)
    if lowered.endswith('.doc'):
        raise QuizFormatError('old .doc files are not supported: open it in Word and save as .docx')
    raise QuizFormatError('unsupported file type, use .docx, .txt or .md')


def parse_quiz_lines(lines):
    """
    Returns (questions, errors, warnings).
    questions: [{'text', 'kind', 'options': [{'text', 'correct'}], 'answers': [...], 'explanation', 'points'}]
    errors / warnings: [{'line': int, 'question': int or None, 'message': str}]
    """
    questions, errors, warnings = [], [], []
    current = None
    field = None  # where continuation lines go: ('text',) / ('option', index) / ('explanation',)
    ignored_before_first = False
    section = ['']
    passage = ['']

    def err(line_no, message):
        errors.append({'line': line_no, 'question': len(questions) if current is not None else None,
                       'message': message})

    def start_question(line_no, text):
        nonlocal current, field
        if current is not None:
            questions.append(current)
        current = {'line': line_no, 'text': text.strip(), 'options': [], 'answer_raw': None, 'answer_line': None,
                   'explanation': '', 'points': 1.0, 'star': set(), 'tags': [], 'level': 0,
                   'qtype': None, 'section': section[0], 'passage': passage[0], 'lower': 0}
        field = ('text',)

    for line_no, raw in enumerate(lines, 1):
        stripped = raw.strip()
        marker = MARKER_RE.match(raw)
        key = MARKERS.get(marker.group(1).lower()) if marker else None

        if key == 'section':
            # Sticky: names the section of every following question until the next [sec].
            section[0] = marker.group(2).strip()[:60]
            if current is not None:
                field = None
            continue
        if key == 'passage':
            # Sticky like [sec], but the text may run over several lines.
            passage[0] = marker.group(2).strip()
            field = ('passage',)
            continue
        if key == 'question':
            start_question(line_no, marker.group(2))
            continue
        if field == ('passage',) and not (marker and key):
            if stripped:
                passage[0] = (passage[0] + '\n' + stripped).strip()
            continue
        if current is None:
            if stripped and not ignored_before_first:
                warnings.append({'line': line_no, 'question': None,
                                 'message': 'Text before the first [qus] is ignored.'})
                ignored_before_first = True
            continue
        if key == 'answer':
            current['answer_raw'] = marker.group(2).strip()
            current['answer_line'] = line_no
            field = None
            continue
        if key == 'explanation':
            current['explanation'] = marker.group(2).strip()
            field = ('explanation',)
            continue
        if key == 'points':
            try:
                value = float(marker.group(2).strip().replace(',', '.'))
                if value < 0:
                    raise ValueError
                current['points'] = value
            except ValueError:
                errors.append({'line': line_no, 'question': len(questions) + 1,
                               'message': '[pts] must be a non-negative number.'})
            field = None
            continue
        if key == 'tags':
            current['tags'] = [t.strip()[:40] for t in re.split(r'[,;]', marker.group(2)) if t.strip()]
            field = None
            continue
        if key == 'level':
            word = re.sub(r'[^a-z0-9]', '', marker.group(2).strip().lower())
            if word in LEVEL_WORDS:
                current['level'] = LEVEL_WORDS[word]
            else:
                errors.append({'line': line_no, 'question': len(questions) + 1,
                               'message': '[lvl] must be 1, 2 or 3 (easy, medium, hard).'})
            field = None
            continue
        if key == 'qtype':
            word = re.sub(r'[^a-z0-9]', '', _ascii(marker.group(2)).lower())
            if word in TF_WORDS:
                current['qtype'] = 'tf'
            elif word:
                warnings.append({'line': line_no, 'question': len(questions) + 1,
                                 'message': 'Unknown [type] %r is ignored (use [type] tf).' % marker.group(2).strip()})
            field = None
            continue
        if marker and key is None and stripped:
            warnings.append({'line': line_no, 'question': len(questions) + 1,
                             'message': 'Unknown marker [%s] is treated as text.' % marker.group(1)})

        if not stripped:
            continue

        option = OPTION_RE.match(raw) if field != ('explanation',) else None
        if option and current['answer_raw'] is None:
            star, letter, text = option.groups()
            expected = chr(65 + len(current['options']))
            if letter.upper() == expected:
                current['options'].append({'text': text.strip(), 'correct': False})
                if letter.islower():
                    current['lower'] += 1
                if star:
                    current['star'].add(len(current['options']) - 1)
                field = ('option', len(current['options']) - 1)
                continue
        if field == ('text',):
            current['text'] += '\n' + stripped
        elif field and field[0] == 'option':
            current['options'][field[1]]['text'] += '\n' + stripped
        elif field == ('explanation',):
            current['explanation'] += '\n' + stripped
        else:
            warnings.append({'line': line_no, 'question': len(questions) + 1,
                             'message': 'Unexpected text after [ans] is ignored.'})
    if current is not None:
        questions.append(current)

    cleaned = []
    for number, q in enumerate(questions, 1):
        def qerr(message, line=None):
            errors.append({'line': line or q['line'], 'question': number, 'message': message})

        if not q['text']:
            qerr('The question text is empty.')
        options = q['options']
        raw = q['answer_raw']
        if len(options) > MAX_OPTIONS:
            qerr('At most %d options are allowed.' % MAX_OPTIONS)
        # True/false question: 4 statements a) b) c) d), [ans] lists the true ones. Chosen with [type] tf or by
        # writing exactly four lower-case labels.
        is_tf = bool(options) and (q['qtype'] == 'tf' or (q['qtype'] is None and len(options) == 4 and q['lower'] == 4))
        if options:
            if is_tf:
                if len(options) != 4:
                    qerr('A true/false question needs exactly 4 statements (a, b, c, d).')
            elif len(options) < 2:
                qerr('A choice question needs at least 2 options (A, B, ...).')
            word = re.sub(r'[^a-z]', '', _ascii(raw or '').lower())
            none_true = is_tf and raw is not None and (not LETTERS_RE.search(raw) or word in NO_TRUE_WORDS)
            letters = [] if none_true else [c.upper() for c in LETTERS_RE.findall(raw or '')]
            if raw is None and q['star']:
                chosen = set(q['star'])
            elif none_true:
                chosen = set()
            elif not letters:
                chosen = set()
                qerr('Missing [ans] with the correct option letter(s).')
            else:
                chosen = set()
                for letter in letters:
                    index = ord(letter) - 65
                    if index >= len(options):
                        qerr('[ans] refers to option %s which does not exist.' % letter, q['answer_line'])
                    else:
                        chosen.add(index)
            for index in chosen:
                options[index]['correct'] = True
            if options and not chosen and raw is not None and letters:
                qerr('No valid correct option.')
            kind = 'tf4' if is_tf else 'multi' if len(chosen) > 1 else 'single'
            answers = []
        else:
            kind = 'short'
            answers = [a.strip() for a in (raw or '').split('|') if a.strip()]
            if not answers:
                qerr('A question without options needs [ans] with the accepted answer(s).')
        cleaned.append({
            'line': q['line'], 'text': q['text'], 'kind': kind, 'points': q['points'],
            'options': [{'text': o['text'], 'correct': o['correct']} for o in options],
            'answers': answers, 'explanation': q['explanation'].strip(),
            'tags': q['tags'], 'level': q['level'], 'section': q['section'], 'passage': q['passage'][:20000],
        })

    if not cleaned and not errors:
        errors.append({'line': None, 'question': None, 'message': 'No questions found. Each question must start with [qus].'})
    if len(cleaned) > MAX_QUESTIONS:
        errors.append({'line': None, 'question': None, 'message': 'At most %d questions per quiz.' % MAX_QUESTIONS})
    return cleaned, errors, warnings


def parse_quiz_file(name, data):
    lines = file_to_lines(name, data)
    return parse_quiz_lines(lines)


TEMPLATE_LINES = [
    'MẪU ĐỀ TRẮC NGHIỆM — xóa các dòng này và thay bằng đề của bạn',
    'Quy ước: mỗi câu hỏi bắt đầu bằng [qus]. Các đáp án gõ tay A. B. C. D. (không dùng danh sách tự động đánh số).',
    '[ans] ghi chữ cái đáp án đúng. Nhiều chữ cái (ví dụ B, D) là câu nhiều đáp án đúng. Không có đáp án A. B. = câu trả lời ngắn.',
    '[exp] giải thích (không bắt buộc). [pts] số điểm của câu (không bắt buộc, mặc định 1).',
    '[tag] chủ đề, cách nhau bằng dấu phẩy (không bắt buộc, dùng để lọc ngân hàng đề). [lvl] độ khó 1 dễ, 2 trung bình, 3 khó (không bắt buộc).',
    '',
    '[qus] Thủ đô của Việt Nam là thành phố nào?',
    'A. Hà Nội',
    'B. Huế',
    'C. Đà Nẵng',
    'D. Hồ Chí Minh',
    '[ans] A',
    '[exp] Hà Nội là thủ đô của nước Cộng hòa xã hội chủ nghĩa Việt Nam.',
    '',
    '[qus] Những số nào sau đây là số nguyên tố?',
    'A. 2',
    'B. 4',
    'C. 7',
    'D. 9',
    '[ans] A, C',
    '[pts] 2',
    '[tag] Số học, Số nguyên tố',
    '[lvl] 2',
    '',
    '[qus] Kết quả của 3 + 4 là bao nhiêu?',
    '[ans] 7 | bảy',
    '',
    'Câu đúng/sai (dạng Phần II đề THPTQG): đúng 4 ý a) b) c) d) viết thường, [ans] ghi các ý ĐÚNG (ghi "không" nếu cả 4 ý đều sai).',
    '[sec] Phần II',
    '[qus] Các phát biểu sau về mạng máy tính đúng hay sai?',
    'a) Địa chỉ IP dùng để định danh thiết bị trong mạng.',
    'b) Giao thức HTTP là giao thức tầng vật lý.',
    'c) Router có chức năng chuyển tiếp gói tin giữa các mạng.',
    'd) Một địa chỉ IPv4 gồm 64 bit.',
    '[ans] a, c',
    '[pts] 1',
    '[tag] Mạng máy tính',
    '',
]


def build_template_docx():
    """A minimal valid .docx with the sample questions, built without any dependency."""
    paragraphs = ''.join(
        '<w:p><w:r><w:t xml:space="preserve">%s</w:t></w:r></w:p>' % escape(line) for line in TEMPLATE_LINES
    )
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
        + paragraphs + '</w:body></w:document>'
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '</Types>'
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="word/document.xml"/></Relationships>'
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('[Content_Types].xml', content_types)
        archive.writestr('_rels/.rels', rels)
        archive.writestr('word/document.xml', document)
    return buffer.getvalue()
