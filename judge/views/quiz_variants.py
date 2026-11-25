"""Teacher pages for exam variants ("mã đề"): generate, review, and print them. See judge.utils.exam_variants."""
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponseRedirect
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.generic import TemplateView

from judge.models import ExamVariant, QuizAttempt
from judge.utils import exam_variants as ev
from judge.utils.views import TitleMixin
from judge.views.quiz import QuizMixin

__all__ = ['QuizVariants', 'QuizVariantPrint', 'QuizVariantKeyPrint']


class ManagerMixin(LoginRequiredMixin, QuizMixin):
    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not self.quiz.is_manageable_by(request.user):
            raise PermissionDenied()
        return super().dispatch(request, *args, **kwargs)

    def variants(self):
        return list(self.quiz.variants.all())


class QuizVariants(ManagerMixin, TitleMixin, TemplateView):
    template_name = 'quiz/variants/manage.html'

    def get_title(self):
        return _('Exam codes') + ' — ' + self.quiz.title

    def post(self, request, *args, **kwargs):
        quiz = self.quiz
        try:
            count = int(request.POST.get('count', ''))
        except ValueError:
            count = 0
        try:
            saved = ev.save_variants(
                quiz, count, request.POST.get('start_code', '0101'),
                shuffle_questions=request.POST.get('shuffle_questions') == '1',
                shuffle_options=request.POST.get('shuffle_options') == '1')
        except ev.VariantError as error:
            messages.error(request, error.args[0])
        else:
            messages.success(request, _('Exam codes generated:') + ' %d' % len(saved))
        return HttpResponseRedirect(reverse('quiz_variants', args=(quiz.slug,)))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        quiz = self.quiz
        questions = list(quiz.questions.prefetch_related('options'))
        real = [q for q in questions if q.kind != 'section']
        cards, key_rows, signatures, all_even = [], [], set(), True
        for variant in self.variants():
            ordered = ev.questions_in_order(variant, list(questions))
            dist = ev.answer_distribution(real, variant.option_orders)
            all_even = all_even and dist['even']
            signatures.add((tuple(variant.question_order),
                            tuple(sorted((k, tuple(v)) for k, v in variant.option_orders.items()))))
            rows = ev.answer_key(questions, variant.question_order, variant.option_orders)
            cards.append({'variant': variant, 'pages': ev.estimate_pages(ordered), 'count': len(rows),
                          'dist': dist, 'stale': ev.variant_is_stale(variant, quiz),
                          'attempts': variant.attempts.count()})
            key_rows.append({'variant': variant, 'rows': rows})
        context.update({
            'quiz': quiz, 'cards': cards, 'key_rows': key_rows, 'letters': 'ABCD',
            'all_unique': len(signatures) == len(cards), 'all_even': all_even,
            'drawn': bool(quiz.questions_per_attempt),
            'locked': QuizAttempt.objects.filter(quiz=quiz, variant__isnull=False).exists(),
            'can_manage': True, 'min_count': ev.MIN_COUNT, 'max_count': ev.MAX_COUNT,
            'question_total': len(real),
        })
        return context


class QuizVariantPrint(ManagerMixin, TemplateView):
    template_name = 'quiz/variants/print.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        try:
            variant = self.quiz.variants.get(code=self.kwargs['code'])
        except ExamVariant.DoesNotExist:
            raise Http404()
        layout = ev.variant_layout(variant)
        context.update({'quiz': self.quiz, 'variant': variant, 'items': layout['items'],
                        'total': layout['count'], 'pages': ev.estimate_pages(layout['questions'])})
        return context


class QuizVariantKeyPrint(ManagerMixin, TemplateView):
    template_name = 'quiz/variants/key_print.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        questions = list(self.quiz.questions.prefetch_related('options'))
        keys = [{'variant': v, 'rows': ev.answer_key(questions, v.question_order, v.option_orders)}
                for v in self.variants()]
        if not keys:
            raise Http404()
        context.update({'quiz': self.quiz, 'keys': keys})
        return context
