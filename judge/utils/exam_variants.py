"""
Exam variants ("mã đề"): shuffled versions of one quiz, for printing and for handing out to online candidates.

A variant stores only ids: the order of question ids and, per question, the order of option ids. Questions and options
keep their identity, so grading (by option id) and statistics (by question id) work unchanged for every variant.

Rules of the shuffle:
  * questions move only inside their section; sections keep their order;
  * a reading passage and all the questions that share it stay together (the block moves as one, inner order kept);
  * options of single / multi questions are shuffled, except that "both A and B" / "all of the above" / "none of the
    above" style options keep their position; a question whose option text refers to letters is not shuffled at all
    (shuffling the others would make "both A and B" point to different answers);
  * tf4 statements stay a, b, c, d and short answer questions have nothing to shuffle.
"""
import random
import re
from math import ceil

from django.db import transaction
from django.utils.translation import gettext as _

__all__ = ['VariantError', 'generate_variants', 'save_variants', 'answer_distribution', 'answer_key',
           'next_codes', 'is_pinned_option', 'questions_in_order', 'variant_layout', 'estimate_pages',
           'assign_variant', 'apply_variant', 'shown_attempt', 'variant_is_stale', 'MIN_COUNT', 'MAX_COUNT']

MIN_COUNT, MAX_COUNT = 2, 12
TRIES_PER_VARIANT = 24          # random orders compared per variant; the most even answer distribution wins
EXTRA_TRIES = 200               # more tries when every order so far duplicated an earlier code
EVEN_TOLERANCE = 10.0           # a letter may differ from an even share by this many percentage points
CODE_RE = re.compile(r'^[A-Za-z0-9]{1,8}$')
LETTERS = 'ABCDEFGHIJ'

# "Both A and B", "All of the above", "None of the above" and their Vietnamese forms.
_LETTER_REF = re.compile(
    r'(\bboth\s+[a-j]\s+and\s+[a-j]\b|\b[a-j]\s+(?:and|va|và)\s+[a-j]\b.*\b(?:correct|right|đúng|dung)\b'
    r'|\bcả\s+[a-j]\b|\bca\s+[a-j]\b|\bcả\s+[a-j]\s*(?:và|,)|\b(?:đáp án|phương án)\s+[a-j]\s+(?:và|,)\s*[a-j]\b)')
_POSITIONAL = re.compile(
    r'(all of the above|none of the above|all the above|both of the above|neither of the above|'
    r'tất cả (?:các )?(?:đáp án|phương án|ý|câu)|cả hai|các đáp án trên|các phương án trên|'
    r'không có (?:đáp án|phương án) nào|không (?:đáp án|phương án) nào|đáp án khác|phương án khác|'
    r'tat ca (?:cac )?(?:dap an|phuong an)|khong co dap an nao)')


class VariantError(Exception):
    """A readable reason why variants cannot be generated or saved."""


# ------------------------------------------------------------------ codes

def next_codes(start_code, count):
    """'0101' -> ['0101', '0102', ...]; 'DE7' -> ['DE7', 'DE8', ...]; 'DE' -> ['DE1', 'DE2', ...]."""
    start_code = (start_code or '').strip()
    if not CODE_RE.match(start_code):
        raise VariantError(_('The starting code must be 1-8 letters or digits.'))
    match = re.search(r'(\d+)$', start_code)
    if match:
        prefix, digits = start_code[:match.start()], match.group(1)
        width, first = len(digits), int(digits)
        codes = [prefix + str(first + i).zfill(width) for i in range(count)]
    else:
        codes = ['%s%d' % (start_code, i + 1) for i in range(count)]
    if any(len(code) > 8 for code in codes):
        raise VariantError(_('The generated codes would be longer than 8 characters.'))
    return codes


# ------------------------------------------------------------------ shuffling

def _norm(text):
    return ' '.join((text or '').casefold().split())


def is_pinned_option(text):
    """Does this option text only make sense in a fixed position ("both A and B", "all of the above"...)?"""
    text = _norm(text)
    if len(text) > 70:
        return False
    return bool(_LETTER_REF.search(text) or _POSITIONAL.search(text))


def refers_to_letters(text):
    text = _norm(text)
    return len(text) <= 70 and bool(_LETTER_REF.search(text))


def _blocks_by_section(questions):
    """[[block, ...] per section] where a block is a list of questions that must stay adjacent."""
    sections = {}
    for question in questions:
        sections.setdefault(question.section, []).append(question)
    result = []
    for group in sections.values():
        blocks, last_passage = [], None
        for question in group:
            passage = (question.passage or '').strip()
            if passage and passage == last_passage:
                blocks[-1].append(question)
            else:
                blocks.append([question])
            last_passage = passage
        result.append(blocks)
    return result


def _shuffle_question_order(questions, rng):
    order = []
    for blocks in _blocks_by_section(questions):
        rng.shuffle(blocks)
        for block in blocks:
            order.extend(question.id for question in block)
    return order


def _original_question_order(questions):
    return [question.id for blocks in _blocks_by_section(questions) for block in blocks for question in block]


def _shuffle_options(question, rng):
    options = list(question.options.all())
    if question.kind not in ('single', 'multi') or len(options) < 2:
        return [o.id for o in options]
    if any(refers_to_letters(o.text) for o in options):
        return [o.id for o in options]
    pinned = {index for index, o in enumerate(options) if is_pinned_option(o.text)}
    movable = [o for index, o in enumerate(options) if index not in pinned]
    rng.shuffle(movable)
    movable = iter(movable)
    return [options[index].id if index in pinned else next(movable).id for index in range(len(options))]


def _can_shuffle(questions):
    return [q for q in questions if q.kind != 'section']


def _build(questions, rng, shuffle_questions, shuffle_options):
    fixed = [q for q in questions if q.kind == 'section']
    real = _can_shuffle(questions)
    order = _shuffle_question_order(real, rng) if shuffle_questions else _original_question_order(real)
    orders = {}
    for question in real:
        if shuffle_options:
            orders[str(question.id)] = _shuffle_options(question, rng)
        else:
            orders[str(question.id)] = [o.id for o in question.options.all()]
    if fixed:   # explicit heading rows (kind 'section') keep their original slot among the questions
        positions = {q.id: index for index, q in enumerate(questions)}
        for heading in fixed:
            order.insert(min(positions[heading.id], len(order)), heading.id)
    return order, orders


def _signature(order, orders):
    return (tuple(order), tuple(sorted((k, tuple(v)) for k, v in orders.items())))


# ------------------------------------------------------------------ answer key and distribution

def _correct_letters(question, option_ids):
    correct = {o.id for o in question.options.all() if o.is_correct}
    return [LETTERS[index] for index, option_id in enumerate(option_ids) if option_id in correct]


def answer_distribution(questions, option_orders):
    """
    {'A': n, 'B': n, ..., 'total': n, 'percent': {'A': %...}, 'deviation': pp, 'even': bool} counting every correct
    option of single / multi questions by the letter it gets in this variant.
    """
    counts = {letter: 0 for letter in 'ABCD'}
    total = 0
    for question in questions:
        if question.kind not in ('single', 'multi'):
            continue
        ids = option_orders.get(str(question.id)) or [o.id for o in question.options.all()]
        for letter in _correct_letters(question, ids):
            if letter in counts:
                counts[letter] += 1
                total += 1
    percent = {letter: (100.0 * counts[letter] / total if total else 0.0) for letter in counts}
    deviation = max((abs(p - 25.0) for p in percent.values()), default=0.0) if total else 0.0
    return dict(counts, total=total, percent=percent, deviation=deviation, even=deviation <= EVEN_TOLERANCE)


def answer_key(questions, question_order, option_orders):
    """Rows [{'number', 'question', 'kind', 'key'}] for the answer sheet of one variant."""
    by_id = {q.id: q for q in questions}
    true_letter = _('True')[:1].upper()
    false_letter = _('False')[:1].upper()
    rows, number = [], 0
    for question_id in question_order:
        question = by_id.get(question_id)
        if question is None or question.kind == 'section':
            continue
        number += 1
        ids = option_orders.get(str(question.id)) or [o.id for o in question.options.all()]
        if question.kind in ('single', 'multi'):
            key = ''.join(_correct_letters(question, ids))
        elif question.kind == 'tf4':
            by_option = {o.id: o for o in question.options.all()}
            key = ''.join(true_letter if by_option[i].is_correct else false_letter for i in ids if i in by_option)
        else:
            accepted = question.accepted_list()
            key = ' | '.join(accepted[:2]) if accepted else '-'
        rows.append({'number': number, 'question': question, 'kind': question.kind, 'key': key})
    return rows


# ------------------------------------------------------------------ generation

def _check_quiz(quiz, count):
    if not MIN_COUNT <= count <= MAX_COUNT:
        raise VariantError(_('The number of codes must be between 2 and 12.'))
    if quiz.questions_per_attempt:
        raise VariantError(_('This quiz draws a random subset of questions for every candidate, so exam codes '
                             '(which contain every question) cannot be used. Set "questions per attempt" to 0 first.'))
    questions = list(quiz.questions.prefetch_related('options'))
    if not [q for q in questions if q.kind != 'section']:
        raise VariantError(_('The quiz has no questions.'))
    return questions


def generate_variants(quiz, count, start_code='0101', seed=None, shuffle_questions=True, shuffle_options=True):
    """
    Returns [{'code', 'question_order', 'option_orders', 'seed', 'distribution'}] without saving anything.
    Raises VariantError if codes cannot be told apart or the quiz cannot have codes.
    """
    questions = _check_quiz(quiz, count)
    codes = next_codes(start_code, count)
    if not shuffle_questions and not shuffle_options:
        raise VariantError(_('Choose at least one thing to shuffle: the questions or the options.'))
    base = random.SystemRandom().randrange(1, 2 ** 31) if seed is None else int(seed)
    real = _can_shuffle(questions)
    seen, result = set(), []
    for index, code in enumerate(codes):
        best, tries = None, 0
        while tries < TRIES_PER_VARIANT + EXTRA_TRIES:
            rng = random.Random('%d/%d/%d' % (base, index, tries))
            tries += 1
            order, orders = _build(questions, rng, shuffle_questions, shuffle_options)
            if _signature(order, orders) in seen:
                continue
            dist = answer_distribution(real, orders)
            if best is None or dist['deviation'] < best[2]['deviation']:
                best = (order, orders, dist, tries - 1)
            if tries >= TRIES_PER_VARIANT and best is not None:
                break
        if best is None:
            raise VariantError(_('Could not make that many different codes: the quiz has too few questions or '
                                 'options to shuffle.'))
        order, orders, dist, used = best
        seen.add(_signature(order, orders))
        result.append({'code': code, 'question_order': order, 'option_orders': orders,
                       'seed': '%d/%d/%d' % (base, index, used), 'distribution': dist})
    return result


def save_variants(quiz, count, start_code='0101', seed=None, shuffle_questions=True, shuffle_options=True):
    """Replace the quiz's codes with freshly generated ones. Refused once a candidate has an attempt on a code."""
    from judge.models import ExamVariant, Quiz, QuizAttempt
    data = generate_variants(quiz, count, start_code, seed, shuffle_questions, shuffle_options)
    with transaction.atomic():
        Quiz.objects.select_for_update().get(pk=quiz.pk)
        if QuizAttempt.objects.filter(quiz=quiz, variant__isnull=False).exists():
            raise VariantError(_('Candidates already have attempts on the current exam codes, so they cannot be '
                                 'replaced. Reset or delete those attempts first.'))
        ExamVariant.objects.filter(quiz=quiz).delete()
        return [ExamVariant.objects.create(quiz=quiz, code=item['code'], question_order=item['question_order'],
                                           option_orders=item['option_orders']) for item in data]


# ------------------------------------------------------------------ reading a stored variant

def questions_in_order(variant, questions):
    """
    `questions` (with options prefetched) reordered as in `variant`; each gets `shown_options`. Questions or options
    added after the variant was made go last, in their normal order; deleted ones are skipped.
    """
    by_id = {q.id: q for q in questions}
    ordered = [by_id[i] for i in variant.question_order if i in by_id]
    placed = {q.id for q in ordered}
    ordered.extend(q for q in questions if q.id not in placed)
    for question in ordered:
        options = {o.id: o for o in question.options.all()}
        listed = [options[i] for i in (variant.option_orders or {}).get(str(question.id), []) if i in options]
        used = {o.id for o in listed}
        question.shown_options = listed + [o for o in question.options.all() if o.id not in used]
    return ordered


def variant_is_stale(variant, quiz):
    """True when the quiz's questions or options changed after the variant was made."""
    current = {q.id: sorted(o.id for o in q.options.all()) for q in quiz.questions.prefetch_related('options')}
    if set(current) != set(variant.question_order):
        return True
    return any(sorted(variant.option_orders.get(str(i), [])) != ids for i, ids in current.items()
               if ids or str(i) in variant.option_orders)


def variant_layout(variant):
    """Everything a print page needs: items [{'type': 'section'|'passage'|'question', ...}] in order."""
    quiz = variant.quiz
    questions = questions_in_order(variant, list(quiz.questions.prefetch_related('options')))
    items, number, last_section, last_passage = [], 0, None, None
    for question in questions:
        if question.kind == 'section':
            items.append({'type': 'section', 'title': question.text})
            last_section = question.text
            continue
        if question.section and question.section != last_section:
            items.append({'type': 'section', 'title': question.section})
        last_section = question.section or last_section
        passage = (question.passage or '').strip()
        if passage and passage != last_passage:
            items.append({'type': 'passage', 'text': passage})
        last_passage = passage
        number += 1
        items.append({'type': 'question', 'number': number, 'question': question,
                      'options': [{'label': LETTERS[i] if i < len(LETTERS) else str(i + 1), 'option': o}
                                  for i, o in enumerate(question.shown_options)]})
    return {'items': items, 'questions': questions, 'count': number}


def estimate_pages(questions):
    """Rough A4 page count (about 52 lines of text per page)."""
    lines = 4
    for question in questions:
        lines += ceil(len(question.text or '') / 95) + 1
        for option in question.options.all():
            lines += max(1, ceil(len(option.text or '') / 90))
        if question.kind == 'short':
            lines += 2
    return max(1, ceil(lines / 52))


# ------------------------------------------------------------------ online exam

def assign_variant(attempt):
    """
    Give a new attempt the least used exam code (ties broken by the attempt's seed). Does nothing if the quiz has no
    codes or draws a subset of its questions. Returns the variant or None.
    """
    from django.db.models import Count
    from judge.models import ExamVariant, Quiz
    quiz = attempt.quiz
    if quiz.questions_per_attempt:
        return None
    with transaction.atomic():
        Quiz.objects.select_for_update().get(pk=quiz.pk)   # one assignment at a time, so the split stays even
        variants = list(ExamVariant.objects.filter(quiz=quiz).annotate(used=Count('attempts')).order_by('code'))
        if not variants:
            return None
        fewest = min(v.used for v in variants)
        pool = [v for v in variants if v.used == fewest]
        variant = pool[random.Random(attempt.seed).randrange(len(pool))]
        attempt.variant = variant
        attempt.save(update_fields=['variant'])
    return variant


def apply_variant(attempt, questions):
    """
    Reorder `questions` (an attempt's drawn / ordered questions) by the attempt's variant, setting `shown_options`.
    Without a variant the list is returned untouched.
    """
    variant = attempt.variant if attempt.variant_id else None
    if variant is None:
        return questions
    return questions_in_order(variant, list(questions))


class _AttemptWithCode(object):
    """The attempt as the exam page sees it: same data, but the paper code is the exam code of its variant."""

    def __init__(self, attempt):
        self._attempt = attempt

    def __getattr__(self, name):
        return getattr(self._attempt, name)

    @property
    def exam_code(self):
        return self._attempt.variant.code


def shown_attempt(attempt):
    """`attempt` itself, or (when it has an exam code) a view of it whose `exam_code` is that code."""
    return _AttemptWithCode(attempt) if attempt.variant_id else attempt
