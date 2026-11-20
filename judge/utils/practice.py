"""Building personal practice sets from the question bank, and the mistake notebook ("sổ lỗi")."""
import random
from collections import defaultdict
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from judge.models import BankQuestion, BankTag, CourseRole, Quiz, QuizAttempt, QuizQuestion
from judge.utils.question_bank import copy_to_quiz

MIN_COUNT, MAX_COUNT, DEFAULT_COUNT = 5, 50, 20
MAX_MISTAKE_ATTEMPTS = 300   # only the latest attempts feed the notebook, so the page stays fast
KIND_GROUPS = {
    'choice': ('single', 'multi', 'short'),
    'tf': ('tf4',),
}


def can_practice(user):
    """Practice is for class members (and for staff who prepare the bank); it is not open to everyone."""
    if not user.is_authenticated:
        return False
    if user.is_superuser or user.has_perm('judge.add_quiz'):
        return True
    return CourseRole.objects.filter(user=user.profile).exists()


def tag_options():
    """Tags that have questions, split into tracks and topics: [(tag, question count)]."""
    from django.db.models import Count
    tags = BankTag.objects.annotate(n=Count('questions')).filter(n__gt=0).order_by('name')
    return ([t for t in tags if t.group == 'track'], [t for t in tags if t.group != 'track'])


def pick_questions(profile, tag_ids=(), track_ids=(), level=0, kinds='', count=DEFAULT_COUNT, prefer_new=True):
    """Random bank questions matching the filters. Questions the student never got right come first."""
    pool = BankQuestion.objects.all()
    if track_ids:
        pool = pool.filter(tags__id__in=track_ids)
    if tag_ids:
        pool = pool.filter(tags__id__in=tag_ids)
    if level in (1, 2, 3):
        pool = pool.filter(level=level)
    if kinds in KIND_GROUPS:
        pool = pool.filter(kind__in=KIND_GROUPS[kinds])
    ids = list(pool.values_list('id', flat=True).distinct())
    count = max(MIN_COUNT, min(MAX_COUNT, count))
    if prefer_new and len(ids) > count:
        known = right_before(profile)
        fresh = [i for i in ids if i not in known]
        if len(fresh) >= count:
            ids = fresh
        else:  # not enough unseen questions: take them all and fill up with ones already mastered
            seen = [i for i in ids if i in known]
            ids = fresh + random.sample(seen, count - len(fresh))
    picked = random.sample(ids, min(count, len(ids)))
    by_id = {q.id: q for q in BankQuestion.objects.filter(id__in=picked)}
    return [by_id[i] for i in picked]


def history(profile):
    """
    {bank question id: {'right': bool (latest result), 'wrong': times wrong, 'last_wrong': datetime}} over the
    student's finished attempts. Mock exam answers only count once the results were released to them.
    """
    attempts = list(QuizAttempt.objects.filter(user=profile, finished__isnull=False, invalidated=False)
                    .select_related('quiz').order_by('-finished')[:MAX_MISTAKE_ATTEMPTS])
    attempts = [a for a in reversed(attempts) if not a.quiz.is_exam or a.quiz.results_visible_to(profile.user)]
    mapping = {}
    for qid, bank_id in (QuizQuestion.objects.filter(quiz_id__in={a.quiz_id for a in attempts},
                                                     bank_question__isnull=False)
                         .values_list('id', 'bank_question_id')):
        mapping[qid] = bank_id
    state = defaultdict(lambda: {'right': True, 'wrong': 0, 'last_wrong': None})
    for attempt in attempts:   # oldest first, so the last write is the latest result
        for key, ok in attempt.results.items():
            bank_id = mapping.get(int(key))
            if bank_id is None:
                continue
            entry = state[bank_id]
            entry['right'] = bool(ok)
            if not ok:
                entry['wrong'] += 1
                entry['last_wrong'] = attempt.finished
    return state


def right_before(profile):
    return {bank_id for bank_id, e in history(profile).items() if e['right']}


def mistakes(profile):
    """The notebook: bank questions whose latest result is wrong, most recently missed first."""
    wrong = {bank_id: e for bank_id, e in history(profile).items() if not e['right']}
    banks = {b.id: b for b in BankQuestion.objects.filter(id__in=wrong).prefetch_related('tags')}
    rows = [{'bank': banks[i], 'wrong': e['wrong'], 'last_wrong': e['last_wrong']}
            for i, e in wrong.items() if i in banks]
    rows.sort(key=lambda r: r['last_wrong'], reverse=True)
    return rows


def unique_slug(base):
    slug, number = base, 2
    while Quiz.objects.filter(slug=slug).exists():
        slug = '%s-%d' % (base, number)
        number += 1
    return slug


@transaction.atomic
def create_session(profile, questions, title, minutes=0):
    """Snapshot `questions` into a private quiz of the student and start an attempt on it."""
    stamp = timezone.now().strftime('%y%m%d%H%M%S')
    quiz = Quiz.objects.create(
        title=title[:200], slug=unique_slug('luyen-tap-%d-%s' % (profile.id, stamp)), mode='personal',
        creator=profile, time_limit=minutes, shuffle_options=True, shuffle_questions=True, show_answers=True,
        is_public=False, source_name='practice')
    copy_to_quiz(quiz, questions)
    attempt = QuizAttempt.objects.create(quiz=quiz, user=profile, seed=random.randint(1, 2 ** 31 - 1))
    return quiz, attempt


def purge_unused(days=30):
    """Delete personal sets that were created but never finished; sets with results stay (statistics use them)."""
    cutoff = timezone.now() - timedelta(days=days)
    stale = Quiz.objects.filter(mode='personal', created__lt=cutoff).exclude(attempts__finished__isnull=False)
    count = stale.count()
    stale.delete()
    return count
