"""Tiny integer expression language for generator specs. Never calls eval(): the text is parsed with `ast`
and only a whitelist of nodes is evaluated."""
import ast

MAX_ABS = 10 ** 30
MAX_TEXT = 80
MAX_NODES = 40
FUNCS = {'min': min, 'max': max}
BINOPS = (ast.Add, ast.Sub, ast.Mult, ast.FloorDiv, ast.Mod, ast.Pow)


class SpecError(ValueError):
    """A problem with the spec; the message is shown (in Vietnamese) to the teacher through the assistant."""

    def __init__(self, message, code='unsupported'):
        super().__init__(message)
        self.message = message
        self.code = code


class Expr:
    __slots__ = ('tree', 'names', 'text')

    def __init__(self, value, where):
        if isinstance(value, bool) or not isinstance(value, (int, str)):
            raise SpecError('%s: cần một số nguyên hoặc biểu thức (ví dụ "n-1"), nhận được %r.' % (where, value))
        text = str(value).strip()
        if not text or len(text) > MAX_TEXT:
            raise SpecError('%s: biểu thức trống hoặc dài quá %d ký tự.' % (where, MAX_TEXT))
        try:
            tree = ast.parse(text, mode='eval')
        except SyntaxError:
            raise SpecError('%s: biểu thức "%s" sai cú pháp.' % (where, text))
        names = set()
        call_funcs = {id(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
        for count, node in enumerate(ast.walk(tree), 1):
            if count > MAX_NODES:
                raise SpecError('%s: biểu thức "%s" quá phức tạp.' % (where, text))
            if isinstance(node, (ast.Expression, ast.operator, ast.unaryop, ast.Load)):
                if isinstance(node, ast.operator) and not isinstance(node, BINOPS):
                    raise SpecError('%s: toán tử không được hỗ trợ trong "%s" (chỉ + - * // %% **).' % (where, text))
                continue
            if isinstance(node, ast.BinOp):
                if isinstance(node.op, ast.Pow) and not (isinstance(node.right, ast.Constant) and
                                                         isinstance(node.right.value, int) and
                                                         0 <= node.right.value <= 18):
                    raise SpecError('%s: số mũ phải là hằng số từ 0 đến 18 trong "%s".' % (where, text))
            elif isinstance(node, ast.UnaryOp):
                if not isinstance(node.op, (ast.USub, ast.UAdd)):
                    raise SpecError('%s: toán tử không được hỗ trợ trong "%s".' % (where, text))
            elif isinstance(node, ast.Constant):
                if isinstance(node.value, bool) or not isinstance(node.value, int):
                    raise SpecError('%s: chỉ dùng số nguyên trong "%s".' % (where, text))
            elif isinstance(node, ast.Name):
                if id(node) in call_funcs:
                    if node.id not in FUNCS:
                        raise SpecError('%s: chỉ có hàm min và max, không có "%s".' % (where, node.id))
                else:
                    names.add(node.id)
            elif isinstance(node, ast.Call):
                if node.keywords or not 1 <= len(node.args) <= 4 or not isinstance(node.func, ast.Name):
                    raise SpecError('%s: dùng min(a, b) hoặc max(a, b) trong "%s".' % (where, text))
            else:
                raise SpecError('%s: "%s" có thành phần không được hỗ trợ.' % (where, text))
        self.tree, self.names, self.text = tree.body, names, text

    def eval(self, env):
        return _ev(self.tree, env, self.text)


def _ev(node, env, text):
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        if node.id not in env:
            raise SpecError('Biểu thức "%s": chưa có biến "%s".' % (text, node.id))
        return env[node.id]
    if isinstance(node, ast.UnaryOp):
        value = _ev(node.operand, env, text)
        return -value if isinstance(node.op, ast.USub) else value
    if isinstance(node, ast.Call):
        return FUNCS[node.func.id](*[_ev(a, env, text) for a in node.args])
    left, right = _ev(node.left, env, text), _ev(node.right, env, text)
    op = node.op
    if isinstance(op, ast.Add):
        value = left + right
    elif isinstance(op, ast.Sub):
        value = left - right
    elif isinstance(op, ast.Mult):
        value = left * right
    elif isinstance(op, ast.Pow):
        value = left ** right
    else:
        if right == 0:
            raise SpecError('Biểu thức "%s": chia cho 0.' % text)
        value = left // right if isinstance(op, ast.FloorDiv) else left % right
    if abs(value) > MAX_ABS:
        raise SpecError('Biểu thức "%s": giá trị quá lớn.' % text)
    return value
