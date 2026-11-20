"""
"Chạy thử": run the code from the problem page on the statement's example and a few tests of the user's own.

The code is compiled and run by the run service (/home/vnojsite/runner/runner.py), which uses the judge's sandbox.
This view only checks who may ask, limits how often, and passes the request on.
"""
import json
import urllib.error
import urllib.request

from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.cache import cache
from django.http import Http404, JsonResponse
from django.views.generic import View
from django.views.generic.detail import SingleObjectMixin

from judge.utils.run_service import RUN_LANGUAGES, runner_key
from judge.views.problem import ProblemMixin

__all__ = ['ProblemRun']

MAX_TESTS = 8
MAX_INPUT = 100 * 1024
MAX_SOURCE = 65536
PER_MINUTE = 12
RUN_TIMEOUT = 45


class ProblemRun(LoginRequiredMixin, ProblemMixin, SingleObjectMixin, View):
    http_method_names = ['post']

    def error(self, code, message, status):
        return JsonResponse({'error': code, 'message': message}, status=status)

    def post(self, request, *args, **kwargs):
        if not getattr(settings, 'RUN_ENABLED', True):
            return self.error('disabled', 'Chức năng chạy thử đang tắt.', 503)
        try:
            problem = self.get_object()
        except Http404:
            return self.error('not_found', 'Không tìm thấy bài.', 404)
        try:
            body = json.loads(request.body)
            language = problem.usable_languages.filter(id=int(body['language'])).first()
            source = body['source']
            tests = body['tests']
            if not isinstance(source, str) or not isinstance(tests, list):
                raise ValueError
            inputs = [t['input'] for t in tests]
            if not 0 < len(inputs) <= MAX_TESTS or not all(isinstance(i, str) and len(i.encode()) <= MAX_INPUT
                                                             for i in inputs):
                raise ValueError
        except (ValueError, TypeError, KeyError):
            return self.error('bad_request', 'Dữ liệu gửi lên không hợp lệ.', 400)
        if language is None or language.file_only:
            return self.error('language', 'Ngôn ngữ này không dùng được cho bài này.', 400)
        if language.key not in RUN_LANGUAGES:
            return self.error('unsupported', 'Ngôn ngữ này chưa hỗ trợ chạy thử, bạn vẫn nộp bài bình thường.', 400)
        if not source.strip() or len(source.encode()) > MAX_SOURCE:
            return self.error('source', 'Code trống hoặc quá dài (tối đa 65536 ký tự).', 400)

        # One run at a time per user, and a few per minute.
        uid = request.user.id
        count_key = 'problem-run-count:%d' % uid
        cache.add(count_key, 0, 60)
        if cache.incr(count_key) > PER_MINUTE:
            return self.error('rate', 'Bạn chạy thử quá nhanh, hãy đợi một chút.', 429)
        lock_key = 'problem-run-lock:%d' % uid
        if not cache.add(lock_key, 1, RUN_TIMEOUT):
            return self.error('busy', 'Lần chạy trước của bạn chưa xong.', 429)
        try:
            payload = json.dumps({
                'lang': language.key, 'source': source, 'tests': [{'input': i} for i in inputs],
                'time_limit': problem.time_limit, 'memory_limit': problem.memory_limit,
            }).encode()
            req = urllib.request.Request(
                getattr(settings, 'RUNNER_URL', 'http://127.0.0.1:9777/run'), data=payload,
                headers={'Content-Type': 'application/json', 'X-Runner-Key': runner_key()})
            try:
                with urllib.request.urlopen(req, timeout=RUN_TIMEOUT) as resp:
                    reply = json.load(resp)
            except urllib.error.HTTPError as e:
                if e.code == 503:
                    return self.error('busy', 'Máy chấm đang bận, thử lại sau ít giây.', 503)
                return self.error('runner', 'Không chạy thử được lúc này.', 502)
            except (urllib.error.URLError, OSError, ValueError):
                return self.error('runner', 'Dịch vụ chạy thử chưa sẵn sàng.', 502)
        finally:
            cache.delete(lock_key)
        return JsonResponse(reply)
