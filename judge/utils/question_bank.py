import hashlib

from django.db import transaction

from judge.models import BankQuestion, BankTag, QuizOption, QuizQuestion
from judge.models.quiz import normalize_answer


def question_hash(q):
    """Identity of a question's content: same text + options + answers means the same question."""
    parts = [q['kind'], normalize_answer(q['text'])]
    options = sorted((normalize_answer(o['text']), bool(o['correct'])) for o in q.get('options', []))
    parts.extend('%s|%d' % option for option in options)
    parts.extend(sorted(normalize_answer(a) for a in q.get('answers', [])))
    return hashlib.sha1('\x1f'.join(parts).encode('utf-8')).hexdigest()


def get_tags(names):
    tags = []
    for name in names:
        name = ' '.join(name.split())[:40]
        if not name:
            continue
        tag = BankTag.objects.filter(name__iexact=name).first() or BankTag.objects.create(name=name)
        if tag not in tags:
            tags.append(tag)
    return tags


def split_tags(text):
    import re
    return [t for t in (x.strip() for x in re.split(r'[,;]', text or '')) if t]


@transaction.atomic
def add_to_bank(questions, profile, source='', extra_tags=(), subject=None):
    """
    Add parsed questions (see quiz_parser) to the bank, skipping duplicates.
    `subject` (a Subject) is set on new rows, and on existing ones that have none yet.
    Returns (banks, added, skipped): `banks` is aligned with `questions` (new or already-existing rows).
    """
    banks, added, skipped = [], 0, 0
    for q in questions:
        digest = question_hash(q)
        bank = BankQuestion.objects.filter(content_hash=digest).first()
        names = list(q.get('tags', [])) + list(extra_tags)
        if bank is None:
            bank = BankQuestion.objects.create(
                kind=q['kind'], text=q['text'], options=q['options'], accepted_answers='\n'.join(q['answers']),
                explanation=q['explanation'], points=q['points'], level=q.get('level', 0), source_name=source,
                creator=profile, content_hash=digest, subject=subject)
            added += 1
        else:
            skipped += 1
            if subject is not None and bank.subject_id is None:
                bank.subject = subject
                bank.save(update_fields=['subject'])
        if names:
            bank.tags.add(*get_tags(names))
        banks.append(bank)
    return banks, added, skipped


def count_duplicates(questions):
    hashes = [question_hash(q) for q in questions]
    existing = set(BankQuestion.objects.filter(content_hash__in=hashes).values_list('content_hash', flat=True))
    seen, duplicates_in_file = set(), 0
    for h in hashes:
        if h in seen:
            duplicates_in_file += 1
        seen.add(h)
    return len(existing), duplicates_in_file


def copy_to_quiz(quiz, bank_questions, points=None, start=1, sections=None):
    """
    Snapshot bank questions into a quiz. `points` maps bank id -> points override;
    `sections` maps a question kind -> section heading (e.g. {'tf4': 'Phần II'}).
    """
    points = points or {}
    sections = sections or {}
    for number, bank in enumerate(bank_questions, start):
        question = QuizQuestion.objects.create(
            quiz=quiz, order=number, kind=bank.kind, text=bank.text, section=sections.get(bank.kind, ''),
            points=points.get(bank.id, bank.points), explanation=bank.explanation,
            accepted_answers=bank.accepted_answers, bank_question=bank)
        for index, option in enumerate(bank.options, 1):
            QuizOption.objects.create(question=question, order=index, text=option['text'],
                                      is_correct=bool(option['correct']))


def bank_to_marker_text(bank):
    """Render a bank question in the upload format so it can be edited as plain text."""
    lines = ['[qus] ' + bank.text]
    if bank.kind == 'tf4':
        lines.append('[type] tf')
    for index, option in enumerate(bank.options):
        letter = chr(97 + index) if bank.kind == 'tf4' else chr(65 + index)
        lines.append('%s%s %s' % (letter, ')' if bank.kind == 'tf4' else '.', option['text']))
    if bank.kind == 'short':
        lines.append('[ans] ' + ' | '.join(bank.accepted_list()))
    else:
        letters = ', '.join(chr(65 + i) for i, o in enumerate(bank.options) if o['correct'])
        lines.append('[ans] ' + (letters or ('none' if bank.kind == 'tf4' else '')))
    if bank.explanation:
        lines.append('[exp] ' + bank.explanation)
    lines.append('[pts] %g' % bank.points)
    if bank.level:
        lines.append('[lvl] %d' % bank.level)
    tags = ', '.join(t.name for t in bank.tags.all())
    if tags:
        lines.append('[tag] ' + tags)
    return '\n'.join(lines)
