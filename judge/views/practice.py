from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.http import HttpResponseRedirect, JsonResponse
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.generic import TemplateView, View

from judge.models import BankTag
from judge.utils import practice
from judge.utils.views import TitleMixin
from judge.views.quiz import AttemptMixin, can_upload, collect_answers

__all__ = ['PracticeSetup', 'PracticeMistakes', 'PracticeCheck']


def to_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class PracticeAccessMixin(LoginRequiredMixin):
    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not practice.can_practice(request.user):
            raise PermissionDenied(_('Practice is available to members of a course.'))
        return super().dispatch(request, *args, **kwargs)

    def tab_context(self, tab):
        return {'tab': tab, 'can_upload': can_upload(self.request.user)}


class PracticeSetup(PracticeAccessMixin, TitleMixin, TemplateView):
    template_name = 'quiz/practice.html'

    def get_title(self):
        return _('Practice')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        tracks, topics = practice.tag_options()
        context.update(self.tab_context('practice'))
        context.update({'tracks': tracks, 'topics': topics, 'default_count': practice.DEFAULT_COUNT,
                        'min_count': practice.MIN_COUNT, 'max_count': practice.MAX_COUNT,
                        'form': kwargs.get('form', {})})
        return context

    def post(self, request, *args, **kwargs):
        profile = request.user.profile
        post = request.POST
        minutes = max(0, min(180, to_int(post.get('minutes'))))
        if post.get('source') == 'mistakes':
            wanted = {to_int(i) for i in post.getlist('ids')}
            rows = [r for r in practice.mistakes(profile) if not wanted or r['bank'].id in wanted]
            questions = [r['bank'] for r in rows][:practice.MAX_COUNT]
            title = _('Practice mistakes')
            back = reverse('practice_mistakes')
        else:
            tag_ids = [to_int(i) for i in post.getlist('tags')]
            track_ids = [to_int(i) for i in post.getlist('tracks')]
            questions = practice.pick_questions(
                profile, tag_ids=tag_ids, track_ids=track_ids, level=to_int(post.get('level')),
                kinds=post.get('kinds', ''), count=to_int(post.get('count'), practice.DEFAULT_COUNT),
                prefer_new=post.get('prefer_new') == 'on')
            names = list(BankTag.objects.filter(id__in=[i for i in tag_ids + track_ids if i])
                         .order_by('name').values_list('name', flat=True))
            title = _('Practice') + (': ' + ', '.join(names[:3]) if names else '')
            back = reverse('practice')
        if not questions:
            messages.warning(request, _('No questions match your choice. Try other topics or levels.'))
            return HttpResponseRedirect(back)
        quiz, attempt = practice.create_session(profile, questions, title, minutes)
        return HttpResponseRedirect(reverse('quiz_attempt', args=(quiz.slug, attempt.id)))


class PracticeMistakes(PracticeAccessMixin, TitleMixin, TemplateView):
    template_name = 'quiz/mistakes.html'

    def get_title(self):
        return _('Mistake notebook')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(self.tab_context('mistakes'))
        context['rows'] = practice.mistakes(self.request.user.profile)
        return context


class PracticeCheck(LoginRequiredMixin, AttemptMixin, View):
    """Instant feedback for one question. Only personal practice sets: exams and class quizzes never reveal it."""
    http_method_names = ['post']

    def post(self, request, *args, **kwargs):
        self.check_access()
        attempt, quiz = self.attempt, self.quiz
        if quiz.mode != 'personal' or attempt.user_id != request.user.profile.id or attempt.is_finished:
            return JsonResponse({'status': 'error'}, status=400)
        question = quiz.questions.filter(id=to_int(request.POST.get('question'))).prefetch_related('options').first()
        if question is None:
            return JsonResponse({'status': 'error'}, status=404)
        given = collect_answers(request.POST, [question])[str(question.id)]
        answers = dict(attempt.answers or {})
        answers[str(question.id)] = given          # checking also saves the answer
        attempt.answers = answers
        attempt.save(update_fields=['answers'])
        fraction = question.score_fraction(given)
        data = {'status': 'ok', 'fraction': fraction, 'points': round(question.points * fraction, 4),
                'max': question.points, 'kind': question.kind}
        if question.kind == 'short':
            data['accepted'] = question.accepted_list()
        elif question.kind == 'tf4':
            data['tf'] = {str(o.id): o.is_correct for o in question.options.all()}
        else:
            data['correct'] = sorted(question.correct_option_ids())
        return JsonResponse(data)
