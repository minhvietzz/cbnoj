# flake8: noqa: E501  (long Vietnamese messages)
"""The whole generation job: spec -> inputs -> reference solution (sandbox) -> optional brute-force cross-check ->
list of (input, output, points). Nothing is written to the database here, so a failure leaves the problem untouched."""
from judge.utils.test_gen.generator import generate_all, validate_spec
from judge.utils.test_gen.runner_client import run_solution, RunnerError

MAX_TIME = 5.0
MAX_MEMORY_KB = 512 * 1024
SHOW = 300


class JobError(Exception):
    """A reason the tests could not be generated. `code` is one of: unsupported, too_big, compile_error,
    solution_failed, brute_failed, crosscheck_mismatch, busy, runner."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code, self.message = code, message


def _clip(text):
    text = text.strip()
    return text if len(text) <= SHOW else text[:SHOW] + '...'


def outputs_match(a, b, checker='standard', precision=6):
    if checker == 'identical':
        return a.rstrip('\n') == b.rstrip('\n')
    ta, tb = a.split(), b.split()
    if len(ta) != len(tb):
        return False
    if checker not in ('floats', 'floatsabs', 'floatsrel'):
        return ta == tb
    eps = 10.0 ** -int(precision)
    for x, y in zip(ta, tb):
        if x == y:
            continue
        try:
            fx, fy = float(x), float(y)
        except ValueError:
            return False
        scale = 1.0 if checker == 'floatsabs' else max(1.0, abs(fx), abs(fy))
        if abs(fx - fy) > eps * scale:
            return False
    return True


def _run(label, solution, inputs, names, time_limit, memory_kb, runner):
    try:
        reply = runner(solution['language'], solution['source'], inputs, time_limit, memory_kb)
    except RunnerError as e:
        raise JobError('busy' if e.code == 'busy' else ('unsupported' if e.code == 'unsupported' else 'runner'), e.message)
    if reply.get('compile_error'):
        raise JobError('compile_error', '%s không biên dịch được:\n%s' % (label, _clip(reply['compile_error'])))
    results = reply.get('results') or []
    if len(results) != len(inputs):
        raise JobError('runner', 'Dịch vụ chạy lời giải trả kết quả không đủ.')
    outputs = []
    for name, res in zip(names, results):
        if res['status'] == 'SKIP':
            raise JobError('runner', 'Hết thời gian chạy tổng của dịch vụ trước khi xong mọi test.')
        if res['status'] != 'OK' or res.get('truncated'):
            why = 'in quá nhiều' if res.get('truncated') and res['status'] == 'OK' else res['status']
            detail = _clip(res.get('stderr') or '')
            raise JobError('solution_failed' if label.startswith('Lời giải mẫu') else 'brute_failed',
                           '%s lỗi ở test "%s": %s%s. (TLE = quá giờ, MLE = quá bộ nhớ, OLE = in quá nhiều, RTE/IR = lỗi lúc chạy.)' % (
                               label, name, why, (' - ' + detail) if detail else ''))
        out = res['stdout']
        if not out.strip():
            raise JobError('solution_failed', '%s không in ra gì ở test "%s" (thường do đọc/ghi file sai hoặc quên in kết quả).' % (label, name))
        outputs.append(out if out.endswith('\n') else out + '\n')
    return outputs


def run_job(raw_spec, solution, brute, checker, precision, time_limit, memory_limit_kb, runner=run_solution,
            progress=lambda stage: None):
    """Returns [(input, output, points)]. Raises JobError."""
    from judge.utils.test_gen.expr import SpecError
    if time_limit > MAX_TIME or memory_limit_kb > MAX_MEMORY_KB:
        raise JobError('unsupported', 'Bài có giới hạn %.1f giây / %d MB, vượt mức sinh test tự động hỗ trợ (%d giây / %d MB).' % (
            time_limit, memory_limit_kb // 1024, MAX_TIME, MAX_MEMORY_KB // 1024))
    try:
        compiled = validate_spec(raw_spec)
        progress('generating')
        tests = generate_all(compiled)
    except SpecError as e:
        raise JobError(e.code, e.message)
    names = [t['name'] for t in tests]
    inputs = [t['input'] for t in tests]
    progress('solution')
    outputs = _run('Lời giải mẫu', solution, inputs, names, time_limit, memory_limit_kb, runner)
    if brute:
        small = [i for i, t in enumerate(tests) if t['small']]
        if not small:
            raise JobError('unsupported', 'Có lời giải vét cạn nhưng không nhóm nào có "small": true để so sánh.')
        progress('crosscheck')
        brute_out = _run('Lời giải vét cạn', brute, [inputs[i] for i in small], [names[i] for i in small],
                         min(max(time_limit * 3, 2.0), MAX_TIME), memory_limit_kb, runner)
        for i, other in zip(small, brute_out):
            if not outputs_match(outputs[i], other, checker, precision):
                raise JobError('crosscheck_mismatch', 'Lời giải mẫu và lời giải vét cạn cho kết quả KHÁC nhau ở test "%s". Input (đầu): %s | mẫu: %s | vét cạn: %s. Không lưu test nào; hãy kiểm tra lại hai lời giải.' % (
                    names[i], _clip(inputs[i]), _clip(outputs[i]), _clip(other)))
    return [(t['input'], out, t['points']) for t, out in zip(tests, outputs)]
