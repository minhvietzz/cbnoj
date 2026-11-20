import csv

from django.contrib import admin, messages
from django.http import HttpResponse
from django.utils.translation import gettext_lazy as _, ngettext

from judge.models import QuizOption, QuizQuestion, QuizViolation
from judge.utils import quiz_stats


class QuizQuestionInline(admin.TabularInline):
    model = QuizQuestion
    extra = 0
    fields = ('order', 'kind', 'section', 'passage', 'text', 'points')
    show_change_link = True


class QuizAdmin(admin.ModelAdmin):
    list_display = ('title', 'slug', 'mode', 'course', 'start_time', 'end_time', 'proctoring', 'is_public',
                    'attempt_total', 'creator', 'created')
    list_filter = ('mode', 'proctoring', 'results_release', 'is_public', 'track', 'course')
    search_fields = ('title', 'slug')
    prepopulated_fields = {'slug': ('title',)}
    raw_id_fields = ('creator',)
    inlines = [QuizQuestionInline]
    actions = ['publish_results', 'hide_results']
    fieldsets = (
        (None, {'fields': ('title', 'slug', 'description', 'creator', 'source_name')}),
        (_('Mode'), {'fields': ('mode', 'course', 'track', 'is_public', 'lesson')}),
        (_('Mock exam'), {'fields': ('start_time', 'end_time', 'time_limit', 'max_attempts', 'questions_per_attempt',
                                     'proctoring',
                                     'max_violations', 'results_release', 'results_published', 'extra_minutes',
                                     'seb_browser_key', 'rules_text')}),
        (_('Behaviour'), {'fields': ('shuffle_questions', 'shuffle_options', 'show_answers')}),
    )

    def get_queryset(self, request):
        from django.db.models import Count, Q
        return super().get_queryset(request).annotate(
            _attempts=Count('attempts', filter=Q(attempts__finished__isnull=False), distinct=True))

    @admin.display(description=_('finished attempts'), ordering='_attempts')
    def attempt_total(self, obj):
        return obj._attempts

    @admin.action(description=_('Publish results (manual release)'))
    def publish_results(self, request, queryset):
        updated = queryset.update(results_published=True)
        self.message_user(request, ngettext('%d quiz published.', '%d quizzes published.', updated) % updated)

    @admin.action(description=_('Hide results again'))
    def hide_results(self, request, queryset):
        updated = queryset.update(results_published=False)
        self.message_user(request, ngettext('%d quiz hidden.', '%d quizzes hidden.', updated) % updated)


class QuizOptionInline(admin.TabularInline):
    model = QuizOption
    extra = 0


class QuizQuestionAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'kind', 'section', 'points')
    list_filter = ('kind',)
    search_fields = ('text', 'quiz__title')
    inlines = [QuizOptionInline]


class BankTagAdmin(admin.ModelAdmin):
    list_display = ('name', 'group')
    list_filter = ('group',)
    search_fields = ('name',)


class BankQuestionAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'kind', 'level', 'creator', 'created')
    list_filter = ('kind', 'level', 'tags')
    search_fields = ('text',)
    raw_id_fields = ('creator',)
    filter_horizontal = ('tags',)
    exclude = ('content_hash',)

    def save_model(self, request, obj, form, change):
        from judge.utils.question_bank import question_hash
        obj.content_hash = question_hash({
            'kind': obj.kind, 'text': obj.text, 'options': obj.options, 'answers': obj.accepted_list()})
        super().save_model(request, obj, form, change)


class QuizViolationInline(admin.TabularInline):
    model = QuizViolation
    extra = 0
    can_delete = False
    fields = ('created', 'kind', 'detail', 'counted')
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False


class QuizAttemptAdmin(admin.ModelAdmin):
    list_display = ('user', 'quiz', 'score_display', 'score10', 'correct_count', 'started', 'finished',
                    'violation_count', 'auto_submitted', 'invalidated')
    list_filter = ('quiz', 'quiz__mode', 'auto_submitted', 'invalidated')
    search_fields = ('user__user__username', 'quiz__title')
    raw_id_fields = ('user', 'quiz')
    date_hierarchy = 'started'
    inlines = [QuizViolationInline]
    actions = ['invalidate_attempts', 'restore_attempts', 'export_csv']
    readonly_fields = ('started', 'seed', 'answers', 'results', 'scores', 'score', 'max_score', 'correct_count',
                       'question_count', 'violation_count', 'last_heartbeat', 'session_key', 'ip', 'user_agent')

    def has_add_permission(self, request):
        return False  # attempts only come from students taking a quiz

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('user__user', 'quiz')

    @admin.display(description=_('score'))
    def score_display(self, obj):
        return '%g/%g' % (obj.score, obj.max_score) if obj.finished else '—'

    @admin.display(description=_('score /10'))
    def score10(self, obj):
        return quiz_stats.score10(obj.score, obj.max_score) if obj.finished else '—'

    @admin.action(description=_('Invalidate selected attempts (leaves rankings; the student may retake)'))
    def invalidate_attempts(self, request, queryset):
        count = 0
        for attempt in queryset.filter(invalidated=False):
            quiz_stats.set_invalidated(attempt, True)
            count += 1
        self.message_user(request, ngettext('%d attempt invalidated.', '%d attempts invalidated.', count) % count,
                          messages.SUCCESS)

    @admin.action(description=_('Restore selected attempts'))
    def restore_attempts(self, request, queryset):
        count = 0
        for attempt in queryset.filter(invalidated=True):
            quiz_stats.set_invalidated(attempt, False)
            count += 1
        self.message_user(request, ngettext('%d attempt restored.', '%d attempts restored.', count) % count,
                          messages.SUCCESS)

    @admin.action(description=_('Export selected attempts as CSV'))
    def export_csv(self, request, queryset):
        response = HttpResponse(content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = 'attachment; filename="quiz-attempts.csv"'
        response.write('﻿')
        writer = csv.writer(response)
        writer.writerow(['Username', 'Quiz', 'Score', 'Max', 'Score /10', 'Started', 'Finished', 'Violations',
                         'Auto-submitted', 'Invalidated', 'IP'])
        for a in queryset.select_related('user__user', 'quiz'):
            writer.writerow([a.user.user.username, a.quiz.title, a.score, a.max_score,
                             quiz_stats.score10(a.score, a.max_score), a.started, a.finished or '',
                             a.violation_count, 'yes' if a.auto_submitted else '', 'yes' if a.invalidated else '',
                             a.ip or ''])
        return response


class QuizProfileStatAdmin(admin.ModelAdmin):
    """Read-only ranking of everyone's quiz activity and level; recomputed by the actions below."""
    list_display = ('user', 'level', 'level_score', 'exams_taken', 'practice_sessions', 'avg_exam_score',
                    'best_exam_score', 'questions_correct', 'questions_answered', 'updated')
    list_filter = ('level',)
    search_fields = ('user__user__username',)
    ordering = ('-level_score',)
    actions = ['recompute']

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('user__user')

    @admin.action(description=_('Recompute statistics of the selected users'))
    def recompute(self, request, queryset):
        users = quiz_stats.rebuild_all(users=[s.user for s in queryset])
        self.message_user(request, ngettext('Statistics of %d user rebuilt.', 'Statistics of %d users rebuilt.',
                                            users) % users, messages.SUCCESS)
