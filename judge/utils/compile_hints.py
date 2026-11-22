"""Plain-language hints (in Vietnamese) for the most common compile errors, shown under the compiler output.

The compiler message stays exactly as it is; the hints only help beginners read it. Every hint is a guess about
the usual cause, so they are worded as suggestions.
"""
import re

__all__ = ['compile_hints']

MAX_HINTS = 4

# (regular expression on the normalised message, hint). Order matters: the first matches are shown first.
RULES = [
    (r"(bits/stdc\+\+\.h|iostream|vector|string|algorithm|cmath)[\"']?: No such file or directory",
     'Lỗi này thường do chọn nhầm ngôn ngữ: code C++ nhưng nộp bằng ngôn ngữ C. Hãy chọn C++17 (hoặc C++20) '
     'ở ô ngôn ngữ khi nộp bài.'),
    (r"undefined reference to [`']?main",
     'Chương trình chưa có hàm main(), hoặc hàm main viết sai (phải là int main()).'),
    (r"['\"]?(cin|cout|endl|cerr)['\"]? (was not declared|does not name a type)",
     'Thiếu #include <iostream> hoặc thiếu dòng using namespace std; (hoặc phải viết std::cin, std::cout).'),
    (r"['\"]?(string)['\"]? (was not declared|does not name a type)",
     'Thiếu #include <string> hoặc using namespace std;.'),
    (r"['\"]?(vector|map|set|queue|stack|deque|pair)['\"]? (was not declared|does not name a type)",
     'Thiếu thư viện tương ứng (ví dụ #include <vector>, <map>, <set>...) hoặc using namespace std;.'),
    (r"['\"]?(sort|swap|min|max|reverse|unique|lower_bound|upper_bound)['\"]? (was not declared|"
     r"has not been declared)", 'Thiếu #include <algorithm> hoặc using namespace std;.'),  # noqa: Q000
    (r"['\"]?(printf|scanf|puts|getchar|freopen)['\"]? (was not declared|has not been declared)",
     'Thiếu #include <cstdio> (hoặc <stdio.h>).'),
    (r"was not declared in this scope",  # noqa: Q000
     'Một tên (biến hoặc hàm) được dùng khi chưa khai báo, hoặc viết sai tên. C/C++ phân biệt chữ hoa và chữ thường, '
     'và biến chỉ dùng được trong phạm vi { } nơi nó được khai báo.'),
    (r"expected [\"'‘]?;[\"'’]?|expected ['\"‘]?;['\"’]? before",
     'Thiếu dấu ; ở cuối một câu lệnh. Hãy xem cả dòng ngay trước dòng báo lỗi.'),
    (r"expected declaration before [\"'‘]?\}|expected [\"'‘]?\}[\"'’]? at end of input|expected [\"'‘]?\{",
     'Số dấu ngoặc nhọn { } không khớp (thừa hoặc thiếu một dấu).'),
    (r"expected [\"'‘]?\)[\"'’]?|expected primary-expression|expected [\"'‘]?\([\"'’]?",
     'Thiếu hoặc thừa dấu ngoặc tròn ( ), hoặc viết sai một biểu thức.'),
    (r"stray [\"'‘]?\\\d+|stray [\"'‘]?\\|extended character",
     'Trong code có ký tự lạ, thường do chép từ Word, Zalo hoặc web (nháy cong “ ”, dấu cách đặc biệt). '
     'Hãy gõ lại ký tự đó trực tiếp trong ô soạn thảo.'),
    (r"no matching function for call|no match for [\"'‘]?operator|no match for call",
     'Gọi hàm hoặc dùng toán tử với kiểu dữ liệu hay số lượng tham số không đúng.'),
    (r"invalid conversion from|cannot convert",  # noqa: Q000
     'Gán hoặc truyền giá trị sai kiểu dữ liệu (ví dụ gán chuỗi cho số nguyên).'),
    (r"redefinition of|redeclaration of|conflicting declaration|has already been declared|duplicate (member|symbol)",  # noqa: E501,Q000
     'Một tên bị khai báo hai lần trong cùng phạm vi.'),
    (r"lvalue required as left operand of assignment",  # noqa: Q000
     'Có thể bạn dùng một dấu = ở chỗ cần so sánh (phải viết ==), hoặc gán giá trị vào thứ không gán được.'),
    (r"missing terminating [\"'] character",
     'Thiếu dấu nháy đóng ở một chuỗi hoặc ký tự.'),
    (r"invalid types .* for array subscript",  # noqa: Q000
     'Dùng [ ] với thứ không phải mảng, hoặc chỉ số mảng không phải số nguyên.'),
    (r"request for member .* which is of non-class type",  # noqa: Q000
     'Dùng dấu chấm (.) với biến không phải struct/class (ví dụ một số nguyên).'),
    (r"control reaches end of non-void function",  # noqa: Q000
     'Hàm có kiểu trả về nhưng có đường chạy không return giá trị nào.'),
    (r"[\"'‘]?main[\"'’]? must return [\"'‘]?int",
     'Hàm main phải có kiểu trả về int.'),
    (r"IndentationError|unexpected indent|expected an indented block",  # noqa: Q000
     'Python: thụt lề sai. Các dòng cùng khối phải thụt lề bằng nhau (không trộn Tab và dấu cách).'),
    (r"SyntaxError: (EOL while scanning|unterminated string)",  # noqa: Q000
     'Python: thiếu dấu nháy đóng ở một chuỗi.'),
    (r"SyntaxError: invalid syntax|SyntaxError: expected",  # noqa: Q000
     'Python: sai cú pháp. Kiểm tra dấu hai chấm (:) sau if/for/while/def, dấu ngoặc và dấu nháy của dòng báo lỗi '
     'và dòng ngay trước nó.'),
    (r"is public, should be declared in a file named",  # noqa: Q000
     'Java: lớp public phải đặt tên là Main (hoặc tên mà đề bài yêu cầu).'),
    (r"cannot find symbol",  # noqa: Q000
     'Java: dùng tên chưa khai báo, viết sai tên hoặc thiếu import.'),
    (r"[\"'‘]?;[\"'’]? expected",
     'Java: thiếu dấu ; ở cuối câu lệnh.'),
    (r"Syntax error, [\"'‘]?;[\"'’]? expected|Fatal: Syntax error",
     'Pascal: sai cú pháp, thường là thiếu dấu ; hoặc thiếu begin/end.'),
    (r"Identifier not found",  # noqa: Q000
     'Pascal: dùng tên chưa khai báo hoặc viết sai tên.'),
]
QUOTES = str.maketrans({'\u2018': "'", '\u2019': "'", '\u201c': '"', '\u201d': '"'})
COMPILED = [(re.compile(pattern, re.IGNORECASE), hint) for pattern, hint in RULES]


def compile_hints(message):
    """Return up to MAX_HINTS distinct hints for the given compiler output (an empty list when nothing matches)."""
    if not message:
        return []
    text = re.sub(r'\x1b\[[0-9;]*[A-Za-z]', '', str(message))     # colours added by the compiler
    text = text.translate(QUOTES)                           # ‘ ’ “ ” -> ' so one pattern covers both locales
    hints = []
    for pattern, hint in COMPILED:
        if hint not in hints and pattern.search(text):
            hints.append(hint)
            if len(hints) == MAX_HINTS:
                break
    return hints
