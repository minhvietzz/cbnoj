"""
Server side of the mock exam: heartbeat, violation log and auto-submit.

The browser only reports what it sees (see templates/quiz/proctor.html); counting violations, the deadline and
the decision to auto-submit all happen here.
"""
from datetime import timedelta

from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.http import Http404, JsonResponse
from django.utils import timezone
from django.views.generic import View

from judge.models import QuizAttempt, QuizViolation
from judge.views.quiz import AttemptMixin, attempt_state

__all__ = ['QuizAttemptHeartbeat', 'QuizAttemptEvent', 'record_violation', 'superseded_response']

VALID_KINDS = {kind for kind, _label in QuizViolation.KINDS}
COUNT_GRACE = timedelta(seconds=3)       # leaving fullscreen also hides the tab: that is one violation, not two
EVENT_WINDOW = timedelta(seconds=60)
EVENT_LIMIT = 30                         # events recorded per attempt per window; the rest are dropped
SECOND_SESSION_GAP = timedelta(seconds=60)
HEARTBEAT_MIN_GAP = timedelta(seconds=3)    # the page beats every 15 s; anything faster is not our script


@transaction.atomic
def record_violation(attempt_id, kind, detail=''):
    """
    Store one proctoring event. Only the kinds in QuizViolation.COUNTED count towards `max_violations`, and only
    for strict exams; reaching the limit submits the attempt. Returns (attempt, counted).
    """
    attempt = QuizAttempt.objects.select_for_update().select_related('quiz').get(pk=attempt_id)
    if attempt.finished:
        return attempt, False
    now = timezone.now()
    if attempt.violations.filter(created__gte=now - EVENT_WINDOW).count() >= EVENT_LIMIT:
        return attempt, False
    quiz = attempt.quiz
    counted = False
    if kind in QuizViolation.COUNTED and quiz.proctoring == 'strict':
        counted = not attempt.violations.filter(counted=True, created__gte=now - COUNT_GRACE).exists()
    QuizViolation.objects.create(attempt=attempt, kind=kind, detail=detail[:255], counted=counted)
    if counted:
        attempt.violation_count += 1
        attempt.save(update_fields=['violation_count'])
        if quiz.max_violations and attempt.violation_count >= quiz.max_violations:
            attempt.finish(auto_submitted=True)
    return attempt, counted


def superseded_response(attempt):
    """The request came from a tab that was replaced by a newer page load: lock it and log it (once a minute)."""
    recent = attempt.violations.filter(kind='second_session',
                                       created__gte=timezone.now() - SECOND_SESSION_GAP).exists()
    if not recent:
        attempt, _counted = record_violation(attempt.id, 'second_session', 'Another tab or device took over.')
    return JsonResponse(dict(attempt_state(attempt), status='finished' if attempt.is_finished else 'superseded'),
                        status=409)


class ExamCallMixin(LoginRequiredMixin, AttemptMixin):
    http_method_names = ['post']

    def load_attempt(self):
        self.check_access()
        self.check_seb()
        attempt = self.attempt
        if attempt.user_id != self.request.user.profile.id:
            raise Http404()
        return attempt


class QuizAttemptHeartbeat(ExamCallMixin, View):
    def post(self, request, *args, **kwargs):
        attempt = self.load_attempt()
        if attempt.finish_if_expired() or attempt.is_finished:
            return JsonResponse(attempt_state(attempt))
        if request.POST.get('attempt_token') != attempt.session_key:
            return superseded_response(attempt)
        now = timezone.now()
        # The timestamp lives in the database, so this limit holds across all uwsgi workers.
        if attempt.last_heartbeat and now - attempt.last_heartbeat < HEARTBEAT_MIN_GAP:
            return JsonResponse({'status': 'slow'}, status=429)
        attempt.last_heartbeat = now
        attempt.save(update_fields=['last_heartbeat'])
        return JsonResponse(attempt_state(attempt))


class QuizAttemptEvent(ExamCallMixin, View):
    def post(self, request, *args, **kwargs):
        attempt = self.load_attempt()
        if attempt.finish_if_expired() or attempt.is_finished:
            return JsonResponse(attempt_state(attempt))
        if request.POST.get('attempt_token') != attempt.session_key:
            return JsonResponse(dict(attempt_state(attempt), status='superseded'), status=409)
        kind = request.POST.get('kind', '')
        if kind not in VALID_KINDS:
            return JsonResponse({'status': 'error'}, status=400)
        attempt, counted = record_violation(attempt.id, kind, request.POST.get('detail', ''))
        return JsonResponse(dict(attempt_state(attempt), counted=counted))
