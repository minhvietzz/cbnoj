"""So sánh mã nguồn bài nộp để phát hiện bài giống nhau trong kỳ thi (chạy ngay trên máy chủ, không gửi mã ra ngoài).

Cách làm: tách token bằng pygments, chuẩn hóa (tên -> N, chuỗi -> S, số -> D, bỏ chú thích/#include), rồi tạo "dấu vân tay"
bằng winnowing trên các đoạn K token liên tiếp. Độ giống giữa hai bài = tỉ lệ đoạn chung có trọng số (xem _weight): đoạn mà nhiều bài
cùng có (lời giải chuẩn, đọc/ghi dữ liệu) ít giá trị, đoạn hiếm chỉ hai bài có thì giá trị đầy đủ.
Tín hiệu thứ hai ("literal"): giống cả tên biến, bằng chứng mạnh hơn chỉ giống cấu trúc.
"""
import hashlib
from collections import Counter

from django.conf import settings

K = 7              # số token liên tiếp trong một đoạn
W = 4              # cửa sổ winnowing
MIN_TOKENS = 40    # bài ngắn hơn thì không so (dễ giống ngẫu nhiên)
MAX_SOURCE_LEN = 65536

_lexers = {}


def _lexer(family):
    if family not in _lexers:
        from pygments.lexers import CppLexer, Python3Lexer
        _lexers[family] = CppLexer() if family == 'cpp' else Python3Lexer()
    return _lexers[family]


def lang_family(key):
    """'cpp' cho C/C++, 'py' cho Python, None cho ngôn ngữ chưa hỗ trợ."""
    key = (key or '').upper()
    if key.startswith('PY'):
        return 'py'
    if key.startswith('C') and not key.startswith(('CS', 'COFFEE', 'COBOL', 'CLOJ')):
        return 'cpp'
    return None


def tokenize(src, family, keep_names=False):
    from pygments.token import Comment, Keyword, Name, Number, String, Text
    out = []
    for tok, val in _lexer(family).get_tokens(src[:MAX_SOURCE_LEN]):
        if tok in Comment.Preproc or tok in Comment.PreprocFile or tok in Comment or tok in Text:
            continue
        if tok in Name:
            if keep_names or tok in Name.Builtin or tok in Keyword:
                out.append(val)
            else:
                out.append('N')
        elif tok in String:
            out.append('S')
        elif tok in Number:
            out.append('D')
        else:
            v = val.strip()
            if v:
                out.append(v)
    return out


def _hash(parts):
    return int.from_bytes(hashlib.blake2b(' '.join(parts).encode(), digest_size=6).digest(), 'big')


def fingerprints(tokens):
    """Winnowing. Trả về danh sách băm đã sắp xếp (rỗng nếu bài quá ngắn)."""
    if len(tokens) < MIN_TOKENS:
        return []
    hashes = [_hash(tokens[i:i + K]) for i in range(len(tokens) - K + 1)]
    chosen = set()
    last = None
    for i in range(len(hashes) - W + 1):
        window = hashes[i:i + W]
        m = min(window)
        j = i + window.index(m)
        if last != j:
            chosen.add(m)
            last = j
    return sorted(chosen)


def compute(src, family):
    """(struct_fp, literal_fp, số_token)."""
    toks = tokenize(src, family)
    return fingerprints(toks), fingerprints(tokenize(src, family, keep_names=True)), len(toks)


def containment(a, b):
    a, b = set(a), set(b)
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def _weight(df):
    """Đoạn chỉ hai bài có (chính cặp đang xét) hoặc chỉ bài mới có: giá trị đầy đủ; từ 3 bài trở lên cùng có thì giảm dần."""
    return 1.0 if df <= 2 else 2.0 / df


def compare_new(new_struct, new_literal, others):
    """So một bài mới với các bài khác cùng bài tập.

    others: {khóa: (struct_fp, literal_fp)}. Trả về danh sách
    (khóa, điểm_cấu_trúc, điểm_tên_biến, số_đoạn_chung, số_đoạn_hiếm) cho các cặp có điểm cấu trúc >= SIMILARITY_MIN_REPORT.
    """
    new = set(new_struct)
    if not new:
        return []
    sets = {k: set(v[0]) for k, v in others.items() if v[0]}
    n = len(sets) + 1
    df = Counter(new)
    for s in sets.values():
        df.update(s)
    bp = set()
    if n >= 6:
        limit = max(3, 0.5 * n)
        bp = {h for h, c in df.items() if c >= limit}
    new_s = new - bp
    if len(new_s) < 5:
        return []
    wnew = sum(_weight(df[h]) for h in new_s)
    min_report = getattr(settings, 'SIMILARITY_MIN_REPORT', 0.6)
    res = []
    for key, s in sets.items():
        s = s - bp
        if len(s) < 5:
            continue
        shared = new_s & s
        if not shared:
            continue
        score = sum(_weight(df[h]) for h in shared) / min(wnew, sum(_weight(df[h]) for h in s))
        if score < min_report:
            continue
        res.append((key, score, containment(new_literal, others[key][1]), len(shared),
                    sum(1 for h in shared if df[h] <= 3)))
    return res


def classify(score, literal):
    """'strong' (rất đáng ngờ), 'review' (cần xem) hoặc None. Ngưỡng chỉnh được trong settings."""
    strong_s = getattr(settings, 'SIMILARITY_STRONG_SCORE', 0.9)
    strong_l = getattr(settings, 'SIMILARITY_STRONG_LITERAL', 0.85)
    review_s = getattr(settings, 'SIMILARITY_REVIEW_SCORE', 0.85)
    review_s2 = getattr(settings, 'SIMILARITY_REVIEW_SCORE_LITERAL', 0.75)
    review_l = getattr(settings, 'SIMILARITY_REVIEW_LITERAL', 0.6)
    if score >= strong_s and literal >= strong_l:
        return 'strong'
    if score >= review_s or (score >= review_s2 and literal >= review_l):
        return 'review'
    return None
