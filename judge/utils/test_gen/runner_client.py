"""Client of the `runner` service (sandboxed execution, see /home/vnojsite/runner/runner.py), endpoint /gen."""
import json
import urllib.error
import urllib.request

from django.conf import settings

from judge.utils.run_service import RUN_LANGUAGES, runner_key

TIMEOUT = 150   # a little more than the 120 s budget of the service


class RunnerError(Exception):
    def __init__(self, message, code='runner'):
        super().__init__(message)
        self.message = message
        self.code = code


def run_solution(language, source, inputs, time_limit, memory_limit_kb):
    """Run `source` on every input in the sandbox. Returns the reply dict of the service:
    {'compile_error': str|None, 'results': [{'status', 'stdout', 'stderr', 'time', 'memory', 'truncated', ...}]}
    The service stops at the first failing test and marks the remaining ones with status SKIP."""
    if language not in RUN_LANGUAGES:
        raise RunnerError('Ngôn ngữ %s chưa hỗ trợ chạy tự động (dùng một trong: %s).' % (
            language, ', '.join(sorted(RUN_LANGUAGES))), 'unsupported')
    payload = json.dumps({'lang': language, 'source': source, 'tests': [{'input': i} for i in inputs],
                          'time_limit': time_limit, 'memory_limit': memory_limit_kb}).encode()
    req = urllib.request.Request(
        getattr(settings, 'RUNNER_GEN_URL', 'http://127.0.0.1:9777/gen'), data=payload,
        headers={'Content-Type': 'application/json', 'X-Runner-Key': runner_key()})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        if e.code == 503:
            raise RunnerError('Máy chạy lời giải đang bận, thử lại sau ít phút.', 'busy')
        if e.code == 404:
            raise RunnerError('Dịch vụ runner chưa hỗ trợ sinh test (cần restart runner).', 'runner')
        raise RunnerError('Dịch vụ chạy lời giải trả lỗi %d.' % e.code)
    except (urllib.error.URLError, OSError, ValueError):
        raise RunnerError('Dịch vụ chạy lời giải chưa sẵn sàng.')
