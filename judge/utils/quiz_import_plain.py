"""
Import of "ordinary" exam papers: a Word (.docx) or text PDF that is just a printed exam, without the [qus] markers
used by quiz_parser.

Recognised layout (Vietnamese or English):
  * a question starts a line with `Câu 1.`, `Câu 1:`, `Question 1`, `Q1.` or (when the document never says "Câu")
    a plain `1.` / `1)`;
  * options `A.` `B)` `a.` ... (2-6), one per line or several on one line;
  * the correct answer comes from, in this order, an `Đáp án: C` line, the answer table at the end of the paper
    (`1-A 2-B ...`, or a two-row / two-column table), and finally underlined / bold / coloured options (.docx);
  * sections `PHẦN I`, `Phần II. Câu trắc nghiệm đúng sai`, `Phần III. Trả lời ngắn` decide the kind:
    single choice, true/false with four statements a) b) c) d), or short answer.

Nothing here touches the database. `parse_plain_file` returns {'questions': [...], 'doc_warnings': [...]}; every
question carries `warn`, a list of codes (see WARNING_CODES) that the preview page shows.
"""
import io
import re
import unicodedata
import zipfile

from defusedxml import ElementTree

MAX_BYTES = 10 * 1024 * 1024
MAX_QUESTIONS = 300
MAX_PDF_PAGES = 100
MAX_DOCUMENT_XML = 20 * 1024 * 1024
FIGURE_MARK = '[hình]'

WARNING_CODES = ('no_answer', 'few_options', 'figure', 'formula', 'bad_answer', 'partial_answer', 'no_options')

F_BOLD, F_UNDER, F_COLOR = 1, 2, 4
MARK_PRIORITY = (F_UNDER, F_BOLD, F_COLOR)

W_NS = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
M_NS = '{http://schemas.openxmlformats.org/officeDocument/2006/math}'
DRAWING_TAGS = {W_NS + 'drawing', W_NS + 'pict', W_NS + 'object'}


class PlainImportError(Exception):
    """A problem with the file as a whole; the message is shown to the teacher (Vietnamese)."""


class Line:
    """One line of text with, for each character, a bit set telling whether it is bold / underlined / coloured."""
    __slots__ = ('text', 'fmt', 'formula')

    def __init__(self, text, fmt=None, formula=False):
        self.text = text
        self.fmt = fmt if fmt is not None else bytearray(len(text))
        self.formula = formula

    def slice(self, start, end):
        return Line(self.text[start:end], bytearray(self.fmt[start:end]), self.formula)


def fold(text):
    """Lower-case, no diacritics: 'Đáp án' -> 'dap an'."""
    text = (text or '').replace('đ', 'd').replace('Đ', 'D')
    return unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('ascii').lower()


# ------------------------------------------------------------------------------------------------- .docx

def _local(node):
    return node.tag.rsplit('}', 1)[-1]


def _on(node, name):
    """A boolean run property such as <w:b/> or <w:b w:val="0"/>."""
    child = node.find(W_NS + name)
    if child is None:
        return False
    return child.get(W_NS + 'val', '1').lower() not in ('0', 'false', 'off', 'none')


def _run_flags(run):
    props = run.find(W_NS + 'rPr')
    if props is None:
        return 0
    flags = 0
    if _on(props, 'b'):
        flags |= F_BOLD
    underline = props.find(W_NS + 'u')
    if underline is not None and underline.get(W_NS + 'val', 'single').lower() != 'none':
        flags |= F_UNDER
    color = props.find(W_NS + 'color')
    if color is not None and color.get(W_NS + 'val', 'auto').lower() not in ('auto', '000000', 'ffffff'):
        flags |= F_COLOR
    highlight = props.find(W_NS + 'highlight')
    if highlight is not None and highlight.get(W_NS + 'val', 'none').lower() != 'none':
        flags |= F_COLOR
    return flags


def _children(node, name):
    return [c for c in node if c.tag == M_NS + name]


def _omml_child(node, name):
    found = _children(node, name)
    return omml_to_text(found[0]) if found else ''


NARY_SYMBOLS = {'∑': '\\sum', '∏': '\\prod', '∫': '\\int', '∬': '\\iint', '∮': '\\oint'}


def omml_to_text(node):
    """Office Math -> a LaTeX-like string (lossy but readable). Unknown structures keep their text."""
    kind = _local(node)
    if kind == 't':
        return node.text or ''
    if kind == 'f':
        return '\\frac{%s}{%s}' % (_omml_child(node, 'num'), _omml_child(node, 'den'))
    if kind == 'sSup':
        return '{%s}^{%s}' % (_omml_child(node, 'e'), _omml_child(node, 'sup'))
    if kind == 'sSub':
        return '{%s}_{%s}' % (_omml_child(node, 'e'), _omml_child(node, 'sub'))
    if kind == 'sSubSup':
        return '{%s}_{%s}^{%s}' % (_omml_child(node, 'e'), _omml_child(node, 'sub'), _omml_child(node, 'sup'))
    if kind == 'rad':
        degree = _omml_child(node, 'deg')
        root = '\\sqrt[%s]{%s}' if degree else '\\sqrt%s{%s}'
        return root % (degree, _omml_child(node, 'e'))
    if kind == 'd':
        props = node.find(M_NS + 'dPr')
        begin = end = None
        if props is not None:
            b, e = props.find(M_NS + 'begChr'), props.find(M_NS + 'endChr')
            begin = b.get(M_NS + 'val') if b is not None else None
            end = e.get(M_NS + 'val') if e is not None else None
        inner = ', '.join(omml_to_text(e) for e in _children(node, 'e'))
        return '%s%s%s' % ('(' if begin is None else begin, inner, ')' if end is None else end)
    if kind == 'nary':
        props = node.find(M_NS + 'naryPr')
        symbol = '∫'
        if props is not None and props.find(M_NS + 'chr') is not None:
            symbol = props.find(M_NS + 'chr').get(M_NS + 'val', symbol)
        text = NARY_SYMBOLS.get(symbol, symbol)
        sub, sup = _omml_child(node, 'sub'), _omml_child(node, 'sup')
        if sub:
            text += '_{%s}' % sub
        if sup:
            text += '^{%s}' % sup
        return text + ' ' + _omml_child(node, 'e')
    if kind.endswith('Pr'):
        return ''
    return ''.join(omml_to_text(child) for child in node)


class _DocxReader:
    def __init__(self):
        self.lines = []

    def paragraph(self, p):
        """Append the lines of a paragraph; returns them (a soft line break makes several)."""
        text, fmt = [], []

        def add(piece, flags):
            piece = unicodedata.normalize('NFC', piece)
            text.append(piece)
            fmt.extend([flags] * len(piece))

        formula = False

        def walk(node, depth=0):
            nonlocal formula
            for child in node:
                tag = child.tag
                if tag == W_NS + 'r':
                    flags = _run_flags(child)
                    drawn = False
                    for part in child.iter():
                        ptag = part.tag
                        if ptag == W_NS + 't':
                            add(part.text or '', flags)
                        elif ptag == W_NS + 'tab':
                            add(' ', flags)
                        elif ptag in (W_NS + 'br', W_NS + 'cr'):
                            add('\n', 0)
                        elif ptag in DRAWING_TAGS and not drawn:
                            drawn = True
                            add(FIGURE_MARK, 0)
                elif tag in (M_NS + 'oMath', M_NS + 'oMathPara'):
                    formula = True
                    maths = [child] if tag == M_NS + 'oMath' else _children(child, 'oMath')
                    pieces = [omml_to_text(m) for m in maths]
                    body = ' '.join(x for x in pieces if x.strip())
                    if body:
                        add('$%s$' % body, 0)
                elif tag in (W_NS + 'hyperlink', W_NS + 'ins', W_NS + 'smartTag', W_NS + 'sdt', W_NS + 'sdtContent',
                             W_NS + 'fldSimple') and depth < 6:
                    walk(child, depth + 1)

        walk(p)
        pieces = ''.join(text)
        out, start = [], 0
        fmts = bytearray(fmt)
        for part in pieces.split('\n'):
            out.append(Line(part, bytearray(fmts[start:start + len(part)])))
            start += len(part) + 1
        for line in out:
            line.formula = formula
        return out

    def table(self, tbl):
        for row in tbl.iter(W_NS + 'tr'):
            cells = []
            for cell in row.findall(W_NS + 'tc'):
                parts = []
                for p in cell.iter(W_NS + 'p'):
                    parts.extend(self.paragraph(p))
                cells.append(parts)
            merged = Line('')
            for cell in cells:
                for line in cell:
                    merged.formula = merged.formula or line.formula
                    if merged.text:
                        merged.text += ' '
                        merged.fmt.append(0)
                    merged.text += line.text
                    merged.fmt.extend(line.fmt)
            self.lines.append(merged)

    def body(self, node, depth=0):
        for child in node:
            if child.tag == W_NS + 'p':
                self.lines.extend(self.paragraph(child))
            elif child.tag == W_NS + 'tbl':
                self.table(child)
            elif child.tag in (W_NS + 'sdt', W_NS + 'sdtContent') and depth < 6:
                self.body(child, depth + 1)


def docx_to_lines(data):
    """Returns (lines, info); a line whose paragraph holds an equation has `formula` set."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            if 'word/document.xml' not in archive.namelist():
                raise PlainImportError('Tệp .docx không hợp lệ (thiếu word/document.xml).')
            if archive.getinfo('word/document.xml').file_size > MAX_DOCUMENT_XML:
                raise PlainImportError('Tài liệu Word quá lớn.')
            xml = archive.read('word/document.xml')
    except zipfile.BadZipFile:
        raise PlainImportError('Không phải tệp .docx hợp lệ (hãy lưu lại bằng Word dưới dạng .docx, không dùng .doc).')
    try:
        root = ElementTree.fromstring(xml)
    except Exception:
        raise PlainImportError('Không đọc được nội dung tệp Word.')
    body = root.find(W_NS + 'body')
    reader = _DocxReader()
    if body is not None:
        reader.body(body)
    return reader.lines, {'pdf': False}


# --------------------------------------------------------------------------------------------------- .pdf

PDF_FORMULA_RE = re.compile('[∑∫√∞≤≥≠≈±×÷∈∉⊂⊆∪∩→⇒⇔αβγδθλμπσφω²³⁴ⁿ₀₁₂]|\\^\\s*\\d|\\bsqrt\\b')
PAGE_NUMBER_RE = re.compile(r'^\s*(?:(?:Trang|Page)\s*\d+(?:\s*/\s*\d+)?|-\s*\d+\s*-|\d+\s*/\s*\d+)\s*$', re.I)


def pdf_to_lines(data):
    """Text of a text-based PDF as lines. Scanned (image only) PDFs raise PlainImportError."""
    try:
        import pypdfium2 as pdfium
    except ImportError:
        raise PlainImportError('Máy chủ chưa cài thư viện đọc PDF (pypdfium2). Hãy dùng tệp Word.')
    try:
        pdf = pdfium.PdfDocument(data)
    except Exception:
        raise PlainImportError('Không mở được tệp PDF (hỏng hoặc có mật khẩu). Hãy dùng tệp Word hoặc PDF chữ.')
    try:
        pages = len(pdf)
        if pages > MAX_PDF_PAGES:
            raise PlainImportError('PDF có hơn %d trang.' % MAX_PDF_PAGES)
        texts, image_pages = [], []
        for number in range(pages):
            page = pdf[number]
            textpage = page.get_textpage()
            try:
                texts.append(textpage.get_text_range() or '')
            finally:
                textpage.close()
            try:
                if any(True for _ in page.get_objects(filter=[3])):   # 3 = FPDF_PAGEOBJ_IMAGE
                    image_pages.append(number + 1)
            except Exception:
                pass
            page.close()
    finally:
        pdf.close()
    letters = sum(1 for ch in ''.join(texts) if ch.isalnum())
    if letters < 40 or letters < 15 * max(pages, 1):
        raise PlainImportError('PDF này là ảnh chụp/scan, không có chữ để đọc. '
                               'Cần tệp Word (.docx) hoặc PDF chữ (xuất trực tiếp từ Word).')
    lines = []
    for text in texts:
        for raw in unicodedata.normalize('NFC', text).replace(' ', ' ').splitlines():
            if raw.strip() and not PAGE_NUMBER_RE.match(raw):
                lines.append(Line(raw))
    return lines, {'pdf': True, 'image_pages': image_pages}


def text_to_lines(data):
    for encoding in ('utf-8-sig', 'utf-16', 'cp1258'):
        try:
            text = data.decode(encoding)
            break
        except (UnicodeDecodeError, UnicodeError):
            continue
    else:
        raise PlainImportError('Không đọc được bảng mã của tệp.')
    lines = [Line(unicodedata.normalize('NFC', raw)) for raw in text.splitlines()]
    return lines, {'pdf': False}


def file_to_lines(name, data):
    lowered = (name or '').lower()
    if len(data) > MAX_BYTES:
        raise PlainImportError('Tệp lớn hơn %d MB.' % (MAX_BYTES // 1024 // 1024))
    if lowered.endswith('.docx'):
        return docx_to_lines(data)
    if lowered.endswith('.pdf'):
        return pdf_to_lines(data)
    if lowered.endswith('.txt'):
        return text_to_lines(data)
    if lowered.endswith('.doc'):
        raise PlainImportError('Tệp .doc cũ chưa được hỗ trợ: mở bằng Word và lưu lại dưới dạng .docx.')
    raise PlainImportError('Chỉ nhận tệp .docx (Word) hoặc .pdf chữ.')


# ----------------------------------------------------------------------------------------------- recognising

QUESTION_RE = re.compile(r'^\s*(?:(?:C[âa]u(?:\s*h[ỏo]i)?|Question|Q)\s*(\d+)\s*[\.:\)\-–]*\s*|'
                         r'(\d{1,3})\s*[\.\)]\s+)(.*)$', re.I)
CAU_RE = re.compile(r'^\s*(?:C[âa]u(?:\s*h[ỏo]i)?|Question|Q)\s*\d+', re.I)
SECTION_RE = re.compile(r'^\s*(?i:phần|phan|part|section)\s+([IVX]+|\d+)\b(.*)$')
ANSWER_RE = re.compile(r'^\s*(?:Đáp\s*án(?:\s*đúng)?|ĐA|Answer|Key|Đáp\s*số)\s*[:\-–]\s*(.*)$', re.I)
EXPLAIN_RE = re.compile(r'^\s*(?:Lời\s*giải|Giải\s*thích|Hướng\s*dẫn(?:\s*giải)?|Explanation|Solution)\b'
                        r'\s*[:\-–.]?\s*(.*)$', re.I)
KEY_HEADING_RE = re.compile(r'^\W*(?:bang\s+)?(?:dap\s*an|huong\s*dan\s*(?:giai|cham)|answer\s*keys?|answers?|key|'
                            r'loi\s*giai(?:\s*chi\s*tiet)?)\b\W*(.*)$')
KEY_PAIR_RE = re.compile(r'(?:C[âa]u\s*)?(\d{1,3})\s*[-–:\)\.]\s*(.+?)'
                         r'(?=\s+(?:C[âa]u\s*)?\d{1,3}\s*[-–:\)\.]\s*\S|\s*$)', re.I)
TF_PAIR_RE = re.compile(r'(?<![A-Za-zÀ-ỹ])([a-dA-D])\s*[\)\.\-–:=]?\s*(Đúng|Sai|Đ|S|True|False|T|F)(?![A-Za-zÀ-ỹ])')
LETTER_RE = re.compile(r'(?<![A-Za-zÀ-ỹ0-9])([A-Fa-f])(?![A-Za-zÀ-ỹ0-9])')
FIGURE_REF_RE = re.compile(r'(?:hình|sơ đồ|đồ thị|biểu đồ|bảng)\s+(?:vẽ\s+)?(?:sau|dưới|bên|trên)|'
                           r'quan sát\s+(?:hình|sơ đồ)|figure|diagram', re.I)

TF_WORDS_RE = re.compile(r'dung\s*[-/,]?\s*sai|true\s*/?\s*false')
SHORT_WORDS_RE = re.compile(r'tra\s*loi\s*ngan|short\s*answer|dien\s*(?:dap\s*an|ket\s*qua)')
SINGLE_WORDS_RE = re.compile(r'nhieu\s*lua\s*chon|mot\s*dap\s*an|one\s*answer|multiple\s*choice|trac\s*nghiem')
ROMAN = {'I': 1, 'II': 2, 'III': 3, 'IV': 4}
ORDINAL_KIND = {1: 'single', 2: 'tf4', 3: 'short'}


def section_kind(text):
    """Kind announced by a section heading, or None."""
    folded = fold(text)
    if TF_WORDS_RE.search(folded):
        return 'tf4'
    if SHORT_WORDS_RE.search(folded):
        return 'short'
    if SINGLE_WORDS_RE.search(folded):
        return 'single'
    return None


def _marked_fraction(line, flag):
    chars = [(ch, f) for ch, f in zip(line.text, line.fmt) if not ch.isspace()]
    if not chars:
        return 0.0
    return sum(1 for _, f in chars if f & flag) / len(chars)


def split_options(line, count):
    """
    Find option markers in `line`. `count` options exist already, so the next letter is chr(65 + count).
    Returns [(marker_start, marker_end, letter, punct)]. A marker in the middle of a line only counts after an
    earlier marker on the same line (or when the line is the one carrying the first option and 'B' follows).
    """
    text = line.text
    found, pos, expected = [], 0, count
    while expected < 6:
        letter = chr(65 + expected)
        pattern = re.compile(r'(?:(?<=\s)|^)([%s%s])\s?([\.\)])(?!\.)' % (letter, letter.lower()))
        match = pattern.search(text, pos)
        if match is None:
            break
        at_start = not text[:match.start()].strip()
        if not at_start and not found:
            if expected != 0:
                break    # a stray "C." in the middle of ordinary text
            nxt = re.compile(r'(?:(?<=\s)|^)[Bb]\s?[\.\)](?!\.)').search(text, match.end())
            if nxt is None:
                break
        found.append((match.start(), match.end(), match.group(1), match.group(2)))
        pos = match.end()
        expected += 1
    return found


def _answer_letters(raw, option_count):
    letters, bad = [], False
    for letter in LETTER_RE.findall(raw or ''):
        index = ord(letter.upper()) - 65
        if index >= option_count:
            bad = True
        elif index not in letters:
            letters.append(index)
    return letters, bad


def _tf_truth(raw):
    """True/false statements from text such as 'a) Đ b) S c) Đ d) Đ', 'ĐSĐS', 'a, c' (the true ones)."""
    raw = (raw or '').strip()
    pairs = TF_PAIR_RE.findall(raw)
    if pairs:
        truth = {}
        for letter, word in pairs:
            truth[ord(letter.lower()) - 97] = word[0].upper() in 'ĐT'
        return truth, len(truth) < 4
    compact = re.sub(r'[\s,;\-–/]', '', raw)
    if len(compact) == 4 and re.fullmatch(r'[ĐSdsTF]{4}', compact):
        return {i: ch.upper() in 'ĐDT' for i, ch in enumerate(compact)}, False
    letters = [ord(x.lower()) - 97 for x in re.findall(r'(?<![A-Za-zÀ-ỹ])([a-dA-D])(?![A-Za-zÀ-ỹ])', raw)]
    if letters:
        return {i: i in letters for i in range(4)}, False
    return None, False


def _split_short(raw):
    return [a.strip() for a in re.split(r'\s*\|\s*|\s+hoặc\s+', (raw or '').strip()) if a.strip()]


# ------------------------------------------------------------------------------------------------ answer table

def _tokens(text):
    return [t for t in re.split(r'[\s|;,\t]+', text.strip()) if t]


def parse_answer_table(lines):
    """{question number: raw answer text} from key lines ("1-A 2-B", "Câu 1: C", or a number row + letter row)."""
    key, index = {}, 0
    texts = [line.text if isinstance(line, Line) else line for line in lines]
    while index < len(texts):
        text = texts[index]
        head = KEY_HEADING_RE.match(fold(text))
        body = text[len(text) - len(head.group(1)):] if head and head.group(1) else text
        tokens = _tokens(re.sub(r'^\s*(?:Câu|Cau|Question)\b[\s:]*', '', body, flags=re.I))
        if len(tokens) >= 3 and all(re.fullmatch(r'\d{1,3}', t) for t in tokens) and index + 1 < len(texts):
            below = _tokens(re.sub(r'^\s*(?:Đáp\s*án|ĐA|Answer|Key)\b[\s:]*', '', texts[index + 1], flags=re.I))
            if len(below) == len(tokens):
                for number, value in zip(tokens, below):
                    key.setdefault(int(number), value)
                index += 2
                continue
        for match in KEY_PAIR_RE.finditer(body):
            key.setdefault(int(match.group(1)), match.group(2).strip())
        index += 1
    return key


def _keyish(text):
    pairs = KEY_PAIR_RE.findall(text)
    if len(pairs) >= 2:
        return True
    tokens = _tokens(text)
    if len(tokens) >= 3 and all(re.fullmatch(r'\d{1,3}', t) for t in tokens):
        return True
    return len(tokens) >= 3 and all(re.fullmatch(r'[A-Fa-fĐSđs]{1,4}', t) for t in tokens)


def _plausible_key(lines):
    short = [v for v in parse_answer_table(lines).values() if len(v) <= 20]
    return len(short) >= 2


def split_answer_region(lines):
    """(question lines, answer-table lines). The table starts at a 'Đáp án' heading or is a run of key-like lines."""
    first_question = next((i for i, line in enumerate(lines) if QUESTION_RE.match(line.text)), None)
    if first_question is None:
        return lines, []
    for index in range(first_question + 1, len(lines)):
        head = KEY_HEADING_RE.match(fold(lines[index].text))
        if not head:
            continue
        rest = head.group(1).strip()
        following = lines[index + 1:index + 9]
        if rest and not _keyish(rest):
            continue   # "Đáp án: C" inside a question
        if rest or any(_keyish(line.text) for line in following) or _plausible_key(following):
            return lines[:index], lines[index:]
    cut = len(lines)
    while cut > first_question + 1 and _keyish(lines[cut - 1].text):
        cut -= 1
    if cut < len(lines) and len(parse_answer_table(lines[cut:])) >= 3:
        return lines[:cut], lines[cut:]
    return lines, []


# -------------------------------------------------------------------------------------------------- the parser

def _new_block(number, section, kind_hint, label):
    return {'num': number, 'section': section, 'kind_hint': kind_hint, 'stem': [], 'options': [], 'answer': None,
            'explanation': [], 'mode': 'stem', 'label_style': label}


def split_questions(lines):
    """Cut the lines into question blocks (see _new_block); text outside any question is ignored."""
    uses_cau = any(CAU_RE.match(line.text) for line in lines)
    blocks, current = [], None
    section = ''
    kind_hint, pending_hint = None, False
    last_number = None
    for line in lines:
        text = line.text
        if not text.strip():
            continue
        heading = SECTION_RE.match(text)
        if heading and not (QUESTION_RE.match(text) and CAU_RE.match(text)):
            if current is not None:
                blocks.append(current)
                current = None
            section = text.strip()[:60]
            kind_hint = section_kind(text)
            pending_hint = kind_hint is None
            if kind_hint is None:
                ordinal = ROMAN.get(heading.group(1)) or (int(heading.group(1)) if heading.group(1).isdigit() else 0)
                kind_hint = ORDINAL_KIND.get(ordinal)
            continue
        match = QUESTION_RE.match(text)
        number = None
        if match:
            if match.group(1):
                number = int(match.group(1))
            elif not uses_cau and match.group(2):
                bare = int(match.group(2))
                if bare == (1 if last_number is None else last_number + 1):
                    number = bare
        if number is not None:
            if current is not None:
                blocks.append(current)
            last_number = number
            current = _new_block(number, section, kind_hint, None)
            start = match.start(3)
            rest = line.slice(start, len(text))
            _feed_stem_line(current, rest)
            pending_hint = False
            continue
        if current is None:
            if pending_hint and section_kind(text):
                kind_hint = section_kind(text)
                pending_hint = False
            continue
        _feed_line(current, line)
    if current is not None:
        blocks.append(current)
    return blocks


def _feed_stem_line(block, line):
    """The first line of a question: the stem, possibly followed by inline options."""
    found = split_options(line, 0)
    if found and len(found) >= 2:
        stem = line.slice(0, found[0][0])
        if stem.text.strip():
            block['stem'].append(stem)
        _add_options(block, line, found)
    else:
        block['stem'].append(line)


def _add_options(block, line, found):
    for number, (start, end, letter, punct) in enumerate(found):
        stop = found[number + 1][0] if number + 1 < len(found) else len(line.text)
        block['options'].append({'letter': letter, 'punct': punct, 'label': line.slice(start, end),
                                 'text': line.slice(end, stop)})
    block['mode'] = 'option'


def _feed_line(block, line):
    text = line.text
    answer = ANSWER_RE.match(text)
    if answer:
        block['answer'] = (block['answer'] + ' ' if block['answer'] else '') + answer.group(1).strip()
        block['mode'] = 'answer'
        return
    explain = EXPLAIN_RE.match(text)
    if explain:
        block['explanation'].append(explain.group(1).strip())
        block['mode'] = 'explain'
        return
    if block['mode'] in ('stem', 'option'):
        found = split_options(line, len(block['options']))
        if found:
            if found[0][0] > 0 and line.text[:found[0][0]].strip():
                prefix = line.slice(0, found[0][0])
                target = block['options'][-1]['text'] if block['options'] else None
                if target is not None:
                    target.formula = target.formula or prefix.formula
                    target.text += ' ' + prefix.text.strip()
                    target.fmt.extend([0] * (1 + len(prefix.text.strip())))
                else:
                    block['stem'].append(prefix)
            _add_options(block, line, found)
            return
    if block['mode'] == 'stem':
        block['stem'].append(line)
    elif block['mode'] == 'option' and block['options']:
        option = block['options'][-1]['text']
        option.formula = option.formula or line.formula
        option.text += ' ' + text.strip()
        option.fmt.extend([0] * (1 + len(text.strip())))
    elif block['mode'] == 'explain':
        block['explanation'].append(text.strip())
    elif block['mode'] == 'answer' and block['answer'] is not None:
        block['answer'] += ' ' + text.strip()


def _joined(lines):
    return '\n'.join(line.text.strip() for line in lines if line.text.strip()).strip()


def build_question(block, key, info):
    """Turn a block into a question dict (see module docstring)."""
    warn = []
    options = block['options']
    stem_lines = block['stem']
    stem = _joined(stem_lines)
    count = len(options)
    hint = block['kind_hint']
    lower = count and all(o['letter'].islower() for o in options)
    if hint == 'tf4':
        kind = 'tf4'
    elif hint == 'short':
        kind = 'short' if count < 2 else 'single'
    elif hint == 'single':
        kind = 'single' if count else 'short'
    else:
        kind = 'tf4' if (count == 4 and lower and options[0]['punct'] == ')') else 'single' if count else 'short'
    if count == 0 and kind != 'short':
        kind = 'short'
    if count == 0 and hint in ('single', 'tf4'):
        warn.append('no_options')
    if kind == 'single' and count < 2 or kind == 'tf4' and count != 4:
        warn.append('few_options')

    answer_raw = block['answer']
    if answer_raw is None and block['num'] in key:
        answer_raw = key[block['num']]

    opts = [{'text': _joined([o['text']]), 'correct': False} for o in options]
    answers = []
    resolved = False
    if kind in ('single', 'multi'):
        if answer_raw:
            letters, bad = _answer_letters(answer_raw, count)
            if letters:
                for i in letters:
                    opts[i]['correct'] = True
                resolved = True
            if bad or not letters:
                warn.append('bad_answer')
        if not resolved:
            resolved = _apply_marks(options, opts, kind)
        if kind == 'single' and sum(o['correct'] for o in opts) > 1:
            kind = 'multi'
    elif kind == 'tf4':
        if answer_raw:
            truth, partial = _tf_truth(answer_raw)
            if truth:
                for i, value in truth.items():
                    if i < count:
                        opts[i]['correct'] = value
                resolved = True
                if partial:
                    warn.append('partial_answer')
            else:
                warn.append('bad_answer')
        if not resolved:
            resolved = _apply_marks(options, opts, kind)
    else:
        answers = _split_short(answer_raw)
        resolved = bool(answers)
    if not resolved and 'bad_answer' not in warn and 'no_options' not in warn:
        warn.append('no_answer')

    joined_lines = stem_lines + [o['text'] for o in options]
    if any(FIGURE_MARK in line.text for line in joined_lines) or FIGURE_REF_RE.search(stem):
        warn.append('figure')
    if any(line.formula for line in joined_lines) or (
            info.get('pdf') and any(PDF_FORMULA_RE.search(line.text) for line in joined_lines)):
        warn.append('formula')
    return {'num': block['num'], 'kind': kind, 'text': stem, 'options': opts, 'answers': answers,
            'explanation': _joined([Line(x) for x in block['explanation']]), 'points': 1.0, 'tags': [], 'level': 0,
            'section': block['section'], 'warn': list(dict.fromkeys(warn))}


def _apply_marks(options, opts, kind):
    """Correct options from underline / bold / colour; ignored when every option carries the same mark."""
    if not options:
        return False
    for flag in MARK_PRIORITY:
        marked = [i for i, o in enumerate(options)
                  if _marked_fraction(o['label'], flag) == 1.0 or _marked_fraction(o['text'], flag) >= 0.7]
        if marked and len(marked) < len(options):
            for i in marked:
                opts[i]['correct'] = True
            return True
    return False


def parse_plain_lines(lines, info=None):
    info = info or {'pdf': False}
    body, table = split_answer_region(lines)
    key = parse_answer_table(table) if table else {}
    blocks = split_questions(body)
    questions = [build_question(block, key, info) for block in blocks]
    if not questions:
        raise PlainImportError('Không nhận dạng được câu hỏi nào. Mỗi câu cần bắt đầu bằng "Câu 1." hoặc "1." và có '
                               'các phương án A. B. C. D.')
    if len(questions) > MAX_QUESTIONS:
        raise PlainImportError('Tệp có hơn %d câu; hãy tách thành nhiều tệp.' % MAX_QUESTIONS)
    doc_warnings = []
    if info.get('image_pages'):
        doc_warnings.append({'code': 'pdf_images', 'pages': info['image_pages'][:20]})
    if table and not key:
        doc_warnings.append({'code': 'key_unreadable'})
    return {'questions': questions, 'doc_warnings': doc_warnings, 'has_key': bool(key)}


def parse_plain_file(name, data):
    lines, info = file_to_lines(name, data)
    result = parse_plain_lines(lines, info)
    result['format'] = 'PDF' if (name or '').lower().endswith('.pdf') else 'Word' if (name or '').lower().endswith(
        '.docx') else 'Text'
    return result


def parse_plain_text(text):
    """Convenience for tests and pasted text."""
    return parse_plain_lines([Line(unicodedata.normalize('NFC', raw)) for raw in text.splitlines()])
