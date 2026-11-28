import difflib

from django.http import Http404, HttpResponseRedirect, JsonResponse
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.views.generic import View
from django.views.generic.detail import DetailView, SingleObjectMixin

from judge.models import ContestSimilarity
from judge.tasks import rebuild_contest_similarity
from judge.utils.views import TitleMixin
from judge.views.contests import ContestMixin

__all__ = ['ContestSimilarityView', 'ContestSimilarityFeed', 'ContestSimilarityPair', 'ContestSimilarityAction']


class ContestSimilarityMixin(ContestMixin):
    """Chỉ người sửa được kỳ thi mới xem được."""

    def get_object(self, queryset=None):
        contest = super().get_object(queryset)
        if not contest.is_editable_by(self.request.user):
            raise Http404()
        return contest

    def base_queryset(self):
        return (ContestSimilarity.objects.filter(contest=self.object)
                .select_related('problem', 'participation_a__user__user', 'participation_b__user__user'))


def _signature(qs):
    last = qs.order_by('-updated').values_list('updated', flat=True).first()
    return '%d-%s' % (qs.count(), last.timestamp() if last else 0)


class ContestSimilarityView(ContestSimilarityMixin, TitleMixin, DetailView):
    template_name = 'contest/similarity.html'

    def get_title(self):
        return 'Bài giống nhau - %s' % self.object.name

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        qs = self.base_queryset()
        problem = self.request.GET.get('problem', '')
        status = self.request.GET.get('status', 'open')
        level = self.request.GET.get('level', '')
        problems = sorted({(r.problem.code, r.problem.name) for r in qs}, key=lambda x: x[0])
        if problem:
            qs = qs.filter(problem__code=problem)
        if level in ('strong', 'review'):
            qs = qs.filter(level=level)
        if status == 'open':
            qs = qs.exclude(status=ContestSimilarity.STATUS_DISMISSED)
        elif status == 'dismissed':
            qs = qs.filter(status=ContestSimilarity.STATUS_DISMISSED)
        rows = list(qs.order_by('-level', '-score', '-literal_score')[:500])   # 'strong' > 'review' theo chữ cái giảm dần
        context.update({
            'rows': rows, 'problems': problems, 'sel_problem': problem, 'sel_status': status, 'sel_level': level,
            'signature': _signature(self.base_queryset()), 'feed_url': reverse('contest_similarity_feed',
                                                                              args=(self.object.key,)),
            'n_new': sum(1 for r in rows if r.status == ContestSimilarity.STATUS_NEW),
            'can_edit': True, 'tab': 'similarity',
        })
        return context

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        rebuild_contest_similarity.delay(self.object.key)
        return HttpResponseRedirect(reverse('contest_similarity', args=(self.object.key,)))


class ContestSimilarityFeed(ContestSimilarityMixin, SingleObjectMixin, View):
    def get(self, request, *args, **kwargs):
        self.object = self.get_object()
        return JsonResponse({'signature': _signature(self.base_queryset())})


class ContestSimilarityPair(ContestSimilarityMixin, TitleMixin, DetailView):
    template_name = 'contest/similarity-pair.html'

    def get_title(self):
        return 'So sánh hai bài - %s' % self.object.name

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        try:
            pair = self.base_queryset().select_related('submission_a__source', 'submission_b__source',
                                                       'submission_a__language', 'submission_b__language'
                                                       ).get(pk=self.kwargs['sim_id'])
        except ContestSimilarity.DoesNotExist:
            raise Http404()
        if pair.status == ContestSimilarity.STATUS_NEW:
            pair.status = ContestSimilarity.STATUS_SEEN
            pair.reviewed_by = self.request.profile
            pair.save(update_fields=['status', 'reviewed_by', 'updated'])
        a = pair.submission_a.source.source.splitlines()
        b = pair.submission_b.source.source.splitlines()
        na, nb = [x.strip() for x in a], [x.strip() for x in b]
        same_a, same_b = set(), set()
        for blk in difflib.SequenceMatcher(None, na, nb, autojunk=False).get_matching_blocks():
            for k in range(blk.size):
                if na[blk.a + k]:
                    same_a.add(blk.a + k)
                    same_b.add(blk.b + k)
        context.update({
            'pair': pair, 'tab': 'similarity', 'can_edit': True,
            'lines_a': [(i + 1, t, i in same_a) for i, t in enumerate(a)],
            'lines_b': [(i + 1, t, i in same_b) for i, t in enumerate(b)],
            'same_count': len(same_a), 'back_url': reverse('contest_similarity', args=(self.object.key,)),
        })
        return context


class ContestSimilarityAction(ContestSimilarityMixin, SingleObjectMixin, View):
    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        pair = self.base_queryset().filter(pk=self.kwargs['sim_id']).first()
        if pair is None:
            raise Http404()
        action = request.POST.get('action')
        if action == 'dismiss':
            pair.status = ContestSimilarity.STATUS_DISMISSED
        elif action == 'restore':
            pair.status = ContestSimilarity.STATUS_SEEN
        else:
            raise Http404()
        pair.reviewed_by = request.profile
        pair.save(update_fields=['status', 'reviewed_by', 'updated'])
        nxt = request.POST.get('next', '')
        if not nxt or not url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}):
            nxt = reverse('contest_similarity', args=(self.object.key,))
        return HttpResponseRedirect(nxt)
