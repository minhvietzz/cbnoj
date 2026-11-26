"""Background job behind the MCP tool `problem_generate_tests` (see judge/utils/test_gen/)."""
import logging

from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from django.contrib.auth.models import User
from django.core.cache import cache

from judge.models import Problem
from judge.utils.test_gen import store
from judge.utils.test_gen.job import JobError, run_job

__all__ = ['generate_problem_tests', 'gen_job_key', 'gen_lock_key', 'GEN_STATE_TTL', 'GEN_LOCK_TTL']

logger = logging.getLogger('judge.mcp')
GEN_STATE_TTL = 3600
GEN_LOCK_TTL = 300      # a crashed job cannot block the site for longer than this


def gen_job_key(job_id):
    return 'mcp:gen:job:%s' % job_id


def gen_lock_key():
    return 'mcp:gen:lock'


def _set(job_id, **changes):
    state = cache.get(gen_job_key(job_id)) or {}
    state.update(changes)
    cache.set(gen_job_key(job_id), state, GEN_STATE_TTL)


def _fail(job_id, code, message):
    retry = ('solution_failed', 'brute_failed', 'crosscheck_mismatch', 'compile_error', 'busy', 'runner')
    _set(job_id, state='failed', code=code, message=message, can_generate=code in retry)


def _log(message, *args):
    try:
        from judge.mcp import audit
        audit.log_event(message, *args)
    except Exception:
        logger.exception('audit log failed')


@shared_task(ignore_result=True, soft_time_limit=170, time_limit=200)
def generate_problem_tests(job_id, user_id, code, spec, solution, brute, checker, precision):
    _set(job_id, state='running', stage='starting')
    try:
        user = User.objects.get(id=user_id, is_active=True)
        problem = Problem.objects.get(code=code)
        # permissions may have changed since the request was accepted
        if not problem.is_editable_by(user):
            return _fail(job_id, 'forbidden', 'Bạn không còn quyền sửa bài này.')
        try:
            store.check_tests_writable(problem)
        except store.StoreError as e:
            return _fail(job_id, 'store', str(e))
        cases = run_job(spec, solution, brute, checker, precision, float(problem.time_limit), int(problem.memory_limit),
                        progress=lambda stage: _set(job_id, stage=stage))
        _set(job_id, stage='writing')
        try:
            data = store.write_tests(problem, cases, checker, precision)
        except store.StoreError as e:
            return _fail(job_id, 'store', str(e))
        _set(job_id, state='done', stage='done', result={
            'test_count': len(cases), 'total_points': sum(c[2] for c in cases), 'checker': checker,
            'zip_bytes': data.zipfile_size, 'input_bytes': sum(len(c[0]) for c in cases),
            'output_bytes': sum(len(c[1]) for c in cases)})
        _log('gen job %s ok: user=%s problem=%s tests=%d', job_id, user_id, code, len(cases))
    except JobError as e:
        _fail(job_id, e.code, e.message)
        _log('gen job %s failed: user=%s problem=%s code=%s', job_id, user_id, code, e.code)
    except SoftTimeLimitExceeded:
        _fail(job_id, 'runner', 'Quá thời gian cho phép của một lần sinh test.')
        _log('gen job %s timed out: user=%s problem=%s', job_id, user_id, code)
    except Exception:
        logger.exception('gen job %s crashed', job_id)
        _fail(job_id, 'internal', 'Lỗi hệ thống khi sinh test; quản trị viên có thể xem nhật ký.')
    finally:
        if cache.get(gen_lock_key()) == job_id:
            cache.delete(gen_lock_key())
