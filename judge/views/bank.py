import random

from django import forms
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Count
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.generic import FormView, ListView, TemplateView, View

from judge.models import BankQuestion, BankTag
from judge.utils.question_bank import add_to_bank, bank_to_marker_text, copy_to_quiz, count_duplicates, get_tags, \
    question_hash, split_tags
from judge.utils.quiz_parser import QuizFormatError, parse_quiz_file, parse_quiz_lines
from judge.utils.views import TitleMixin
from judge.views.quiz import MAX_UPLOAD_BYTES, ManageForm, can_upload, make_slug

__all__ = ['BankList', 'BankAction', 'BankImport', 'BankImportConfirm', 'BankEdit', 'BankCompose']

COMPOSE_KEY = 'bank_compose'
IMPORT_KEY = 'bank_import'
PAGE_SIZE = 20


class BankAccessMixin(LoginRequiredMixin):
    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not can_upload(request.user):
            raise PermissionDenied(_('You do not have permission to use the question bank.'))
        return super().dispatch(request, *args, **kwargs)

    def tab_context(self):
        return {'tab': 'bank', 'can_upload': True,
                'compose_count': len(self.request.session.get(COMPOSE_KEY, []))}


def safe_next(request, default):
    target = request.POST.get('next') or ''
    return target if target.startswith('/bank/') and not target.startswith('//') else default


class BankList(BankAccessMixin, TitleMixin, ListView):
    template_name = 'bank/list.html'
    context_object_name = 'questions'
    paginate_by = PAGE_SIZE

    def get_title(self):
        return _('Question bank')

    def filters(self):
        get = self.request.GET
        return {
            'q': get.get('q', '').strip(),
            'tag': get.get('tag', ''),
            'kind': get.get('kind', ''),
            'level': get.get('level', ''),
            'mine': get.get('mine', ''),
        }

    def get_queryset(self):
        f = self.filters()
        queryset = BankQuestion.objects.all()
        if f['q']:
            queryset = queryset.filter(text__icontains=f['q'])
        if f['tag'].isdigit():
            queryset = queryset.filter(tags__id=int(f['tag']))
        if f['kind'] in ('single', 'multi', 'short', 'tf4'):
            queryset = queryset.filter(kind=f['kind'])
        if f['level'] in ('0', '1', '2', '3'):
            queryset = queryset.filter(level=int(f['level']))
        if f['mine']:
            queryset = queryset.filter(creator=self.request.user.profile)
        return queryset.select_related('creator__user').prefetch_related('tags').distinct()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        f = self.filters()
        query = self.request.GET.copy()
        query.pop('page', None)
        context.update(self.tab_context())
        context.update({
            'f': f,
            'tags': BankTag.objects.annotate(n=Count('questions')).filter(n__gt=0).order_by('-n', 'name'),
            'total': BankQuestion.objects.count(),
            'filtered': self.get_queryset().count(),
            'page_prefix': '?%s&page=' % query.urlencode() if query else '?page=',
            'first_page_href': '?%s' % query.urlencode() if query else self.request.path,
            'next': self.request.get_full_path(),
        })
        return context


class BankAction(BankAccessMixin, View):
    http_method_names = ['post']

    def post(self, request, *args, **kwargs):
        action = request.POST.get('action')
        ids = [int(i) for i in request.POST.getlist('ids') if i.isdigit()]
        back = safe_next(request, reverse('bank_list'))
        if not ids and action != 'clear':
            messages.warning(request, _('Select at least one question first.'))
            return HttpResponseRedirect(back)
        questions = BankQuestion.objects.filter(id__in=ids)

        if action == 'compose':
            current = request.session.get(COMPOSE_KEY, [])
            for qid in [q.id for q in questions.order_by('id')]:
                if qid not in current:
                    current.append(qid)
            request.session[COMPOSE_KEY] = current
            return HttpResponseRedirect(reverse('bank_compose'))
        if action == 'delete':
            allowed = [q for q in questions if q.is_manageable_by(request.user)]
            for question in allowed:
                question.delete()
            messages.success(request, _('%(n)d questions deleted.') % {'n': len(allowed)})
            if len(allowed) < len(ids):
                messages.warning(request, _('You can only delete questions you added.'))
        elif action == 'tag':
            names = split_tags(request.POST.get('tag_name'))
            if not names:
                messages.warning(request, _('Enter a tag name.'))
            else:
                tags = get_tags(names)
                for question in questions:
                    question.tags.add(*tags)
                messages.success(request, _('Tags added to %(n)d questions.') % {'n': questions.count()})
        elif action == 'untag':
            tag = BankTag.objects.filter(id=request.POST.get('tag_id') or 0).first()
            if tag:
                for question in questions:
                    question.tags.remove(tag)
        return HttpResponseRedirect(back)


class ImportForm(forms.Form):
    file = forms.FileField(required=False)
    text = forms.CharField(required=False, widget=forms.Textarea(attrs={'rows': 10}))
    tags = forms.CharField(required=False, max_length=200)

    def clean(self):
        cleaned = super().clean()
        upload, text = cleaned.get('file'), (cleaned.get('text') or '').strip()
        self.parsed = None
        if upload and upload.size > MAX_UPLOAD_BYTES:
            self.add_error('file', _('The file is larger than 5 MB.'))
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


class BankImport(BankAccessMixin, TitleMixin, FormView):
    template_name = 'bank/import.html'
    form_class = ImportForm

    def get_title(self):
        return _('Import to question bank')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(self.tab_context())
        return context

    def form_valid(self, form):
        parsed = form.parsed
        context = {'form': form, 'parsed': parsed, 'title': self.get_title()}
        context.update(self.tab_context())
        if parsed['errors']:
            return render(self.request, 'bank/import.html', context)
        questions = parsed['questions']
        existing, in_file = count_duplicates(questions)
        self.request.session[IMPORT_KEY] = {'questions': questions, 'source': parsed['source'],
                                            'tags': form.cleaned_data['tags']}
        context.update({'questions': questions, 'existing': existing, 'in_file': in_file,
                        'new': max(0, len(questions) - existing - in_file)})
        return render(self.request, 'bank/import_preview.html', context)


class BankImportConfirm(BankAccessMixin, View):
    http_method_names = ['post']

    def post(self, request, *args, **kwargs):
        draft = request.session.pop(IMPORT_KEY, None)
        if not draft:
            return HttpResponseRedirect(reverse('bank_import'))
        banks, added, skipped = add_to_bank(draft['questions'], request.user.profile, draft['source'],
                                            split_tags(draft['tags']))
        messages.success(request, _('%(added)d new questions were added to the question bank '
                                    '(%(skipped)d already existed).') % {'added': added, 'skipped': skipped})
        return HttpResponseRedirect(reverse('bank_list'))


class BankEdit(BankAccessMixin, TitleMixin, TemplateView):
    template_name = 'bank/edit.html'

    def get_title(self):
        return _('Edit bank question')

    def get_object(self):
        bank = get_object_or_404(BankQuestion, id=self.kwargs['pk'])
        if not bank.is_manageable_by(self.request.user):
            raise PermissionDenied()
        return bank

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        bank = self.get_object()
        context.update(self.tab_context())
        context['bank'] = bank
        context.setdefault('text', bank_to_marker_text(bank))
        return context

    def post(self, request, *args, **kwargs):
        bank = self.get_object()
        text = request.POST.get('text', '')
        questions, errors, warnings = parse_quiz_lines(text.splitlines())
        problems = [_(e['message']) for e in errors]
        if not errors and len(questions) != 1:
            problems.append(_('Exactly one question is expected here.'))
        if not problems:
            q = questions[0]
            digest = question_hash(q)
            clash = BankQuestion.objects.filter(content_hash=digest).exclude(id=bank.id).first()
            if clash:
                problems.append(_('Another question in the bank is identical (#%(id)d).') % {'id': clash.id})
        if problems:
            context = self.get_context_data(text=text)
            context['problems'] = problems
            return self.render_to_response(context)
        with transaction.atomic():
            bank.kind, bank.text, bank.options = q['kind'], q['text'], q['options']
            bank.accepted_answers = '\n'.join(q['answers'])
            bank.explanation, bank.points, bank.level = q['explanation'], q['points'], q.get('level', 0)
            bank.content_hash = digest
            bank.save()
            bank.tags.set(get_tags(q.get('tags', [])))
        messages.success(request, _('Question saved.'))
        return HttpResponseRedirect(reverse('bank_list'))


class ComposeForm(ManageForm):
    pass


# A mock exam is laid out like the real paper: choice questions first, then the true/false part.
EXAM_SECTIONS = {'single': 'Phần I', 'multi': 'Phần I', 'short': 'Phần I', 'tf4': 'Phần II'}


class BankCompose(BankAccessMixin, TitleMixin, TemplateView):
    template_name = 'bank/compose.html'

    def get_title(self):
        return _('Build a quiz from the bank')

    def selected(self):
        ids = self.request.session.get(COMPOSE_KEY, [])
        found = {q.id: q for q in BankQuestion.objects.filter(id__in=ids).prefetch_related('tags')}
        ordered = [found[i] for i in ids if i in found]
        if len(ordered) != len(ids):
            self.request.session[COMPOSE_KEY] = [q.id for q in ordered]
        return ordered

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        selected = self.selected()
        form = kwargs.get('form') or ComposeForm(user=self.request.user, initial={
            'show_answers': True, 'time_limit': 0, 'max_attempts': 0})
        context.update(self.tab_context())
        context.update({
            'selected': selected, 'form': form,
            'total_points': round(sum(q.points for q in selected), 2),
            'tags': BankTag.objects.annotate(n=Count('questions')).filter(n__gt=0).order_by('-n', 'name'),
            'available': BankQuestion.objects.count(),
        })
        return context

    def post(self, request, *args, **kwargs):
        action = request.POST.get('action')
        current = request.session.get(COMPOSE_KEY, [])
        if action == 'remove':
            drop = {int(i) for i in request.POST.getlist('rm') if i.isdigit()}
            request.session[COMPOSE_KEY] = [i for i in current if i not in drop]
        elif action == 'clear':
            request.session[COMPOSE_KEY] = []
        elif action == 'random':
            return self.add_random(request, current)
        elif action == 'matrix':
            return self.add_matrix(request, current)
        elif action == 'create':
            return self.create(request)
        return HttpResponseRedirect(reverse('bank_compose'))

    @staticmethod
    def filtered_pool(request, exclude_ids):
        pool = BankQuestion.objects.exclude(id__in=exclude_ids)
        tag = request.POST.get('tag', '')
        if tag.isdigit():
            pool = pool.filter(tags__id=int(tag))
        if request.POST.get('kind') in ('single', 'multi', 'short', 'tf4'):
            pool = pool.filter(kind=request.POST['kind'])
        return pool

    def add_matrix(self, request, current):
        """Add N easy + N medium + N hard random questions in one go (tag and type filters are shared)."""
        labels = {1: _('easy'), 2: _('medium'), 3: _('hard')}
        picked, short = [], []
        for level in (1, 2, 3):
            try:
                wanted = max(0, min(200, int(request.POST.get('n%d' % level) or 0)))
            except ValueError:
                wanted = 0
            if not wanted:
                continue
            pool = self.filtered_pool(request, current + picked).filter(level=level)
            ids = list(pool.values_list('id', flat=True).distinct())
            got = random.sample(ids, min(wanted, len(ids)))
            picked += got
            if len(got) < wanted:
                short.append(_('%(level)s: %(got)d of %(wanted)d') % {
                    'level': labels[level], 'got': len(got), 'wanted': wanted,
                })
        if not picked and not short:
            messages.warning(request, _('Enter how many questions you want at each difficulty.'))
            return HttpResponseRedirect(reverse('bank_compose'))
        request.session[COMPOSE_KEY] = current + picked
        messages.success(request, _('%(n)d random questions added.') % {'n': len(picked)})
        if short:
            messages.warning(request, _('Not enough matching questions: %(details)s') % {'details': '; '.join(short)})
        return HttpResponseRedirect(reverse('bank_compose'))

    def add_random(self, request, current):
        try:
            count = max(1, min(200, int(request.POST.get('count', '10'))))
        except ValueError:
            count = 10
        pool = self.filtered_pool(request, current)
        if request.POST.get('level') in ('1', '2', '3'):
            pool = pool.filter(level=int(request.POST['level']))
        ids = list(pool.values_list('id', flat=True).distinct())
        picked = random.sample(ids, min(count, len(ids)))
        request.session[COMPOSE_KEY] = current + picked
        if len(picked) < count:
            messages.warning(request, _('Only %(n)d matching questions were available.') % {'n': len(picked)})
        else:
            messages.success(request, _('%(n)d random questions added.') % {'n': len(picked)})
        return HttpResponseRedirect(reverse('bank_compose'))

    def create(self, request):
        selected = self.selected()
        form = ComposeForm(request.POST, user=request.user)
        if not selected:
            messages.warning(request, _('Add some questions first.'))
            return HttpResponseRedirect(reverse('bank_compose'))
        if not form.is_valid():
            context = self.get_context_data(form=form)
            return self.render_to_response(context)
        points = {}
        for question in selected:
            try:
                value = float(request.POST.get('pts%d' % question.id, '').replace(',', '.'))
                if value >= 0:
                    points[question.id] = value
            except ValueError:
                pass
        quiz = form.save(commit=False)
        quiz.slug = make_slug(quiz.title)
        quiz.creator = request.user.profile
        if quiz.lesson and not quiz.lesson.course.is_editable_by(request.user):
            quiz.lesson = None
        quiz.source_name = _('Question bank')
        with transaction.atomic():
            quiz.save()
            if request.POST.get('shuffle_pick') == 'on':
                random.shuffle(selected)
            if quiz.is_exam:
                selected.sort(key=lambda q: q.kind == 'tf4')  # stable: keeps the chosen order inside each part
            copy_to_quiz(quiz, selected, points, sections=EXAM_SECTIONS if quiz.is_exam else None)
        request.session[COMPOSE_KEY] = []
        messages.success(request, _('Quiz created with %(n)d questions.') % {'n': len(selected)})
        return HttpResponseRedirect(quiz.get_absolute_url())
