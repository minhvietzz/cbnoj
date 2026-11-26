import ipaddress
import secrets
from datetime import timedelta

from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Max, Q
from django.http import Http404, HttpResponse, HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.utils.functional import cached_property
from django.utils.translation import gettext as _, gettext_lazy
from django.views.decorators.cache import never_cache
from django.views.generic import DetailView, FormView, ListView, TemplateView, View

from judge.models import Classroom, Course, CourseLesson, Organization, Profile, Quiz, QuizAttempt, Subject
from judge.models.course import EDITABLE_ROLES
from judge.utils import exam_variants, quiz_grading, seb
from judge.utils.question_bank import split_tags
from judge.utils.quiz_create import apply_quiz, make_slug, save_questions  # noqa: F401  (re-exported for bank.py)
from judge.utils.quiz_parser import QuizFormatError, build_template_docx, parse_quiz_file, parse_quiz_lines
from judge.utils.views import TitleMixin

__all__ = ['QuizList', 'QuizDetail', 'QuizStart', 'QuizAttemptView', 'QuizAttemptSave', 'QuizResult',
           'QuizUpload', 'QuizUploadConfirm', 'QuizManage', 'QuizDelete', 'QuizTemplateDownload']

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
DRAFT_KEY = 'quiz_draft'


def client_ip(request):
    """Best-effort client address for the audit trail (X-Forwarded-For comes from our nginx, never trusted for auth)."""
    for value in (request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0].strip(),
                  request.META.get('REMOTE_ADDR', '')):
        try:
            return str(ipaddress.ip_address(value))
        except ValueError:
            continue
    return None


def can_upload(user):
    return user.is_authenticated and (user.is_superuser or user.has_perm('judge.add_quiz'))


def can_upload_for_org(user, org):
    """Administrators of an organization may hold exams in it, like contests, without the global add_quiz right."""
    return (user.is_authenticated and org is not None and
            (user.is_superuser or org.admins.filter(id=user.profile.id).exists()))


def best_scores(profile, quiz_ids):
    """{quiz_id: {'score', 'max', 'percent', 'attempts'}} for finished attempts of one user."""
    if profile is None or not quiz_ids:
        return {}
    result = {}
    rows = (QuizAttempt.objects.filter(user=profile, quiz_id__in=quiz_ids, finished__isnull=False)
            .values('quiz_id').annotate(attempts=Count('id')))
    for row in rows:
        best = (QuizAttempt.objects.filter(user=profile, quiz_id=row['quiz_id'], finished__isnull=False)
                .order_by('-score', 'finished').first())
        result[row['quiz_id']] = {'score': best.score, 'max': best.max_score, 'percent': best.percent,
                                  'attempts': row['attempts']}
    return result


def collect_answers(post, questions):
    answers = {}
    for question in questions:
        key = 'q%d' % question.id
        if question.kind == 'short':
            answers[str(question.id)] = post.get(key, '').strip()[:500]
        elif question.kind == 'tf4':
            # One radio group per statement: q<question>_<option> = 'T' (true) or 'F' (false).
            verdicts = {}
            for option in question.options.all():
                value = post.get('%s_%d' % (key, option.id))
                if value in ('T', 'F'):
                    verdicts[str(option.id)] = value == 'T'
            answers[str(question.id)] = verdicts
        else:
            valid = {o.id for o in question.options.all()}
            chosen = []
            for value in post.getlist(key):
                try:
                    option_id = int(value)
                except ValueError:
                    continue
                if option_id in valid and option_id not in chosen:
                    chosen.append(option_id)
            if question.kind == 'single':
                chosen = chosen[:1]
            answers[str(question.id)] = chosen
    return answers


class QuizTabsMixin(object):
    def tab_context(self, tab):
        return {'tab': tab, 'can_upload': can_upload(self.request.user)}


class QuizList(QuizTabsMixin, TitleMixin, ListView):
    template_name = 'quiz/list.html'
    context_object_name = 'quizzes'
    paginate_by = 12

    def get_title(self):
        return _('Quizzes')

    @cached_property
    def tab(self):
        tab = self.request.GET.get('tab', 'all')
        user = self.request.user
        if tab == 'mine' and user.is_authenticated:
            return 'mine'
        if tab == 'manage' and can_upload(user):
            return 'manage'
        return 'all'

    def get_queryset(self):
        queryset = self.visible_queryset()
        search = self.request.GET.get('search', '').strip()
        if search:
            queryset = queryset.filter(Q(title__icontains=search) | Q(description__icontains=search))
        subject = self.request.GET.get('subject', '').strip()[:64]
        if subject:
            queryset = queryset.filter(self.subject_filter(subject))
        return Quiz.objects.filter(id__in=queryset.values('id')).annotate(
            qcount=Count('questions', distinct=True)).select_related('creator__user', 'subject').order_by('-created')

    @staticmethod
    def subject_filter(subject):
        subject_filter = Q(subject__slug=subject)
        if subject == getattr(settings, 'DEFAULT_SUBJECT_SLUG', 'tin-hoc'):
            subject_filter |= Q(subject__isnull=True)
        return subject_filter

    def visible_queryset(self):
        user = self.request.user
        queryset = Quiz.objects.all()
        if self.tab == 'mine':
            queryset = queryset.filter(attempts__user=user.profile)
        elif self.tab == 'manage':
            queryset = queryset if user.is_superuser else queryset.filter(creator=user.profile)
            queryset = queryset.exclude(mode='personal')   # students' practice sets are not teaching material
        else:
            visible = Q(is_public=True, mode='practice')
            exams = Q(mode='exam', course__isnull=True)
            if user.is_authenticated:
                visible |= exams & (Q(organizations__member=user.profile) |
                                    Q(is_public=True, organizations__isnull=True))
            else:
                visible |= exams & Q(is_public=True, organizations__isnull=True)
            queryset = queryset.filter(visible)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        quizzes = list(context['quizzes'])
        scores = best_scores(self.request.user.profile if self.request.user.is_authenticated else None,
                             [q.id for q in quizzes])
        for quiz in quizzes:
            quiz.my_best = scores.get(quiz.id)
        context['quizzes'] = quizzes
        context['search'] = self.request.GET.get('search', '')
        context['subject'] = self.request.GET.get('subject', '').strip()[:64]
        context['subjects'] = list(Subject.objects.filter(is_active=True))
        visible = self.visible_queryset()
        context['subject_counts'] = [(sub, Quiz.objects.filter(id__in=visible.values('id'))
                                      .filter(self.subject_filter(sub.slug)).count()) for sub in context['subjects']]
        context['total_visible'] = Quiz.objects.filter(id__in=visible.values('id')).count()
        context['page_prefix'] = '?tab=%s&search=%s&subject=%s&page=' % (
            self.tab, context['search'], context['subject'])
        context.update(self.tab_context(self.tab))
        return context


class QuizMixin(object):
    @cached_property
    def quiz(self):
        return get_object_or_404(Quiz, slug=self.kwargs['slug'])

    def check_access(self):
        if not self.quiz.is_accessible_by(self.request.user):
            raise Http404()

    def check_seb(self):
        """Exams locked to Safe Exam Browser refuse every other client (teachers may preview them)."""
        quiz = self.quiz
        if quiz.seb_browser_key and not quiz.is_manageable_by(self.request.user) and \
                not seb.request_ok(self.request, quiz.seb_browser_key):
            raise PermissionDenied(_('This exam can only be taken in Safe Exam Browser.'))

    def manage_context(self):
        return {'quiz': self.quiz, 'can_manage': self.quiz.is_manageable_by(self.request.user),
                'can_upload': can_upload(self.request.user)}


class QuizDetail(QuizMixin, TitleMixin, DetailView):
    template_name = 'quiz/detail.html'
    context_object_name = 'quiz'

    def get_object(self, queryset=None):
        self.check_access()
        return self.quiz

    def get_title(self):
        return self.quiz.title

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(self.manage_context())
        user = self.request.user
        quiz = self.quiz
        context['question_count'] = quiz.paper_size
        context['total_points'] = round(quiz.paper_points, 2)
        attempts, running, finished_count = [], None, 0
        if user.is_authenticated:
            attempts = list(quiz.attempts.filter(user=user.profile))
            for attempt in attempts:
                attempt.finish_if_expired()
            finished_count = sum(1 for a in attempts if a.is_finished and not a.invalidated)
            running = next((a for a in attempts if not a.is_finished), None)
        phase = quiz.phase()
        limit = quiz.attempt_limit
        results_visible = quiz.results_visible_to(user)
        context['attempts'] = [a for a in attempts if a.is_finished]
        context['running'] = running
        context['remaining'] = None if not limit else max(0, limit - finished_count)
        context['phase'] = phase
        context['needs_seb'] = bool(quiz.seb_browser_key)
        context['results_visible'] = results_visible
        context['seconds_to_start'] = (max(0, int((quiz.start_time - timezone.now()).total_seconds()))
                                       if quiz.is_exam and quiz.start_time and phase == 'upcoming' else None)
        context['can_start'] = (user.is_authenticated and context['question_count'] > 0 and
                                (running is not None or
                                 (phase == 'running' and (context['remaining'] is None or context['remaining'] > 0))))
        leaderboard = []
        if results_visible:
            top = (quiz.attempts.filter(finished__isnull=False, invalidated=False).values('user')
                   .annotate(best=Max('score')).order_by('-best')[:10])
            profiles = {p.id: p for p in Profile.objects.filter(id__in=[t['user'] for t in top]).select_related('user')}
            leaderboard = [{'user': profiles[t['user']], 'score': t['best']} for t in top]
        context['leaderboard'] = leaderboard
        return context


class QuizStart(LoginRequiredMixin, QuizMixin, View):
    http_method_names = ['post']

    def post(self, request, *args, **kwargs):
        self.check_access()
        self.check_seb()
        quiz, profile = self.quiz, request.user.profile
        if not quiz.questions.exists():
            raise Http404()
        running = quiz.attempts.filter(user=profile, finished__isnull=True).first()
        if running is not None and running.finish_if_expired():
            running = None
        if running is None:
            phase = quiz.phase()
            if phase != 'running':
                messages.error(request, _('This exam has not started yet.') if phase == 'upcoming'
                               else _('This exam has ended.'))
                return HttpResponseRedirect(quiz.get_absolute_url())
            if quiz.proctoring != 'off' and request.POST.get('agree') != '1':
                messages.error(request, _('You must accept the exam rules before starting.'))
                return HttpResponseRedirect(quiz.get_absolute_url())
            finished = quiz.attempts.filter(user=profile, finished__isnull=False, invalidated=False).count()
            if quiz.attempt_limit and finished >= quiz.attempt_limit:
                raise PermissionDenied(_('You have used all attempts for this quiz.'))
            import random
            running = QuizAttempt.objects.create(
                quiz=quiz, user=profile, seed=random.randint(1, 2 ** 31 - 1), ip=client_ip(request),
                user_agent=request.META.get('HTTP_USER_AGENT', '')[:255])
            exam_variants.assign_variant(running)   # no-op unless the teacher generated exam codes
        return HttpResponseRedirect(reverse('quiz_attempt', args=(quiz.slug, running.id)))


class AttemptMixin(QuizMixin):
    @cached_property
    def attempt(self):
        attempt = get_object_or_404(QuizAttempt, id=self.kwargs['attempt'], quiz=self.quiz)
        user = self.request.user
        if not user.is_authenticated or (attempt.user_id != user.profile.id and
                                         not self.quiz.is_manageable_by(user)):
            raise Http404()
        return attempt


SUBMIT_GRACE = timedelta(seconds=30)  # a submit that arrives this long after the deadline ignores the posted answers


def attempt_state(attempt):
    """What the exam page needs to know after any proctoring call."""
    quiz = attempt.quiz
    state = {'status': 'finished' if attempt.is_finished else 'ok',
             'violations': attempt.violation_count, 'max_violations': quiz.max_violations,
             'seconds_left': attempt.seconds_left}
    if attempt.is_finished:
        state['redirect'] = reverse('quiz_result', args=(quiz.slug, attempt.id))
    return state


@method_decorator(never_cache, name='dispatch')
class QuizAttemptView(LoginRequiredMixin, AttemptMixin, TitleMixin, TemplateView):
    template_name = 'quiz/take.html'

    def get_title(self):
        return self.quiz.title

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        self.check_access()
        self.check_seb()
        attempt = self.attempt
        if attempt.user_id != request.user.profile.id:
            raise Http404()
        if request.method != 'POST':
            attempt.finish_if_expired()
        if attempt.is_finished:
            return HttpResponseRedirect(reverse('quiz_result', args=(self.quiz.slug, attempt.id)))
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, *args, **kwargs):
        attempt = self.attempt
        if self.quiz.is_secured:
            # A new token per page load: any older tab or device still holding the attempt is superseded.
            if attempt.session_key:
                from judge.views.quiz_exam import record_violation
                record_violation(attempt.id, 'reload', 'The exam page was loaded again.')
                attempt.refresh_from_db()
            attempt.session_key = secrets.token_hex(16)
            attempt.ip = client_ip(request)
            attempt.user_agent = request.META.get('HTTP_USER_AGENT', '')[:255]
            attempt.last_heartbeat = timezone.now()
            attempt.save(update_fields=['session_key', 'ip', 'user_agent', 'last_heartbeat'])
        return super().get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        attempt = self.attempt
        deadline = attempt.deadline
        if deadline and timezone.now() > deadline + SUBMIT_GRACE:
            attempt.finish(auto_submitted=True)  # too late: grade what was autosaved before the deadline
        else:
            questions = attempt.drawn_questions()
            attempt.finish(collect_answers(request.POST, questions), auto_submitted=attempt.is_expired)
        return HttpResponseRedirect(reverse('quiz_result', args=(self.quiz.slug, attempt.id)))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        attempt = self.attempt
        questions = exam_variants.apply_variant(attempt, attempt.ordered_questions())
        saved = attempt.answers or {}
        for question in questions:
            value = saved.get(str(question.id))
            question.saved_ids = set(value) if isinstance(value, list) else set()
            question.saved_text = value if isinstance(value, str) else ''
            question.saved_tf = {int(k): v for k, v in value.items()} if isinstance(value, dict) else {}
        passages = []
        for question in questions:
            text = question.passage.strip()
            if text and text not in passages:
                passages.append(text)
            question.passage_no = passages.index(text) + 1 if text else 0
        context.update({'quiz': self.quiz, 'attempt': exam_variants.shown_attempt(attempt),
                        'questions': questions, 'passages': passages,
                        'seconds_left': attempt.seconds_left,
                        'violations_left': (max(0, self.quiz.max_violations - attempt.violation_count)
                                            if self.quiz.max_violations else None)})
        return context


class QuizAttemptSave(LoginRequiredMixin, AttemptMixin, View):
    http_method_names = ['post']

    def post(self, request, *args, **kwargs):
        self.check_access()
        self.check_seb()
        attempt = self.attempt
        if attempt.user_id != request.user.profile.id or attempt.is_finished:
            return JsonResponse({'saved': False}, status=400)
        if attempt.finish_if_expired():
            return JsonResponse(dict(attempt_state(attempt), saved=False), status=409)
        if self.quiz.is_secured and request.POST.get('attempt_token') != attempt.session_key:
            from judge.views.quiz_exam import superseded_response
            return superseded_response(attempt)
        questions = attempt.drawn_questions()
        attempt.answers = collect_answers(request.POST, questions)
        attempt.save(update_fields=['answers'])
        return JsonResponse({'saved': True, 'seconds_left': attempt.seconds_left})


class QuizResult(AttemptMixin, TitleMixin, TemplateView):
    template_name = 'quiz/result.html'

    def get_title(self):
        return _('Result') + ' — ' + self.quiz.title

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            from django.contrib.auth.views import redirect_to_login
            return redirect_to_login(request.get_full_path())
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        attempt = self.attempt
        if not attempt.is_finished:
            raise Http404()
        context = super().get_context_data(**kwargs)
        context.update(self.manage_context())
        if not self.quiz.results_visible_to(self.request.user):
            # Mock exam whose results are not released yet: confirm the submission, show nothing else.
            context.update({'attempt': attempt, 'review': [], 'reveal': False, 'owner': attempt.user,
                            'results_hidden': True})
            return context
        # Mock exam answers stay hidden until the exam has closed for everyone (see Quiz.answers_released).
        released = self.quiz.answers_released()
        reveal = (self.quiz.show_answers and released) or context['can_manage']
        context['answers_pending'] = self.quiz.show_answers and not released and not context['can_manage']
        review = []
        if reveal:
            questions = exam_variants.apply_variant(attempt, attempt.ordered_questions())
            for number, question in enumerate(questions, 1):
                given = attempt.answers.get(str(question.id))
                chosen = set(given) if isinstance(given, list) else set()
                review.append({
                    'number': number, 'question': question, 'chosen': chosen,
                    'text': given if isinstance(given, str) else '',
                    'tf': {int(k): v for k, v in given.items()} if isinstance(given, dict) else {},
                    'correct': attempt.results.get(str(question.id)),
                    'earned': attempt.scores.get(str(question.id)),
                    'answered': quiz_grading.is_answered(question.kind, given),
                })
        context.update({'attempt': attempt, 'review': review, 'reveal': reveal,
                        'owner': attempt.user})
        return context


# ---------------------------------------------------------------- upload / manage

class UploadForm(forms.Form):
    title = forms.CharField(max_length=200, label=gettext_lazy('Title'))
    description = forms.CharField(required=False, label=gettext_lazy('Description'),
                                  widget=forms.Textarea(attrs={'rows': 3}))
    file = forms.FileField(required=False, label=gettext_lazy('Quiz file (.docx, .txt, .md)'))
    text = forms.CharField(required=False, label=gettext_lazy('Or paste the quiz text'),
                           widget=forms.Textarea(attrs={'rows': 10, 'placeholder': '[qus] ...\nA. ...\nB. ...\n[ans] A'}))  # noqa: E501
    time_limit = forms.IntegerField(min_value=0, max_value=600, initial=0, label=gettext_lazy('Time limit (minutes, 0 = none)'))  # noqa: E501
    max_attempts = forms.IntegerField(min_value=0, max_value=100, initial=0,
                                      label=gettext_lazy('Maximum attempts (0 = unlimited)'))
    shuffle_questions = forms.BooleanField(required=False, label=gettext_lazy('Shuffle questions'))
    shuffle_options = forms.BooleanField(required=False, label=gettext_lazy('Shuffle options'))
    show_answers = forms.BooleanField(required=False, initial=True,
                                      label=gettext_lazy('Show correct answers after submitting'))
    is_public = forms.BooleanField(required=False, label=gettext_lazy('Publicly visible'))
    lesson = forms.ModelChoiceField(queryset=CourseLesson.objects.none(), required=False,
                                    label=gettext_lazy('Attach to course lesson (optional)'))
    to_bank = forms.BooleanField(required=False, initial=True,
                                 label=gettext_lazy('Also add the questions to the question bank'))
    bank_tags = forms.CharField(required=False, max_length=200,
                                label=gettext_lazy('Extra question bank tags (comma separated)'))

    def __init__(self, *args, user=None, replacing=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.replacing = replacing
        if user is not None:
            lessons = CourseLesson.objects.select_related('course')
            if not user.is_superuser:
                lessons = lessons.filter(course__roles__user=user.profile, course__roles__role__in=EDITABLE_ROLES)
            self.fields['lesson'].queryset = lessons.order_by('course__name', 'order')
            self.fields['lesson'].label_from_instance = lambda lesson: '%s — %s' % (lesson.course.name, lesson.title)
        if replacing:
            self.fields['title'].required = False

    def clean_file(self):
        upload = self.cleaned_data.get('file')
        if upload and upload.size > MAX_UPLOAD_BYTES:
            raise forms.ValidationError(_('The file is larger than 5 MB.'))
        return upload

    def clean(self):
        cleaned = super().clean()
        upload, text = cleaned.get('file'), (cleaned.get('text') or '').strip()
        self.parsed = None
        if self.errors.get('file'):
            return cleaned
        if not upload and not text:
            self.add_error(None, _('Upload a file or paste the quiz text.'))
            return cleaned
        try:
            if upload:
                questions, errors, warnings = parse_quiz_file(upload.name, upload.read())
                source = upload.name
            else:
                questions, errors, warnings = parse_quiz_lines(text.splitlines())
                source = ''
        except QuizFormatError as e:
            self.add_error('file' if upload else 'text', _(str(e)))
            return cleaned
        self.parsed = {'questions': questions, 'errors': errors, 'warnings': warnings, 'source': source}
        return cleaned


class QuizUpload(LoginRequiredMixin, TitleMixin, FormView):
    template_name = 'quiz/upload.html'
    form_class = UploadForm

    def get_title(self):
        return _('Upload quiz')

    def dispatch(self, request, *args, **kwargs):
        if (request.user.is_authenticated and not can_upload(request.user) and
                not can_upload_for_org(request.user, self.org) and self.classroom is None):
            raise PermissionDenied(_('You do not have permission to upload quizzes.'))
        return super().dispatch(request, *args, **kwargs)

    @cached_property
    def org(self):
        """The organization this exam is being uploaded for (?org=<id>), if any."""
        org_id = self.request.GET.get('org') or self.request.POST.get('org')
        return Organization.objects.filter(id=org_id).first() if org_id and org_id.isdigit() else None

    @cached_property
    def classroom(self):
        """The class this exam is being created for (?class=<id>); only people who manage that class may."""
        class_id = self.request.GET.get('class') or self.request.POST.get('class')
        if not class_id or not class_id.isdigit() or not self.request.user.is_authenticated:
            return None
        classroom = Classroom.objects.filter(id=class_id).first()
        return classroom if classroom is not None and classroom.is_managed_by(self.request.user) else None

    @cached_property
    def replacing(self):
        slug = self.request.GET.get('replace') or self.request.POST.get('replace')
        if not slug:
            return None
        quiz = get_object_or_404(Quiz, slug=slug)
        if not quiz.is_manageable_by(self.request.user):
            raise PermissionDenied()
        return quiz

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs.update(user=self.request.user, replacing=bool(self.replacing))
        return kwargs

    def get_initial(self):
        if self.replacing:
            q = self.replacing
            return {'title': q.title, 'description': q.description, 'time_limit': q.time_limit,
                    'max_attempts': q.max_attempts, 'shuffle_questions': q.shuffle_questions,
                    'shuffle_options': q.shuffle_options, 'show_answers': q.show_answers,
                    'is_public': q.is_public, 'lesson': q.lesson_id}
        return super().get_initial()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({'replacing': self.replacing, 'can_upload': True, 'tab': 'upload', 'org': self.org,
                        'classroom': self.classroom})
        return context

    def form_valid(self, form):
        parsed = form.parsed
        context = {'form': form, 'replacing': self.replacing, 'parsed': parsed, 'title': self.get_title(),
                   'can_upload': True, 'tab': 'upload', 'org': self.org, 'classroom': self.classroom}
        if parsed['errors']:
            return render(self.request, 'quiz/upload.html', context)
        data = form.cleaned_data
        title = data['title'] or (self.replacing.title if self.replacing else '')
        self.request.session[DRAFT_KEY] = {
            'title': title, 'description': data['description'], 'time_limit': data['time_limit'],
            'max_attempts': data['max_attempts'], 'shuffle_questions': data['shuffle_questions'],
            'shuffle_options': data['shuffle_options'], 'show_answers': data['show_answers'],
            'is_public': data['is_public'], 'lesson': data['lesson'].id if data['lesson'] else None,
            'to_bank': data['to_bank'], 'bank_tags': data['bank_tags'],
            'replace': self.replacing.slug if self.replacing else None,
            'org': self.org.id if self.org and can_upload_for_org(self.request.user, self.org) else None,
            'class': self.classroom.id if self.classroom else None,
            'source': parsed['source'], 'questions': parsed['questions'],
        }
        context.update({'draft': self.request.session[DRAFT_KEY], 'preview': True,
                        'total_points': round(sum(q['points'] for q in parsed['questions']), 2)})
        return render(self.request, 'quiz/preview.html', context)


class QuizUploadConfirm(LoginRequiredMixin, View):
    http_method_names = ['post']

    def post(self, request, *args, **kwargs):
        draft = request.session.pop(DRAFT_KEY, None)
        org = Organization.objects.filter(id=draft.get('org')).first() if draft and draft.get('org') else None
        classroom = Classroom.objects.filter(id=draft.get('class')).first() if draft and draft.get('class') else None
        if classroom is not None and not classroom.is_managed_by(request.user):
            classroom = None
        if not can_upload(request.user) and not can_upload_for_org(request.user, org) and classroom is None:
            raise PermissionDenied()
        if not draft:
            return HttpResponseRedirect(reverse('quiz_upload'))
        if org is not None and not can_upload_for_org(request.user, org):
            org = None
        lesson = CourseLesson.objects.filter(id=draft['lesson']).select_related('course').first() \
            if draft['lesson'] else None
        if lesson and not lesson.course.is_editable_by(request.user):
            lesson = None
        replacing = None
        if draft['replace']:
            replacing = get_object_or_404(Quiz, slug=draft['replace'])
            if not replacing.is_manageable_by(request.user):
                raise PermissionDenied()
        quiz, bank_result = apply_quiz(
            request.user.profile, draft['questions'], quiz=replacing, title=draft['title'],
            description=draft['description'], time_limit=draft['time_limit'], max_attempts=draft['max_attempts'],
            shuffle_questions=draft['shuffle_questions'], shuffle_options=draft['shuffle_options'],
            show_answers=draft['show_answers'], is_public=draft['is_public'], lesson=lesson, source=draft['source'],
            org=org, classroom=classroom, to_bank=bool(draft.get('to_bank')),
            bank_tags=split_tags(draft.get('bank_tags')))
        if bank_result is not None:
            messages.success(request, _('%(added)d new questions were added to the question bank '
                                        '(%(skipped)d already existed).') % {'added': bank_result[0],
                                                                             'skipped': bank_result[1]})
        if classroom is not None and not draft['replace']:
            messages.success(request, _('The exam was created for %(org)s. Set its start and end time here.')
                             % {'org': classroom.name})
            return HttpResponseRedirect(reverse('quiz_manage', args=(quiz.slug,)))
        if org is not None and not draft['replace']:
            messages.success(request, _('The exam was created for %(org)s. Set its start and end time here.')
                             % {'org': org.name})
            return HttpResponseRedirect(reverse('quiz_manage', args=(quiz.slug,)))
        return HttpResponseRedirect(quiz.get_absolute_url())


DATETIME_INPUT = '%Y-%m-%dT%H:%M'


class ManageForm(forms.ModelForm):
    start_time = forms.DateTimeField(
        required=False, label=gettext_lazy('Exam start'), input_formats=[DATETIME_INPUT, '%Y-%m-%d %H:%M:%S'],
        widget=forms.DateTimeInput(attrs={'type': 'datetime-local'}, format=DATETIME_INPUT))
    end_time = forms.DateTimeField(
        required=False, label=gettext_lazy('Exam end'), input_formats=[DATETIME_INPUT, '%Y-%m-%d %H:%M:%S'],
        widget=forms.DateTimeInput(attrs={'type': 'datetime-local'}, format=DATETIME_INPUT))

    class Meta:
        model = Quiz
        fields = ('title', 'description', 'mode', 'course', 'organizations', 'track', 'start_time', 'end_time', 'time_limit',  # noqa: E501
                  'max_attempts', 'questions_per_attempt', 'proctoring', 'max_violations', 'results_release',
                  'rules_text',
                  'seb_browser_key', 'shuffle_questions', 'shuffle_options', 'show_answers', 'is_public', 'lesson')

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        lessons = CourseLesson.objects.select_related('course')
        courses = Course.objects.all()
        if user is not None and not user.is_superuser:
            lessons = lessons.filter(course__roles__user=user.profile, course__roles__role__in=EDITABLE_ROLES)
            courses = courses.filter(roles__user=user.profile, roles__role__in=EDITABLE_ROLES).distinct()
        self.fields['lesson'].queryset = lessons.order_by('course__name', 'order')
        self.fields['lesson'].label_from_instance = lambda lesson: '%s — %s' % (lesson.course.name, lesson.title)
        self.fields['course'].queryset = courses.order_by('name')
        orgs = Organization.objects.all()
        if user is not None and not user.is_superuser:
            orgs = orgs.filter(admins=user.profile)
        self.fields['organizations'].queryset = orgs.order_by('name')
        self.fields['organizations'].required = False
        self.fields['course'].help_text = _('Optional. A mock exam in a course is only open to its members; '
                                            'without a course it follows "publicly visible".')

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('mode') == 'exam':
            if not cleaned.get('start_time') or not cleaned.get('end_time'):
                self.add_error('end_time', _('A mock exam needs a start and an end time.'))
            elif cleaned['end_time'] <= cleaned['start_time']:
                self.add_error('end_time', _('The exam must end after it starts.'))
        return cleaned


class QuizManage(LoginRequiredMixin, QuizMixin, TitleMixin, FormView):
    template_name = 'quiz/manage.html'
    form_class = ManageForm

    def get_title(self):
        return _('Manage') + ' — ' + self.quiz.title

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not self.quiz.is_manageable_by(request.user):
            raise PermissionDenied()
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs.update(instance=self.quiz, user=self.request.user)
        return kwargs

    def get_success_url(self):
        return reverse('quiz_manage', args=(self.quiz.slug,))

    def form_valid(self, form):
        form.save()
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(self.manage_context())
        quiz = self.quiz
        finished = quiz.attempts.filter(finished__isnull=False)
        stats = finished.aggregate(count=Count('id'), people=Count('user', distinct=True))
        context['stats'] = stats
        context['recent'] = list(finished.select_related('user__user').order_by('-finished')[:15])
        context['question_count'] = quiz.questions.count()
        return context


class QuizDelete(LoginRequiredMixin, QuizMixin, View):
    http_method_names = ['post']

    def post(self, request, *args, **kwargs):
        if not self.quiz.is_manageable_by(request.user):
            raise PermissionDenied()
        self.quiz.delete()
        return HttpResponseRedirect(reverse('quiz_list') + '?tab=manage')


class QuizTemplateDownload(View):
    def get(self, request, *args, **kwargs):
        response = HttpResponse(
            build_template_docx(),
            content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document')
        response['Content-Disposition'] = 'attachment; filename="mau-de-trac-nghiem.docx"'
        return response
