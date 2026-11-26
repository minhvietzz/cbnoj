# flake8: noqa: E501  (long Vietnamese messages)
"""Spec validation and input generation. Pure Python, deterministic for a given seed, no user code is executed."""
import random
import re
import string
import time
from math import isqrt

from judge.utils.test_gen.expr import Expr, SpecError

NAME_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_]{0,15}$')
RESERVED_NAMES = {'min', 'max'}
ALPHABETS = {
    'lower': string.ascii_lowercase, 'upper': string.ascii_uppercase, 'digits': string.digits,
    'letters': string.ascii_letters, 'alnum': string.ascii_letters + string.digits, 'binary': '01',
}
MAX_VALUE = 10 ** 18


class Limits:
    max_tests = 30
    max_groups = 10
    max_blocks = 50
    max_depth = 2
    max_elements = 1000000           # numbers/characters/edges one test may contain
    max_test_bytes = 4 * 1024 * 1024
    max_total_bytes = 16 * 1024 * 1024
    max_lines = 1000000

    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            if not hasattr(self, key):
                raise TypeError(key)
            setattr(self, key, value)


# ---------------------------------------------------------------------------------------------------------------------
# Compilation (validation) of the spec
# ---------------------------------------------------------------------------------------------------------------------

BLOCK_KEYS = {
    'int': {'name', 'min', 'max'},
    'ints': {'items'},
    'array': {'len', 'min', 'max', 'distinct', 'sorted', 'bias', 'layout'},
    'permutation': {'len', 'layout'},
    'string': {'len', 'alphabet'},
    'matrix': {'rows', 'cols', 'min', 'max'},
    'tree': {'n', 'shape', 'weight'},
    'graph': {'n', 'm', 'connected', 'directed', 'weight'},
    'queries': {'count', 'fields', 'sorted_pair'},
    'repeat': {'count', 'body'},
}


class _Compiler:
    def __init__(self, limits):
        self.limits = limits
        self.free = set()       # names the groups must provide as parameters
        self.blocks = 0

    def expr(self, raw, where, defined):
        e = Expr(raw, where)
        self.free |= e.names - defined
        return e

    def need(self, raw, key, where):
        if key not in raw:
            raise SpecError('%s: thiếu "%s".' % (where, key))
        return raw[key]

    def flag(self, raw, key, where, default=False):
        value = raw.get(key, default)
        if not isinstance(value, bool):
            raise SpecError('%s: "%s" phải là true hoặc false.' % (where, key))
        return value

    def choice(self, raw, key, options, where, default):
        value = raw.get(key, default)
        if value not in options:
            raise SpecError('%s: "%s" phải là một trong: %s.' % (where, key, ', '.join(options)))
        return value

    def name(self, raw, where):
        name = raw.get('name')
        if name is None:
            return None
        if not isinstance(name, str) or not NAME_RE.match(name) or name in RESERVED_NAMES:
            raise SpecError('%s: tên biến "%s" không hợp lệ (chữ, số, gạch dưới, bắt đầu bằng chữ, tối đa 16 ký tự).' % (where, name))
        return name

    def blocks_list(self, raw_blocks, where, defined, depth):
        if not isinstance(raw_blocks, list) or not raw_blocks:
            raise SpecError('%s: cần một danh sách khối không rỗng.' % where)
        return [self.block(raw, '%s[%d]' % (where, i + 1), defined, depth) for i, raw in enumerate(raw_blocks)]

    def block(self, raw, where, defined, depth):
        self.blocks += 1
        if self.blocks > self.limits.max_blocks:
            raise SpecError('Quá %d khối trong spec.' % self.limits.max_blocks)
        if not isinstance(raw, dict) or raw.get('type') not in BLOCK_KEYS:
            raise SpecError('%s: cần {"type": ...} với type thuộc: %s.' % (where, ', '.join(BLOCK_KEYS)))
        kind = raw['type']
        where = '%s (%s)' % (where, kind)
        extra = set(raw) - BLOCK_KEYS[kind] - {'type'}
        if extra:
            raise SpecError('%s: khóa không hợp lệ %s; cho phép: %s.' % (where, sorted(extra), sorted(BLOCK_KEYS[kind])))
        node = {'t': kind, 'where': where}
        e = lambda key: self.expr(self.need(raw, key, where), '%s.%s' % (where, key), defined)  # noqa: E731
        if kind == 'int':
            node.update(min=e('min'), max=e('max'), name=self.name(raw, where))
            if node['name']:
                defined.add(node['name'])
        elif kind == 'ints':
            items = self.need(raw, 'items', where)
            if not isinstance(items, list) or not 1 <= len(items) <= 8:
                raise SpecError('%s: "items" là danh sách 1-8 phần tử {"min","max","name"?}.' % where)
            node['items'] = []
            for i, item in enumerate(items):
                w = '%s.items[%d]' % (where, i + 1)
                if not isinstance(item, dict) or set(item) - {'name', 'min', 'max'}:
                    raise SpecError('%s: cần {"min","max","name"?}.' % w)
                entry = {'min': self.expr(self.need(item, 'min', w), w + '.min', defined),
                         'max': self.expr(self.need(item, 'max', w), w + '.max', defined), 'name': self.name(item, w)}
                node['items'].append(entry)
                if entry['name']:
                    defined.add(entry['name'])
        elif kind == 'array':
            node.update(len=e('len'), min=e('min'), max=e('max'), distinct=self.flag(raw, 'distinct', where),
                        sorted=self.choice(raw, 'sorted', ('none', 'asc', 'desc'), where, 'none'),
                        bias=self.choice(raw, 'bias', ('random', 'min', 'max', 'extreme'), where, 'random'),
                        layout=self.choice(raw, 'layout', ('line', 'column'), where, 'line'))
            if node['distinct'] and node['bias'] != 'random':
                raise SpecError('%s: distinct=true chỉ dùng được với bias="random".' % where)
        elif kind == 'permutation':
            node.update(len=e('len'), layout=self.choice(raw, 'layout', ('line', 'column'), where, 'line'))
        elif kind == 'string':
            alphabet = raw.get('alphabet', 'lower')
            if alphabet in ALPHABETS:
                alphabet = ALPHABETS[alphabet]
            elif not (isinstance(alphabet, str) and 1 <= len(alphabet) <= 64 and alphabet.isprintable() and not any(c.isspace() for c in alphabet)):
                raise SpecError('%s: "alphabet" là %s hoặc một chuỗi 1-64 ký tự in được, không có khoảng trắng.' % (where, '/'.join(ALPHABETS)))
            node.update(len=e('len'), alphabet=alphabet)
        elif kind == 'matrix':
            node.update(rows=e('rows'), cols=e('cols'), min=e('min'), max=e('max'))
        elif kind == 'tree':
            node.update(n=e('n'), shape=self.choice(raw, 'shape', ('random', 'path', 'star', 'binary'), where, 'random'),
                        weight=self.weight(raw, where, defined))
        elif kind == 'graph':
            node.update(n=e('n'), m=e('m'), connected=self.flag(raw, 'connected', where), directed=self.flag(raw, 'directed', where),
                        weight=self.weight(raw, where, defined))
        elif kind == 'queries':
            fields = self.need(raw, 'fields', where)
            if not isinstance(fields, list) or not 1 <= len(fields) <= 8:
                raise SpecError('%s: "fields" là danh sách 1-8 phần tử.' % where)
            node['count'] = e('count')
            node['fields'] = []
            for i, field in enumerate(fields):
                w = '%s.fields[%d]' % (where, i + 1)
                if isinstance(field, dict) and set(field) == {'choice'}:
                    ch = field['choice']
                    if not isinstance(ch, list) or not 1 <= len(ch) <= 20 or not all(isinstance(c, int) and not isinstance(c, bool) and abs(c) <= MAX_VALUE for c in ch):
                        raise SpecError('%s: "choice" là danh sách 1-20 số nguyên.' % w)
                    node['fields'].append({'choice': list(ch)})
                elif isinstance(field, dict) and set(field) == {'min', 'max'}:
                    node['fields'].append({'min': self.expr(field['min'], w + '.min', defined), 'max': self.expr(field['max'], w + '.max', defined)})
                else:
                    raise SpecError('%s: cần {"min","max"} hoặc {"choice":[...]}.' % w)
            node['sorted_pair'] = self.flag(raw, 'sorted_pair', where)
            if node['sorted_pair'] and len(node['fields']) < 2:
                raise SpecError('%s: sorted_pair cần ít nhất 2 trường.' % where)
        elif kind == 'repeat':
            if depth >= self.limits.max_depth:
                raise SpecError('%s: lồng "repeat" tối đa %d cấp.' % (where, self.limits.max_depth))
            node['count'] = e('count')
            node['body'] = self.blocks_list(self.need(raw, 'body', where), where + '.body', set(defined), depth + 1)
        return node

    def weight(self, raw, where, defined):
        weight = raw.get('weight')
        if weight is None:
            return None
        if not isinstance(weight, list) or len(weight) != 2:
            raise SpecError('%s: "weight" là [min, max].' % where)
        return [self.expr(weight[0], where + '.weight[1]', defined), self.expr(weight[1], where + '.weight[2]', defined)]


def validate_spec(spec, limits=None):
    """Check the spec and return the compiled form. Raises SpecError with a Vietnamese message."""
    limits = limits or Limits()
    if not isinstance(spec, dict) or set(spec) - {'seed', 'lines', 'groups'}:
        raise SpecError('spec phải là {"seed"?, "lines": [...], "groups": [...]}.')
    seed = spec.get('seed', 1)
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise SpecError('seed phải là số nguyên.')
    compiler = _Compiler(limits)
    blocks = compiler.blocks_list(spec.get('lines'), 'lines', set(), 0)
    groups = spec.get('groups')
    if not isinstance(groups, list) or not 1 <= len(groups) <= limits.max_groups:
        raise SpecError('"groups" là danh sách 1-%d nhóm test.' % limits.max_groups)
    out, total, points_given = [], 0, []
    for i, group in enumerate(groups, 1):
        where = 'groups[%d]' % i
        if not isinstance(group, dict) or set(group) - {'name', 'count', 'params', 'small', 'points'}:
            raise SpecError('%s: cần {"name","count","params","small"?,"points"?}.' % where)
        count = group.get('count')
        if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= limits.max_tests:
            raise SpecError('%s: "count" là số nguyên từ 1 đến %d.' % (where, limits.max_tests))
        total += count
        params = group.get('params', {})
        if not isinstance(params, dict):
            raise SpecError('%s: "params" là {tên: số hoặc [min, max]}.' % where)
        clean = {}
        for key, value in params.items():
            if not isinstance(key, str) or not NAME_RE.match(key) or key in RESERVED_NAMES:
                raise SpecError('%s: tên tham số "%s" không hợp lệ.' % (where, key))
            if isinstance(value, list) and len(value) == 2 and all(_is_int(v) for v in value):
                if value[0] > value[1]:
                    raise SpecError('%s: tham số "%s" có min > max.' % (where, key))
                clean[key] = (value[0], value[1])
            elif _is_int(value):
                clean[key] = (value, value)
            else:
                raise SpecError('%s: tham số "%s" phải là số nguyên (|giá trị| ≤ 10^18) hoặc [min, max].' % (where, key))
        missing = compiler.free - set(clean)
        if missing:
            raise SpecError('%s: thiếu tham số %s mà các khối đang dùng.' % (where, ', '.join(sorted(missing))))
        points = group.get('points')
        if points is not None and (isinstance(points, bool) or not isinstance(points, int) or points < 0):
            raise SpecError('%s: "points" là số nguyên không âm.' % where)
        points_given.append(points is not None)
        small = group.get('small', False)
        if not isinstance(small, bool):
            raise SpecError('%s: "small" là true hoặc false.' % where)
        out.append({'name': str(group.get('name') or 'nhóm %d' % i)[:40], 'count': count, 'params': clean, 'small': small, 'points': points})
    if total > limits.max_tests:
        raise SpecError('Tổng số test là %d, vượt giới hạn %d.' % (total, limits.max_tests))
    if any(points_given) and not all(points_given):
        raise SpecError('Hoặc nhóm nào cũng có "points", hoặc không nhóm nào có (khi đó chia đều 100 điểm).')
    if any(points_given) and sum(g['points'] for g in out) <= 0:
        raise SpecError('Tổng điểm các nhóm phải lớn hơn 0.')
    return {'seed': seed, 'blocks': blocks, 'groups': out, 'limits': limits}


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool) and abs(value) <= MAX_VALUE


# ---------------------------------------------------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------------------------------------------------

class _Overtime(Exception):
    """Raised inside a preview when its time budget is spent; the lines produced so far are kept."""


class _Emitter:
    def __init__(self, rng, env, limits, deadline=None):
        self.rng, self.env, self.limits, self.deadline = rng, env, limits, deadline
        self.lines, self.elements, self.bytes = [], 0, 0

    def val(self, expr):
        return expr.eval(self.env)

    def bounds(self, lo_expr, hi_expr, where):
        lo, hi = self.val(lo_expr), self.val(hi_expr)
        if lo > hi:
            raise SpecError('%s: min (%d) lớn hơn max (%d) với tham số của test này.' % (where, lo, hi))
        if abs(lo) > MAX_VALUE or abs(hi) > MAX_VALUE:
            raise SpecError('%s: giá trị vượt 10^18.' % where)
        return lo, hi

    def count(self, expr, where, upper=None):
        n = self.val(expr)
        if n < 0 or (upper is not None and n > upper):
            raise SpecError('%s: số lượng %d không hợp lệ (cần 0..%d).' % (where, n, upper if upper is not None else self.limits.max_elements))
        self.take(n, where)
        return n

    def take(self, k, where):
        self.elements += k
        if self.elements > self.limits.max_elements:
            raise SpecError('%s: test vượt %d phần tử cho phép (số, ký tự hay cạnh).' % (where, self.limits.max_elements), 'too_big')

    def line(self, text):
        self.bytes += len(text) + 1
        if self.bytes > self.limits.max_test_bytes:
            raise SpecError('Một test vượt %d MB.' % (self.limits.max_test_bytes // (1024 * 1024)), 'too_big')
        self.lines.append(text)
        count = len(self.lines)
        if count > self.limits.max_lines:
            raise SpecError('Một test vượt %d dòng.' % self.limits.max_lines, 'too_big')
        if self.deadline is not None and count % 2048 == 0 and time.monotonic() > self.deadline:
            raise _Overtime()


def _emit_blocks(E, blocks):
    for node in blocks:
        _EMIT[node['t']](E, node)


def _e_int(E, node):
    lo, hi = E.bounds(node['min'], node['max'], node['where'])
    E.take(1, node['where'])
    v = E.rng.randint(lo, hi)
    if node['name']:
        E.env[node['name']] = v
    E.line(str(v))


def _e_ints(E, node):
    values = []
    for item in node['items']:
        lo, hi = E.bounds(item['min'], item['max'], node['where'])
        v = E.rng.randint(lo, hi)
        if item['name']:
            E.env[item['name']] = v
        values.append(v)
    E.take(len(values), node['where'])
    E.line(' '.join(map(str, values)))


def _put_list(E, values, layout):
    if layout == 'column':
        for v in values:
            E.line(str(v))
    else:
        E.line(' '.join(map(str, values)))


def _e_array(E, node):
    n = E.count(node['len'], node['where'])
    lo, hi = E.bounds(node['min'], node['max'], node['where'])
    rng = E.rng
    if node['distinct']:
        if hi - lo + 1 < n:
            raise SpecError('%s: không đủ %d giá trị khác nhau trong [%d, %d].' % (node['where'], n, lo, hi))
        values = rng.sample(range(lo, hi + 1), n)
    elif node['bias'] == 'min':
        values = [lo] * n
    elif node['bias'] == 'max':
        values = [hi] * n
    elif node['bias'] == 'extreme':
        values = [rng.choice((lo, hi)) for _ in range(n)]
    else:
        values = [rng.randint(lo, hi) for _ in range(n)]
    if node['sorted'] != 'none':
        values.sort(reverse=node['sorted'] == 'desc')
    _put_list(E, values, node['layout'])


def _e_permutation(E, node):
    n = E.count(node['len'], node['where'])
    values = list(range(1, n + 1))
    E.rng.shuffle(values)
    _put_list(E, values, node['layout'])


def _e_string(E, node):
    n = E.count(node['len'], node['where'])
    E.line(''.join(E.rng.choices(node['alphabet'], k=n)))


def _e_matrix(E, node):
    rows = E.val(node['rows'])
    cols = E.val(node['cols'])
    if rows < 0 or cols < 0:
        raise SpecError('%s: số hàng/cột không âm.' % node['where'])
    E.take(rows * cols, node['where'])
    lo, hi = E.bounds(node['min'], node['max'], node['where'])
    for _ in range(rows):
        E.line(' '.join(str(E.rng.randint(lo, hi)) for _ in range(cols)))


def _weight(E, node):
    if node['weight'] is None:
        return None
    return E.bounds(node['weight'][0], node['weight'][1], node['where'])


def _emit_edges(E, edges, weight, undirected):
    rng = E.rng
    rng.shuffle(edges)
    for u, v in edges:
        if undirected and rng.random() < 0.5:
            u, v = v, u
        if weight is None:
            E.line('%d %d' % (u, v))
        else:
            E.line('%d %d %d' % (u, v, rng.randint(*weight)))


def _tree_edges(rng, n, shape):
    perm = list(range(1, n + 1))
    rng.shuffle(perm)
    edges = []
    for i in range(1, n):
        if shape == 'path':
            parent = perm[i - 1]
        elif shape == 'star':
            parent = perm[0]
        elif shape == 'binary':
            parent = perm[(i - 1) // 2]
        else:
            parent = perm[rng.randrange(i)]
        edges.append((parent, perm[i]))
    return edges


def _e_tree(E, node):
    n = E.count(node['n'], node['where'])
    if n < 1:
        raise SpecError('%s: cây cần n ≥ 1.' % node['where'])
    E.take(n, node['where'])
    weight = _weight(E, node)
    _emit_edges(E, _tree_edges(E.rng, n, node['shape']), weight, True)


def _pair_from_index(k, n, directed):
    if directed:
        u, v = divmod(k, n - 1)
        return u + 1, (v + 1 if v < u else v + 2)
    i = ((2 * n - 1) - isqrt((2 * n - 1) ** 2 - 8 * k)) // 2
    while i * (2 * n - i - 1) // 2 > k:
        i -= 1
    while (i + 1) * (2 * n - i - 2) // 2 <= k:
        i += 1
    start = i * (2 * n - i - 1) // 2
    return i + 1, i + 2 + (k - start)


def _e_graph(E, node):
    n = E.count(node['n'], node['where'])
    m = E.count(node['m'], node['where'])
    directed, connected = node['directed'], node['connected']
    where = node['where']
    if n < 1:
        raise SpecError('%s: đồ thị cần n ≥ 1.' % where)
    pairs = n * (n - 1) if directed else n * (n - 1) // 2
    if m > pairs:
        raise SpecError('%s: m=%d vượt số cạnh tối đa %d của đồ thị đơn với n=%d.' % (where, m, pairs, n))
    if connected and m < n - 1:
        raise SpecError('%s: đồ thị liên thông cần m ≥ n-1 (n=%d, m=%d).' % (where, n, m))
    weight = _weight(E, node)
    rng = E.rng

    def key(u, v):
        return (u, v) if directed else ((u, v) if u < v else (v, u))

    edges = {}
    if connected:
        for u, v in _tree_edges(rng, n, 'random'):
            if directed and rng.random() < 0.5:
                u, v = v, u
            edges[key(u, v)] = (u, v)
    need = m - len(edges)
    if need > 0:
        if pairs <= 4 * m + 16:
            existing = set(edges)
            pool = [key(*_pair_from_index(k, n, directed)) for k in range(pairs)]
            pool = [p for p in pool if p not in existing]
            for p in rng.sample(pool, need):
                edges[p] = p
        else:
            while need > 0:
                u, v = rng.randint(1, n), rng.randint(1, n)
                if u == v:
                    continue
                k = key(u, v)
                if k not in edges:
                    edges[k] = (u, v) if directed else k
                    need -= 1
    _emit_edges(E, list(edges.values()), weight, not directed)


def _e_queries(E, node):
    count = E.count(node['count'], node['where'])
    E.take(count * (len(node['fields']) - 1), node['where'])
    fixed = []
    for field in node['fields']:
        fixed.append(None if 'choice' in field else E.bounds(field['min'], field['max'], node['where']))
    for _ in range(count):
        values = [E.rng.choice(f['choice']) if b is None else E.rng.randint(*b) for f, b in zip(node['fields'], fixed)]
        if node['sorted_pair'] and values[0] > values[1]:
            values[0], values[1] = values[1], values[0]
        E.line(' '.join(map(str, values)))


def _e_repeat(E, node):
    count = E.count(node['count'], node['where'], upper=100000)
    outer = dict(E.env)
    for _ in range(count):
        E.env = dict(outer)
        _emit_blocks(E, node['body'])
    E.env = outer


_EMIT = {
    'int': _e_int, 'ints': _e_ints, 'array': _e_array, 'permutation': _e_permutation, 'string': _e_string,
    'matrix': _e_matrix, 'tree': _e_tree, 'graph': _e_graph, 'queries': _e_queries, 'repeat': _e_repeat,
}


def _generate_one(compiled, group_index, test_index, deadline=None):
    """(text, complete). `complete` is False only when `deadline` cut the generation short."""
    group = compiled['groups'][group_index]
    rng = random.Random('%s:%d:%d' % (compiled['seed'], group_index, test_index))
    env = {key: rng.randint(lo, hi) for key, (lo, hi) in sorted(group['params'].items())}
    E = _Emitter(rng, env, compiled['limits'], deadline)
    try:
        _emit_blocks(E, compiled['blocks'])
    except _Overtime:
        return '\n'.join(E.lines) + '\n', False
    return '\n'.join(E.lines) + '\n', True


def assign_points(compiled):
    """Points per test, in test order: group points split evenly over the group, or 100 split over all tests."""
    groups = compiled['groups']
    if groups[0]['points'] is not None:
        result = []
        for g in groups:
            base = g['points'] // g['count']
            result += [base] * (g['count'] - 1) + [g['points'] - base * (g['count'] - 1)]
        return result
    total = sum(g['count'] for g in groups)
    base = 100 // total
    return [base] * (total - 1) + [100 - base * (total - 1)]


def generate_all(compiled):
    """List of {name, group, small, input, points} for every test (raises SpecError)."""
    limits = compiled['limits']
    tests, total = [], 0
    for gi, group in enumerate(compiled['groups']):
        for ti in range(group['count']):
            text = _generate_one(compiled, gi, ti)[0]
            total += len(text)
            if total > limits.max_total_bytes:
                raise SpecError('Tổng input vượt %d MB.' % (limits.max_total_bytes // (1024 * 1024)), 'too_big')
            tests.append({'name': '%s #%d' % (group['name'], ti + 1), 'group': gi, 'small': group['small'], 'input': text})
    for test, points in zip(tests, assign_points(compiled)):
        test['points'] = points
    return tests


def generate_preview(compiled, max_chars=400, budget=1.5):
    """First test of every group, cut short, plus its size. `budget` (seconds) bounds the whole preview, which runs
    inside a web worker; a group that does not fit is reported as partial or skipped, never blocks the worker."""
    out, deadline = [], time.monotonic() + budget
    for gi, group in enumerate(compiled['groups']):
        if time.monotonic() > deadline:
            out.append({'group': group['name'], 'tests': group['count'], 'skipped': True,
                        'note': 'Bỏ qua vì xem trước đã hết thời gian cho phép.'})
            continue
        text, complete = _generate_one(compiled, gi, 0, deadline)
        item = {'group': group['name'], 'tests': group['count'], 'input_bytes': len(text), 'lines': text.count('\n'),
                'sample': text[:max_chars] + ('...' if len(text) > max_chars else '')}
        if not complete:
            item['partial'] = True
            item['note'] = 'Test này rất lớn nên xem trước chỉ sinh một phần đầu; kích thước thật lớn hơn số ghi ở đây.'
        out.append(item)
    return out


HELP_TEXT = r"""
CÁCH MÔ TẢ BỘ SINH TEST (spec) — chỉ dùng được cho bài mà đầu vào là các dạng cơ bản bên dưới. Nếu đề không diễn đạt được
bằng các khối này (cần đảm bảo có nghiệm, cấu trúc đặc biệt, nhiều đáp án đúng...), ĐỪNG ép: trả lời người dùng "không sinh
được test tự động" và chỉ để bài ở trạng thái đã tạo, kèm link tải test.

spec = {"seed": 1, "lines": [<khối>...], "groups": [<nhóm>...]}

NHÓM: {"name": "nhỏ", "count": 3, "params": {"n": [1, 5], "maxv": 10}, "small": true, "points": 20}
  - params: tham số để khối dùng; số cố định hoặc [min, max] (chọn ngẫu nhiên cho mỗi test).
  - small=true: nhóm test nhỏ, được dùng để so lời giải mẫu với lời giải vét cạn (brute).
  - points: tổng điểm của nhóm (chia đều cho test trong nhóm). Bỏ qua tất cả thì 100 điểm chia đều.
  - Tổng số test ≤ 30.

BIỂU THỨC (ở chỗ cần số): số nguyên, tên tham số/biến, hoặc biểu thức như "n-1", "2*n", "min(n, 5)", "10**9". Chỉ có + - * // % **, min, max.

KHỐI (mỗi khối in ra một hoặc nhiều dòng của file input, theo thứ tự):
  {"type":"int","name":"n","min":1,"max":"N"}                       một số, lưu vào biến n để khối sau dùng
  {"type":"ints","items":[{"name":"n","min":1,"max":100},{"name":"m","min":1,"max":100}]}     vài số trên một dòng
  {"type":"array","len":"n","min":-1000,"max":1000,"distinct":false,"sorted":"none|asc|desc","bias":"random|min|max|extreme","layout":"line|column"}
  {"type":"permutation","len":"n"}                                  hoán vị 1..n
  {"type":"string","len":"n","alphabet":"lower|upper|digits|letters|alnum|binary|<chuỗi ký tự>"}
  {"type":"matrix","rows":"n","cols":"m","min":0,"max":9}
  {"type":"tree","n":"n","shape":"random|path|star|binary","weight":[1,100]}              n-1 dòng "u v [w]"
  {"type":"graph","n":"n","m":"m","connected":true,"directed":false,"weight":[1,100]}    m dòng "u v [w]", đồ thị đơn, không khuyên
  {"type":"queries","count":"q","fields":[{"min":1,"max":"n"},{"min":1,"max":"n"},{"choice":[1,2]}],"sorted_pair":true}   q dòng truy vấn
  {"type":"repeat","count":"t","body":[<khối>...]}                 nhiều bộ test trong một file (t thường được in bằng khối int trước đó)

VÍ DỤ 1 — dòng 1: n; dòng 2: n số nguyên.
{"seed":1,"lines":[{"type":"int","name":"n","min":1,"max":"N"},{"type":"array","len":"n","min":-1000000000,"max":1000000000}],
 "groups":[{"name":"nhỏ","count":4,"params":{"N":[1,5]},"small":true},{"name":"lớn","count":4,"params":{"N":[100000,100000]}}]}

VÍ DỤ 2 — cây n đỉnh có trọng số, q truy vấn đoạn.
{"lines":[{"type":"ints","items":[{"name":"n","min":2,"max":"N"},{"name":"q","min":1,"max":"Q"}]},{"type":"tree","n":"n","weight":[1,1000]},
 {"type":"queries","count":"q","fields":[{"min":1,"max":"n"},{"min":1,"max":"n"}],"sorted_pair":true}],
 "groups":[{"name":"nhỏ","count":3,"params":{"N":[2,8],"Q":5},"small":true},{"name":"lớn","count":5,"params":{"N":[50000,100000],"Q":100000}}]}

VÍ DỤ 3 — nhiều bộ test: t, rồi mỗi bộ gồm n và mảng.
{"lines":[{"type":"int","name":"t","min":1,"max":"T"},{"type":"repeat","count":"t","body":[{"type":"int","name":"n","min":1,"max":"N"},{"type":"array","len":"n","min":1,"max":100}]}],
 "groups":[{"name":"test","count":5,"params":{"T":[1,10],"N":[1,20]},"small":true}]}

VÍ DỤ 4 — đồ thị liên thông: dòng "n m", rồi m cạnh có trọng số.
{"lines":[{"type":"ints","items":[{"name":"n","min":2,"max":"N"},{"name":"m","min":"n-1","max":"min(n*(n-1)//2, 3*n)"}]},
 {"type":"graph","n":"n","m":"m","connected":true,"weight":[1,100]}],
 "groups":[{"name":"nhỏ","count":3,"params":{"N":[2,6]},"small":true},{"name":"lớn","count":3,"params":{"N":[1000,5000]}}]}
"""
