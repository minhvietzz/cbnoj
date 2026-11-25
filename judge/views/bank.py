import copy
import logging
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

from judge.models import BankQuestion, BankTag, Quiz, Subject
from judge.utils.question_bank import add_to_bank, bank_to_marker_text, copy_to_quiz, count_duplicates, get_tags, \
    question_hash, split_tags
from judge.utils.quiz_import_plain import MAX_BYTES as PLAIN_MAX_BYTES, PlainImportError, parse_plain_file
from judge.utils.quiz_parser import QuizFormatError, parse_quiz_file, parse_quiz_lines
from judge.utils.views import TitleMixin
from judge.views.quiz import MAX_UPLOAD_BYTES, ManageForm, can_upload, make_slug

__all__ = ['BankList', 'BankAction', 'BankImport', 'BankImportConfirm', 'BankEdit', 'BankCompose',
           'BankImportPlain', 'BankImportPlainPreview']

COMPOSE_KEY = 'bank_compose'
IMPORT_KEY = 'bank_import'
PLAIN_KEY = 'bank_import_plain'
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


def warning_labels():
    return {
        'no_answer': _('No correct answer found: choose it below.'),
        'bad_answer': _('The answer given does not match the options: check it.'),
        'partial_answer': _('Only some statements have an answer: the others were set to false.'),
        'few_options': _('The number of options looks wrong for this type.'),
        'no_options': _('No options were found for this question.'),
        'figure': _('Has a picture or refers to one: pictures are not imported, add them by hand.'),
        'formula': _('Has a formula: check that it was read correctly.'),
    }


PLAIN_KINDS = ('single', 'tf4', 'short')


def kind_labels():
    return {'single': _('Single choice'), 'multi': _('Multiple choice'), 'tf4': _('True/False (4 statements)'),
            'short': _('Short answer')}


def apply_plain_edits(questions, post):
    """The draft questions with the teacher's edits from the preview form applied; deleted ones are dropped."""
    result = []
    for index, original in enumerate(questions):
        if post.get('del_%d' % index):
            continue
        q = copy.deepcopy(original)
        if 'text_%d' % index in post:
            q['text'] = post.get('text_%d' % index, '').strip()
        kind = post.get('kind_%d' % index)
        if kind in PLAIN_KINDS:
            q['kind'] = kind
        if q['kind'] in ('single', 'multi', 'tf4'):
            chosen = {int(i) for i in post.getlist('ok_%d' % index) if i.isdigit()}
            for position, option in enumerate(q['options']):
                option['correct'] = position in chosen
            if q['kind'] != 'tf4':
                q['kind'] = 'multi' if len(chosen) > 1 else 'single'
        else:
            raw = post.get('ans_%d' % index, '')
            q['answers'] = [a.strip() for a in raw.replace('\n', '|').split('|') if a.strip()]
        result.append(q)
    return result


def plain_problems(q):
    """Why a question cannot be saved yet (codes); empty list when it is fine."""
    problems = []
    if not q['text'].strip():
        problems.append(_('The question text is empty.'))
    if q['kind'] in ('single', 'multi'):
        if len(q['options']) < 2:
            problems.append(_('A choice question needs at least 2 options.'))
        elif not any(o['correct'] for o in q['options']):
            problems.append(_('Choose the correct option.'))
    elif q['kind'] == 'tf4':
        if len(q['options']) != 4:
            problems.append(_('A true/false question needs exactly 4 statements.'))
    elif not q['answers']:
        problems.append(_('Enter the accepted answer.'))
    return problems


def refresh_warnings(q):
    keep = [w for w in q.get('warn', []) if w in ('figure', 'formula')]
    if q['kind'] == 'short':
        if not q['answers']:
            keep.append('no_answer')
    else:
        if not q['options']:
            keep.append('no_options')
        elif not any(o['correct'] for o in q['options']) and q['kind'] != 'tf4':
            keep.append('no_answer')
        if q['kind'] != 'tf4' and len(q['options']) < 2 or q['kind'] == 'tf4' and len(q['options']) != 4:
            keep.append('few_options')
    q['warn'] = list(dict.fromkeys(keep))
    return q


class PlainUploadForm(forms.Form):
    file = forms.FileField()

    def clean_file(self):
        upload = self.cleaned_data['file']
        if upload.size > PLAIN_MAX_BYTES:
            raise forms.ValidationError(_('The file is larger than 10 MB.'))
        return upload


class BankImportPlain(BankAccessMixin, TitleMixin, TemplateView):
    """Step 1: upload an ordinary exam paper (.docx or text PDF). Nothing is written to the database."""
    template_name = 'bank/import_plain.html'

    def get_title(self):
        return _('Import an exam paper')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(self.tab_context())
        context.update({'form': kwargs.get('form') or PlainUploadForm(), 'error': kwargs.get('error'),
                        'max_mb': PLAIN_MAX_BYTES // 1024 // 1024})
        return context

    def post(self, request, *args, **kwargs):
        form = PlainUploadForm(request.POST, request.FILES)
        if not form.is_valid():
            return self.render_to_response(self.get_context_data(form=form))
        upload = form.cleaned_data['file']
        try:
            result = parse_plain_file(upload.name, upload.read())
        except PlainImportError as e:
            return self.render_to_response(self.get_context_data(form=form, error=str(e)))
        except Exception:
            logging.getLogger('judge.quiz').exception('plain import failed for %s', upload.name)
            return self.render_to_response(self.get_context_data(
                form=form, error=_('The file could not be read. Try saving it again as .docx.')))
        request.session[PLAIN_KEY] = {'questions': result['questions'], 'source': upload.name[:255],
                                      'format': result['format'], 'doc_warnings': result['doc_warnings'],
                                      'has_key': result['has_key']}
        return HttpResponseRedirect(reverse('bank_import_plain_preview'))


class BankImportPlainPreview(BankAccessMixin, TitleMixin, TemplateView):
    """Steps 2 and 3: review and fix what was recognised, then save (the only step that writes)."""
    template_name = 'bank/import_plain_preview.html'

    def get_title(self):
        return _('Review the imported questions')

    def get(self, request, *args, **kwargs):
        if not request.session.get(PLAIN_KEY):
            return HttpResponseRedirect(reverse('bank_import_plain'))
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        draft = self.request.session[PLAIN_KEY]
        questions = draft['questions']
        counts = {}
        for q in questions:
            counts[q['kind']] = counts.get(q['kind'], 0) + 1
        flagged = [(i + 1, q) for i, q in enumerate(questions) if q.get('warn')]
        form = kwargs.get('form') or {}
        context.update(self.tab_context())
        context.update({
            'draft': draft, 'questions': questions, 'counts': counts, 'flagged': flagged,
            'labels': warning_labels(), 'kinds': kind_labels(), 'form': form, 'problems': kwargs.get('problems', []),
            'subjects': list(Subject.objects.filter(is_active=True)),
            'default_subject': Subject.objects.filter(slug='tin-hoc').values_list('id', flat=True).first(),
            'tag_names': list(BankTag.objects.filter(group='topic').values_list('name', flat=True)[:300]),
        })
        return context

    def post(self, request, *args, **kwargs):
        draft = request.session.get(PLAIN_KEY)
        if not draft:
            return HttpResponseRedirect(reverse('bank_import_plain'))
        post = request.POST
        if post.get('action') == 'cancel':
            request.session.pop(PLAIN_KEY, None)
            return HttpResponseRedirect(reverse('bank_import_plain'))
        questions = [refresh_warnings(q) for q in apply_plain_edits(draft['questions'], post)]
        draft['questions'] = questions
        request.session[PLAIN_KEY] = draft          # edits stay in the session only; the database is untouched
        if post.get('action') != 'save':
            return self.render_to_response(self.get_context_data(form=post))
        problems = []
        for number, q in enumerate(questions, 1):
            for text in plain_problems(q):
                problems.append(_('Question %(n)d: %(why)s') % {'n': number, 'why': text})
        if not questions:
            problems.append(_('There are no questions left to save.'))
        subject = Subject.objects.filter(id=to_id(post.get('subject')), is_active=True).first()
        mode = post.get('mode') if post.get('mode') in ('bank', 'quiz') else 'bank'
        title = post.get('title', '').strip()[:200]
        if mode == 'quiz' and not title:
            problems.append(_('Enter a title for the quiz.'))
        if problems:
            return self.render_to_response(self.get_context_data(form=post, problems=problems))
        level = to_id(post.get('level'))
        level = level if level in (1, 2, 3) else 0
        for q in questions:
            q['level'] = level
        profile = request.user.profile
        with transaction.atomic():
            banks, added, skipped = add_to_bank(questions, profile, draft['source'], split_tags(post.get('tags', '')),
                                                subject=subject)
            quiz = None
            if mode == 'quiz':
                quiz = Quiz.objects.create(title=title, slug=make_slug(title), creator=profile, subject=subject,
                                           source_name=draft['source'], show_answers=True)
                unique, seen = [], set()
                for bank in banks:
                    if bank.id not in seen:
                        seen.add(bank.id)
                        unique.append(bank)
                copy_to_quiz(quiz, unique)
        request.session.pop(PLAIN_KEY, None)
        messages.success(request, _('%(added)d new questions were added to the question bank '
                                    '(%(skipped)d already existed).') % {'added': added, 'skipped': skipped})
        if quiz is not None:
            messages.success(request, _('Quiz created with %(n)d questions.') % {'n': quiz.questions.count()})
            return HttpResponseRedirect(quiz.get_absolute_url())
        return HttpResponseRedirect(reverse('bank_list'))


def to_id(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


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
