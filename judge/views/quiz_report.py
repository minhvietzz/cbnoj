import csv
from statistics import median

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponse, HttpResponseRedirect, JsonResponse
from django.urls import reverse
from django.utils import timezone
from django.utils.functional import cached_property
from django.utils.translation import gettext as _
from django.views.generic import DetailView, TemplateView, View

from judge.models import Quiz, QuizAttempt, QuizProfileStat
from judge.utils import quiz_stats, xlsx
from judge.utils.views import TitleMixin
from judge.views.course import CourseMixin
from judge.views.quiz import QuizMixin, can_upload

__all__ = ['QuizResults', 'QuizLive', 'QuizResultsAction', 'QuizMe', 'CourseQuizReport']

RECENT_LIMIT = 15
ONLINE_WITHIN = 45          # seconds since the last heartbeat for a candidate to count as online
MAX_EXTRA_MINUTES = 240     # per action
MAX_TOTAL_EXTRA = 600       # per quiz / per attempt


def format_duration(seconds):
    return '%d:%02d:%02d' % (seconds // 3600, seconds // 60 % 60, seconds % 60)


class QuizResults(LoginRequiredMixin, QuizMixin, TitleMixin, TemplateView):
    """Ranking, score distribution, per-question accuracy and violations of one quiz (teachers only)."""
    template_name = 'quiz/results.html'

    def get_title(self):
        return _('Results') + ' — ' + self.quiz.title

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not self.quiz.is_manageable_by(request.user):
            raise PermissionDenied()
        return super().dispatch(request, *args, **kwargs)

    EXPORT_HEADER = ['Rank', 'Username', 'Score', 'Max', 'Score /10', 'Correct', 'Questions', 'Time taken',
                     'Submitted', 'Auto-submitted', 'Violations']

    def get(self, request, *args, **kwargs):
        export = request.GET.get('export')
        if export in ('csv', 'xlsx'):
            return self.export(export, quiz_stats.exam_ranking(self.quiz))   # exports always read fresh data
        return super().get(request, *args, **kwargs)

    def export_rows(self, rows):
        for row in rows:
            a = row['attempt']
            yield [row['rank'], row['user'].user.username, row['score'], row['max'], row['score10'],
                   a.correct_count, a.question_count, format_duration(row['seconds']),
                   a.finished.strftime('%Y-%m-%d %H:%M:%S'), 'yes' if a.auto_submitted else '', a.violation_count]

    def export(self, kind, rows):
        name = '%s-results.%s' % (self.quiz.slug, kind)
        if kind == 'xlsx':
            response = HttpResponse(
                xlsx.build_xlsx(self.EXPORT_HEADER, list(self.export_rows(rows)), self.quiz.title),
                content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        else:
            response = HttpResponse(content_type='text/csv; charset=utf-8')
            response.write('﻿')  # BOM: Excel needs it to read Vietnamese names as UTF-8
            writer = csv.writer(response)
            writer.writerow(self.EXPORT_HEADER)
            writer.writerows(self.export_rows(rows))
        response['Content-Disposition'] = 'attachment; filename="%s"' % name
        return response

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        quiz = self.quiz
        rows = quiz_stats.cached_exam_ranking(quiz, fresh=bool(self.request.GET.get('fresh')))
        for row in rows:
            row['duration'] = format_duration(row['seconds'])
        scores = [r['score10'] for r in rows]
        enrolled = quiz.course.get_students().count() if quiz.course_id else None
        distribution = quiz_stats.score_distribution(rows)
        flagged = list(quiz.attempts.filter(violations__isnull=False).distinct()
                       .select_related('user__user').prefetch_related('violations').order_by('-violation_count'))
        context.update(self.manage_context())
        context.update({
            'rows': rows,
            'summary': {
                'taken': len(rows), 'enrolled': enrolled,
                'avg': round(sum(scores) / len(scores), 2) if scores else None,
                'median': round(median(scores), 2) if scores else None,
                'best': max(scores) if scores else None, 'worst': min(scores) if scores else None,
                'auto_submitted': sum(1 for r in rows if r['attempt'].auto_submitted),
            },
            'distribution': distribution,
            'distribution_max': max((c for _lo, _hi, c in distribution), default=0) or 1,
            'accuracy': quiz_stats.question_accuracy(quiz, rows),
            'flagged': flagged,
            'tab': None,
        })
        return context


class ManagerOnlyMixin(LoginRequiredMixin, QuizMixin):
    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not self.quiz.is_manageable_by(request.user):
            raise PermissionDenied()
        return super().dispatch(request, *args, **kwargs)


class QuizLive(ManagerOnlyMixin, View):
    """JSON feed for the live panel of the results page: who is still writing, how long they have left."""
    http_method_names = ['get']

    def get(self, request, *args, **kwargs):
        quiz = self.quiz
        now = timezone.now()
        rows = []
        for attempt in quiz.attempts.filter(finished__isnull=True).select_related('user__user'):
            if attempt.finish_if_expired():
                continue
            idle = int((now - attempt.last_heartbeat).total_seconds()) if attempt.last_heartbeat else None
            rows.append({
                'id': attempt.id, 'user': attempt.user.user.username, 'seconds_left': attempt.seconds_left,
                'idle': idle, 'online': idle is not None and idle <= ONLINE_WITHIN,
                'violations': attempt.violation_count, 'extra': attempt.extra_minutes,
            })
        rows.sort(key=lambda r: (r['online'], -r['violations'], r['user']))
        started = set(quiz.attempts.values_list('user_id', flat=True))
        enrolled = quiz.course.get_students().exclude(id__in=started).count() if quiz.course_id else 0
        return JsonResponse({
            'phase': quiz.phase(), 'extra_minutes': quiz.extra_minutes, 'in_progress': rows,
            'finished': quiz.attempts.filter(finished__isnull=False).count(), 'not_started': enrolled,
            'results_published': quiz.results_published,
        })


class QuizResultsAction(ManagerOnlyMixin, View):
    """Teacher actions from the results page: more time, submit for someone, cancel, publish results."""
    http_method_names = ['post']

    def post(self, request, *args, **kwargs):
        quiz = self.quiz
        post = request.POST
        action = post.get('action', '')
        minutes = max(0, min(MAX_EXTRA_MINUTES, self.number(post.get('minutes'))))
        ids = [self.number(i) for i in post.getlist('ids')]
        attempts = list(quiz.attempts.filter(id__in=ids).select_related('user__user')) if ids else []
        back = HttpResponseRedirect(reverse('quiz_results', args=(quiz.slug,)) + '?fresh=1')

        if action == 'extend_all':
            if not minutes:
                messages.warning(request, _('Enter how many minutes to add.'))
                return back
            quiz.extra_minutes = min(MAX_TOTAL_EXTRA, quiz.extra_minutes + minutes)
            quiz.save(update_fields=['extra_minutes'])
            reopened = self.reopen(quiz.attempts.filter(auto_submitted=True, invalidated=False, finished__isnull=False)
                                   .select_related('quiz', 'user__user'), only_if_open=True) \
                if post.get('reopen') else 0
            messages.success(request, _('Added %(n)d minutes for everyone.') % {'n': minutes})
            if reopened:
                messages.success(request, _('%(n)d automatically submitted attempts were reopened.') % {'n': reopened})
            return back

        if action in ('publish', 'unpublish'):
            quiz.results_published = action == 'publish'
            quiz.save(update_fields=['results_published'])
            messages.success(request, _('Results published.') if quiz.results_published else _('Results hidden.'))
            return back

        if not attempts:
            messages.warning(request, _('Select at least one attempt first.'))
            return back
        if action == 'extend':
            if not minutes:
                messages.warning(request, _('Enter how many minutes to add.'))
                return back
            for attempt in attempts:
                attempt.extra_minutes = min(MAX_TOTAL_EXTRA, attempt.extra_minutes + minutes)
                attempt.save(update_fields=['extra_minutes'])
            reopened = self.reopen([a for a in attempts if a.finished], only_if_open=True)
            messages.success(request, _('Added %(m)d minutes to %(n)d attempts.') % {'m': minutes, 'n': len(attempts)})
            if reopened:
                messages.success(request, _('%(n)d automatically submitted attempts were reopened.') % {'n': reopened})
        elif action == 'submit':
            done = 0
            for attempt in attempts:
                if not attempt.finished:
                    attempt.finish(auto_submitted=True)
                    done += 1
            messages.success(request, _('%(n)d attempts submitted.') % {'n': done})
        elif action in ('invalidate', 'restore'):
            flag = action == 'invalidate'
            changed = [a for a in attempts if a.invalidated != flag]
            for attempt in changed:
                quiz_stats.set_invalidated(attempt, flag)
            messages.success(request, _('%(n)d attempts updated.') % {'n': len(changed)})
        return back

    @staticmethod
    def number(value):
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def reopen(attempts, only_if_open):
        """Reopen automatically submitted attempts whose (extended) deadline is in the future."""
        count = 0
        for attempt in attempts:
            if not attempt.auto_submitted or attempt.invalidated:
                continue
            deadline = attempt.deadline
            if only_if_open and deadline and deadline <= timezone.now():
                continue
            if quiz_stats.reopen_attempt(attempt):
                count += 1
        return count


class QuizMe(LoginRequiredMixin, TitleMixin, TemplateView):
    """The student's own progress: counts, level, topic strengths and weaknesses, recent attempts."""
    template_name = 'quiz/me.html'

    def get_title(self):
        return _('My progress')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        profile = self.request.user.profile
        stat = QuizProfileStat.objects.filter(user=profile).first()
        topics = quiz_stats.topic_breakdown(profile)
        recent = list(QuizAttempt.objects.filter(user=profile, finished__isnull=False, invalidated=False)
                      .select_related('quiz').order_by('-finished')[:RECENT_LIMIT])
        visible = []
        for attempt in recent:
            attempt.score10 = quiz_stats.score10(attempt.score, attempt.max_score)
            attempt.visible = attempt.quiz.results_visible_to(self.request.user)
            visible.append(attempt)
        exam_history = [a for a in reversed(visible) if a.quiz.is_exam and a.visible]
        context.update({
            'stat': stat, 'topics': [(n, int(round(100 * acc)), c) for n, acc, c in topics],
            'attempts': visible, 'exam_history': exam_history,
            'min_questions': quiz_stats.MIN_QUESTIONS_FOR_LEVEL,
            'can_upload': can_upload(self.request.user), 'tab': 'me',
        })
        return context


class CourseQuizReport(CourseMixin, TitleMixin, DetailView):
    """Mock exams of a course and how its students are doing; students only see their own row."""
    template_name = 'course/quiz_report.html'
    context_object_name = 'course'

    def get_object(self, queryset=None):
        self.check_visible()
        if not self.course.is_accessible_by(self.request.user):
            raise Http404()
        return self.course

    def get_title(self):
        return _('Quizzes') + ' — ' + self.course.name

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(self.get_course_context())
        user = self.request.user
        rows = quiz_stats.course_report(self.course)
        if not context['can_edit']:
            rows = [r for r in rows if r['user'].id == user.profile.id]
        exams = []
        for quiz in Quiz.objects.filter(course=self.course, mode='exam').order_by('-start_time', '-created'):
            if quiz.is_accessible_by(user):
                quiz.current_phase = quiz.phase()
                exams.append(quiz)
        context.update({'rows': rows, 'exams': exams})
        if context['can_edit']:
            trend = [t for t in quiz_stats.course_exam_trend(self.course) if t[2] is not None]
            context['trend'] = trend
            context['heatmap'] = quiz_stats.course_topic_matrix(self.course)
        return context
