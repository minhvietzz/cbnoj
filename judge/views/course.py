import csv
from collections import defaultdict
from datetime import timedelta

from django.conf import settings
from django import forms
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Max, Min, Q
from django.http import Http404, HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.utils.functional import cached_property
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy as _l
from django.views.generic import DetailView, FormView, ListView, View

from judge.models import ClassAssignment, Classroom, Course, CourseLesson, CourseRole, Problem, RoleInCourse, \
    Submission
from judge.utils import classroom as class_stats
from judge.utils import xlsx
from judge.utils.views import TitleMixin, generic_message

__all__ = ['CourseList', 'CourseDetail', 'CourseLessonDetail', 'CourseLessonRanking', 'CourseLessonAssign',
           'CourseGrades', 'CourseJoin', 'CourseLeave']

COLORS = ('mint', 'sky', 'lilac', 'peach', 'butter', 'pink')


def course_color(course):
    return COLORS[course.id % len(COLORS)]


def lesson_progress(profile, lessons):
    """
    Per-lesson progress of one profile.
    Returns {lesson_id: {'solved', 'total', 'score', 'max', 'percent', 'problems': [...]}}.
    A problem counts as solved on an AC submission; the score is proportional to the best points ever granted.
    """
    problems_by_lesson = defaultdict(list)
    problem_ids = set()
    for lesson in lessons:
        for lp in lesson.lesson_problems.all():
            problems_by_lesson[lesson.id].append(lp)
            problem_ids.add(lp.problem_id)

    best, solved = {}, set()
    if profile is not None and problem_ids:
        for row in (Submission.objects.filter(user=profile, problem_id__in=problem_ids)
                    .values('problem_id').annotate(best=Max('points'))):
            best[row['problem_id']] = row['best'] or 0
        solved = set(Submission.objects.filter(user=profile, problem_id__in=problem_ids, result='AC')
                     .values_list('problem_id', flat=True))

    progress = {}
    for lesson in lessons:
        items, got, maximum, done = [], 0.0, 0, 0
        for lp in problems_by_lesson[lesson.id]:
            full = lp.problem.points or 0
            ratio = 1.0 if lp.problem_id in solved else (min(1.0, best.get(lp.problem_id, 0) / full) if full else 0.0)
            score = lp.points * ratio
            got += score
            maximum += lp.points
            done += lp.problem_id in solved
            items.append({'lp': lp, 'problem': lp.problem, 'solved': lp.problem_id in solved,
                          'tried': lp.problem_id in best and lp.problem_id not in solved,
                          'score': round(score, 1), 'max': lp.points})
        total = len(items)
        progress[lesson.id] = {'solved': done, 'total': total, 'score': round(got, 1), 'max': maximum,
                               'percent': int(round(100 * done / total)) if total else 0,
                               'score_percent': (100.0 * got / maximum) if maximum else 100.0,
                               'problems': items}
    return progress


def apply_locks(lessons, progress, unlock_all):
    """
    Mark each lesson with `locked` and `lock_info` (prerequisite title, required and current percent).
    A lesson is open once its prerequisite has reached the required score; editors are never locked out.
    """
    by_id = {lesson.id: lesson for lesson in lessons}
    for lesson in lessons:
        lesson.locked, lesson.lock_info = False, None
        pre = by_id.get(lesson.prerequisite_id)
        if pre is None:
            continue
        current = progress[pre.id]['score_percent']
        lesson.lock_info = {'lesson': pre, 'required': lesson.prerequisite_percent, 'current': int(current)}
        lesson.locked = current + 1e-9 < lesson.prerequisite_percent and not unlock_all


class CourseMixin(object):
    @cached_property
    def course(self):
        return get_object_or_404(Course, slug=self.kwargs['slug'])

    def get_course_context(self):
        user = self.request.user
        return {
            'course': self.course,
            'course_color': course_color(self.course),
            'can_access': self.course.is_accessible_by(user),
            'can_edit': self.course.is_editable_by(user),
            'can_join': self.course.can_join(user),
            'is_member': user.is_authenticated and self.course.get_role(user.profile) is not None,
            'quiz_enabled': getattr(settings, 'QUIZ_ENABLED', False),
        }

    def check_visible(self):
        if not self.course.is_visible_to(self.request.user):
            raise Http404()


class CourseList(TitleMixin, ListView):
    context_object_name = 'courses'
    template_name = 'course/list.html'
    paginate_by = 12

    def get_title(self):
        return _('Courses')

    @cached_property
    def tab(self):
        user = self.request.user
        tab = self.request.GET.get('tab')
        if tab is None:
            # people who study something land on their own courses
            tab = 'mine' if user.is_authenticated and CourseRole.objects.filter(user=user.profile).exists() else 'all'
        return 'mine' if tab == 'mine' and user.is_authenticated else 'all'

    def get_queryset(self):
        user = self.request.user
        visible = Course.objects.all()
        if self.tab == 'mine':
            visible = visible.filter(roles__user=user.profile)
        elif not user.is_superuser:
            visible = visible.filter(Q(is_public=True) | Q(roles__user=user.profile) |
                                     Q(organization__in=user.profile.organizations.values('id'))) \
                if user.is_authenticated else visible.filter(is_public=True)
        search = self.request.GET.get('search', '').strip()
        if search:
            visible = visible.filter(Q(name__icontains=search) | Q(about__icontains=search))
        # Count members and lessons in a second query so the filters above cannot skew them.
        return Course.objects.filter(id__in=visible.values('id')).select_related('organization').annotate(
            student_count=Count('roles', filter=Q(roles__role=RoleInCourse.STUDENT), distinct=True),
            lesson_count=Count('lessons', filter=Q(lessons__is_visible=True), distinct=True),
        ).order_by('-created', 'name')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        enrolled = {}
        if user.is_authenticated:
            enrolled = dict(CourseRole.objects.filter(user=user.profile).values_list('course_id', 'role'))
        courses = list(context['courses'])
        teachers = defaultdict(list)
        for role in (CourseRole.objects.filter(course__in=courses, role=RoleInCourse.TEACHER)
                     .select_related('user__user')):
            teachers[role.course_id].append(role.user)
        from judge.utils.learning import course_progress_map
        progress = course_progress_map(user.profile, [c for c in courses if c.id in enrolled]) \
            if user.is_authenticated else {}
        for course in courses:
            course.color = course_color(course)
            course.teacher_list = teachers[course.id]
            course.my_role = enrolled.get(course.id)
            course.progress = progress.get(course.id)
        context['courses'] = courses
        context['tab'] = self.tab
        context['search'] = self.request.GET.get('search', '')
        context['page_prefix'] = '?tab=%s&search=%s&page=' % (self.tab, context['search'])
        return context


class CourseDetail(CourseMixin, TitleMixin, DetailView):
    template_name = 'course/detail.html'
    context_object_name = 'course'

    def get_object(self, queryset=None):
        self.check_visible()
        return self.course

    def get_title(self):
        return self.course.name

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(self.get_course_context())
        context['teachers'] = list(self.course.get_teachers())
        context['student_count'] = self.course.roles.filter(role=RoleInCourse.STUDENT).count()
        lessons = list(self.course.get_lessons(include_hidden=context['can_edit'])
                       .prefetch_related('lesson_problems__problem'))
        context['lesson_count'] = len(lessons)
        if context['can_access']:
            progress = lesson_progress(self.request.user.profile, lessons)
            total = sum(p['total'] for p in progress.values())
            solved = sum(p['solved'] for p in progress.values())
            context['overall_percent'] = int(round(100 * solved / total)) if total else 0
            context['overall_solved'], context['overall_total'] = solved, total
            for lesson in lessons:
                lesson.progress = progress[lesson.id]
            apply_locks(lessons, progress, context['can_edit'])
            context['total_score'] = round(sum(p['score'] for p in progress.values()), 1)
            context['total_max'] = sum(p['max'] for p in progress.values())
            context['total_percent'] = (100.0 * context['total_score'] / context['total_max']
                                        if context['total_max'] else 0)
        context['lessons'] = lessons
        return context


class CourseLessonDetail(CourseMixin, TitleMixin, DetailView):
    template_name = 'course/lesson.html'
    context_object_name = 'lesson'

    def get_object(self, queryset=None):
        self.check_visible()
        if not self.course.is_accessible_by(self.request.user):
            raise Http404()
        lesson = get_object_or_404(CourseLesson.objects.prefetch_related('lesson_problems__problem'),
                                   course=self.course, id=self.kwargs['lesson'])
        if not lesson.is_visible and not self.course.is_editable_by(self.request.user):
            raise Http404()
        return lesson

    def get(self, request, *args, **kwargs):
        self.object = self.get_object()
        context = self.get_context_data(object=self.object)
        if self.object.locked:
            info = self.object.lock_info
            return generic_message(
                request, _('This lesson is locked'),
                _('Reach at least %(percent)d%% of the score in "%(lesson)s" to open this lesson '
                  '(you have %(current)d%%).') % {'percent': info['required'], 'lesson': info['lesson'].title,
                                                  'current': info['current']},
                status=403)
        return self.render_to_response(context)

    def get_title(self):
        return '%s — %s' % (self.object.title, self.course.name)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(self.get_course_context())
        lessons = list(self.course.get_lessons(include_hidden=context['can_edit'])
                       .prefetch_related('lesson_problems__problem'))
        all_progress = lesson_progress(self.request.user.profile, lessons)
        for lesson in lessons:
            lesson.progress = all_progress[lesson.id]
        apply_locks(lessons, all_progress, context['can_edit'])
        context['lessons'] = lessons
        context['course_percent'] = (int(round(100 * sum(p['solved'] for p in all_progress.values()) /
                                               max(1, sum(p['total'] for p in all_progress.values()))))
                                     if any(p['total'] for p in all_progress.values()) else 0)
        index = next(i for i, lesson in enumerate(lessons) if lesson.id == self.object.id)
        context['lesson_index'] = index + 1
        context['lesson_total'] = len(lessons)
        context['prev_lesson'] = lessons[index - 1] if index > 0 else None
        context['next_lesson'] = lessons[index + 1] if index + 1 < len(lessons) else None
        context['progress'] = all_progress[self.object.id]
        self.object.locked, self.object.lock_info = lessons[index].locked, lessons[index].lock_info
        quizzes = []
        if getattr(settings, 'QUIZ_ENABLED', False):
            quizzes = list(self.object.quizzes.annotate(qcount=Count('questions')).order_by('title'))
            from judge.views.quiz import best_scores
            scores = best_scores(self.request.user.profile, [q.id for q in quizzes])
            for quiz in quizzes:
                quiz.my_best = scores.get(quiz.id)
        context['quizzes'] = quizzes
        context['can_assign'] = class_stats.staffed_classes(self.request.user).exists()
        return context


class CourseLessonAssignForm(forms.Form):
    classroom = forms.ModelChoiceField(queryset=Classroom.objects.none(), label=_l('Class'), empty_label=None)
    scope = forms.ChoiceField(choices=(('lesson', _l('The whole lesson')), ('problems', _l('Only some problems'))),
                              widget=forms.RadioSelect, label=_l('What to give'), initial='lesson')
    problems = forms.ModelMultipleChoiceField(queryset=Problem.objects.none(), required=False, widget=forms.CheckboxSelectMultiple,
                                              label=_l('Problems'))
    title = forms.CharField(max_length=200, label=_l('Title'))
    due = forms.DateTimeField(required=False, label=_l('Due'), input_formats=[
        '%Y-%m-%dT%H:%M', '%d/%m/%Y %H:%M', '%Y-%m-%d %H:%M', '%d/%m/%Y'])
    description = forms.CharField(required=False, label=_l('Description'), widget=forms.Textarea(attrs={'rows': 3}))

    def __init__(self, *args, user, lesson, **kwargs):
        super().__init__(*args, **kwargs)
        self.user, self.lesson = user, lesson
        self.fields['classroom'].queryset = class_stats.staffed_classes(user).order_by('-school_year', 'name')
        self.fields['problems'].queryset = Problem.objects.filter(course_lessons__lesson=lesson) \
            .order_by('course_lessons__order', 'course_lessons__id')
        self.fields['problems'].label_from_instance = lambda p: '%s — %s' % (p.code, p.name)

    def clean(self):
        cleaned = super().clean()
        classroom = cleaned.get('classroom')
        if cleaned.get('scope') == 'problems':
            chosen = cleaned.get('problems')
            if not chosen:
                self.add_error('problems', _('Choose at least one problem.'))
            elif any(not p.is_accessible_by(self.user) for p in chosen):
                self.add_error('problems', _('You cannot use some of these problems.'))
        elif classroom is not None:
            error = class_stats.lesson_assign_error(self.user, classroom, self.lesson)
            if error:
                self.add_error('classroom', error)
        return cleaned


class CourseLessonAssign(LoginRequiredMixin, CourseMixin, TitleMixin, FormView):
    """Give a lesson, or just some of its problems, to one of the user's classes."""
    template_name = 'course/assign.html'
    form_class = CourseLessonAssignForm

    def get_title(self):
        return _('Assign: %s') % self.lesson.title

    @cached_property
    def lesson(self):
        self.check_visible()
        lesson = get_object_or_404(CourseLesson.objects.select_related('course'), course=self.course,
                                   id=self.kwargs['lesson'])
        user = self.request.user
        if not (self.course.is_accessible_by(user) or self.course.is_editable_by(user)):
            raise Http404()
        if not lesson.is_visible and not self.course.is_editable_by(user):
            raise Http404()
        return lesson

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            self.lesson  # 404 before anything else for lessons the user cannot see
            if not class_stats.staffed_classes(request.user).exists():
                raise PermissionDenied()
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs.update(user=self.request.user, lesson=self.lesson)
        if self.request.method == 'GET':
            code = self.request.GET.get('problem')
            classes = class_stats.staffed_classes(self.request.user)
            default = (classes.filter(slug=self.request.GET.get('class')).first() or
                       classes.filter(courses=self.course).first() or classes.first())
            problem = self.lesson.lesson_problems.filter(problem__code=code).select_related('problem').first()
            kwargs['initial'] = {
                'classroom': default.pk if default else None,
                'scope': 'problems' if problem else 'lesson',
                'problems': [problem.problem_id] if problem else [],
                'title': problem.problem.name if problem else self.lesson.title,
            }
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(self.get_course_context())
        context['lesson'] = self.lesson
        context['attached_ids'] = list(self.course.classes.values_list('id', flat=True))
        return context

    def form_valid(self, form):
        data = form.cleaned_data
        classroom, whole = data['classroom'], data['scope'] == 'lesson'
        attached = whole and not self.course.classes.filter(pk=classroom.pk).exists()
        class_stats.create_assignment(
            classroom, self.request.profile, title=data['title'], due=data['due'], description=data['description'],
            kind=ClassAssignment.KIND_LESSON if whole else ClassAssignment.KIND_PROBLEM,
            problems=[] if whole else list(data['problems']), lesson=self.lesson)
        messages.success(self.request, _('Assignment created.'))
        if attached:
            messages.info(self.request, _('The class was added to the course "%s" so the students can open the '
                                          'lesson.') % self.course.name)
        return HttpResponseRedirect(reverse('class_assignments', args=(classroom.slug,)))


class CourseLessonRanking(CourseMixin, TitleMixin, DetailView):
    template_name = 'course/lesson_ranking.html'
    context_object_name = 'lesson'

    def get_object(self, queryset=None):
        self.check_visible()
        if not self.course.is_accessible_by(self.request.user):
            raise Http404()
        lesson = get_object_or_404(CourseLesson.objects.prefetch_related('lesson_problems__problem'),
                                   course=self.course, id=self.kwargs['lesson'])
        if not lesson.is_visible and not self.course.is_editable_by(self.request.user):
            raise Http404()
        return lesson

    def get_title(self):
        return _('Ranking') + ' — ' + self.object.title

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(self.get_course_context())
        lesson = self.object
        lps = list(lesson.lesson_problems.all())
        problem_ids = [lp.problem_id for lp in lps]
        students = list(self.course.get_students())
        student_ids = [student.id for student in students]

        best, first_ac = {}, {}
        if problem_ids and student_ids:
            for row in (Submission.objects.filter(user_id__in=student_ids, problem_id__in=problem_ids)
                        .values('user_id', 'problem_id').annotate(best=Max('points'))):
                best[row['user_id'], row['problem_id']] = row['best'] or 0
            for row in (Submission.objects.filter(user_id__in=student_ids, problem_id__in=problem_ids, result='AC')
                        .values('user_id', 'problem_id').annotate(first=Min('date'))):
                first_ac[row['user_id'], row['problem_id']] = row['first']

        rows = []
        for student in students:
            cells, score, solved, last = [], 0.0, 0, None
            for lp in lps:
                key = (student.id, lp.problem_id)
                full = lp.problem.points or 0
                ac = key in first_ac
                ratio = 1.0 if ac else (min(1.0, best.get(key, 0) / full) if full else 0.0)
                got = lp.points * ratio
                score += got
                if ac:
                    solved += 1
                    last = first_ac[key] if last is None or first_ac[key] > last else last
                cells.append({'score': round(got, 1), 'max': lp.points, 'solved': ac,
                              'tried': key in best and not ac,
                              'percent': (100.0 * got / lp.points) if lp.points else 0.0})
            maximum = sum(lp.points for lp in lps)
            rows.append({'user': student, 'cells': cells, 'score': round(score, 1), 'max': maximum,
                         'solved': solved, 'last': last,
                         'percent': (100.0 * score / maximum) if maximum else 0.0})

        far = timezone.now() + timedelta(days=36500)
        rows.sort(key=lambda row: (-row['score'], -row['solved'], row['last'] or far, row['user'].user.username))
        previous, rank = None, 0
        for position, row in enumerate(rows, 1):
            if (row['score'], row['solved']) != previous:
                rank, previous = position, (row['score'], row['solved'])
            row['rank'] = rank

        context['lps'] = lps
        context['rows'] = rows
        context['me'] = next((row for row in rows if row['user'].id == self.request.profile.id), None)
        context['started'] = sum(1 for row in rows if row['score'] > 0)
        context['lesson_max'] = sum(lp.points for lp in lps)
        return context


class CourseGrades(CourseMixin, TitleMixin, DetailView):
    template_name = 'course/grades.html'
    context_object_name = 'course'

    def get_object(self, queryset=None):
        self.check_visible()
        if not self.course.is_accessible_by(self.request.user):
            raise Http404()
        return self.course

    def get_title(self):
        return _('Grades') + ' — ' + self.course.name

    def get(self, request, *args, **kwargs):
        export = request.GET.get('export')
        if export in ('csv', 'xlsx'):
            self.object = self.get_object()
            context = self.get_context_data(object=self.object)
            if not context['can_edit']:
                raise PermissionDenied()
            return self.export(export, context)
        return super().get(request, *args, **kwargs)

    def export(self, kind, context):
        lessons, rows = context['lessons'], context['rows']
        header = ['Rank', 'Username', 'Name'] + [lesson.title for lesson in lessons] + ['Total', 'Max', 'Percent']
        table = [[row['rank'], row['user'].user.username, row['user'].display_name] +
                 [cell['score'] for cell in row['cells']] + [row['score'], row['max'], round(row['percent'], 1)]
                 for row in rows]
        name = '%s-grades.%s' % (self.course.slug, kind)
        if kind == 'xlsx':
            response = HttpResponse(
                xlsx.build_xlsx(header, table, self.course.name),
                content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        else:
            response = HttpResponse(content_type='text/csv; charset=utf-8')
            response.write('\ufeff')  # BOM: Excel needs it to read Vietnamese names as UTF-8
            writer = csv.writer(response)
            writer.writerow(header)
            writer.writerows(table)
        response['Content-Disposition'] = 'attachment; filename="%s"' % name
        return response

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(self.get_course_context())
        lessons = list(self.course.get_lessons().prefetch_related('lesson_problems__problem'))
        if context['can_edit']:
            students = list(self.course.get_students())
        else:
            students = [self.request.user.profile]
        rows = []
        for student in students:
            progress = lesson_progress(student, lessons)
            rows.append({
                'user': student,
                'cells': [progress[lesson.id] for lesson in lessons],
                'score': round(sum(p['score'] for p in progress.values()), 1),
                'max': sum(p['max'] for p in progress.values()),
            })
        if context['can_edit']:
            rows.sort(key=lambda row: (-row['score'], row['user'].user.username))
        previous, rank = None, 0
        for position, row in enumerate(rows, 1):
            row['percent'] = (100.0 * row['score'] / row['max']) if row['max'] else 0.0
            for cell in row['cells']:
                cell['cell_percent'] = (100.0 * cell['score'] / cell['max']) if cell['max'] else 0.0
            if row['score'] != previous:
                rank, previous = position, row['score']
            row['rank'] = rank
        context['lessons'] = lessons
        context['rows'] = rows
        context['lesson_max'] = [sum(lp.points for lp in lesson.lesson_problems.all()) for lesson in lessons]
        if rows:
            context['class_average'] = sum(row['percent'] for row in rows) / len(rows)
            context['class_started'] = sum(1 for row in rows if row['score'] > 0)
            context['class_half'] = sum(1 for row in rows if row['percent'] >= 50)
            context['class_best'] = max(row['percent'] for row in rows)
        return context


class CourseJoin(LoginRequiredMixin, CourseMixin, View):
    http_method_names = ['post']

    def post(self, request, *args, **kwargs):
        course = self.course
        if course.can_join(request.user):
            CourseRole.objects.get_or_create(course=course, user=request.user.profile,
                                             defaults={'role': RoleInCourse.STUDENT})
            return HttpResponseRedirect(course.get_absolute_url())
        if course.is_accessible_by(request.user):
            return HttpResponseRedirect(course.get_absolute_url())
        return generic_message(request, _('Cannot join this course'),
                               _('This course is not open for registration.'), status=403)


class CourseLeave(LoginRequiredMixin, CourseMixin, View):
    http_method_names = ['post']

    def post(self, request, *args, **kwargs):
        role = CourseRole.objects.filter(course=self.course, user=request.user.profile).first()
        if role is not None:
            only_teacher = role.role == RoleInCourse.TEACHER and \
                not CourseRole.objects.filter(course=self.course, role=RoleInCourse.TEACHER) \
                .exclude(pk=role.pk).exists()
            if only_teacher:
                return generic_message(request, _('Cannot leave this course'),
                                       _('You are the only teacher of this course.'), status=403)
            role.delete()
        return HttpResponseRedirect(reverse('course_list'))
