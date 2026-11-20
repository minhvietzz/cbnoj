"""
Per-user quiz statistics, rankings and the level ("trình độ") shown to teachers.

Topic statistics are updated incrementally when an attempt is graded (and reverted when a teacher invalidates it);
`rebuild_all` recomputes everything from the attempts and is what the management command runs.
"""
import logging
from collections import defaultdict

from django.core.cache import cache
from django.db import transaction
from django.db.models import F

from judge.models import CourseRole, Profile, Quiz, QuizAttempt, QuizProfileStat, QuizQuestion, QuizTopicStat

logger = logging.getLogger('judge.quiz')

# A question counts more the harder it is; unrated questions count like easy ones.
LEVEL_WEIGHT = {0: 1.0, 1: 1.0, 2: 1.5, 3: 2.0}

# (upper bound exclusive, level) on the 0-10 scale
LEVEL_BANDS = ((5.0, 'weak'), (6.5, 'average'), (8.0, 'good'), (10.01, 'excellent'))
MIN_QUESTIONS_FOR_LEVEL = 20
RECENT_EXAMS = 3          # the level follows the latest mock exams most
EXAM_WEIGHT = 0.7         # share of the level score coming from those exams (the rest is topic accuracy)


def score10(score, max_score):
    return round(10.0 * score / max_score, 2) if max_score else 0.0


def level_for(value):
    for bound, name in LEVEL_BANDS:
        if value < bound:
            return name
    return 'excellent'


# ------------------------------------------------------------------------------------------ topic statistics

def _earned_fractions(attempt):
    """[(bank question, fraction earned 0..1)] for the attempt's questions that came from the question bank."""
    questions = (QuizQuestion.objects.filter(quiz_id=attempt.quiz_id, bank_question__isnull=False)
                 .select_related('bank_question').prefetch_related('bank_question__tags'))
    rows = []
    for question in questions:
        earned = attempt.scores.get(str(question.id))
        if earned is None:
            earned = question.points if attempt.results.get(str(question.id)) else 0
        rows.append((question.bank_question, min(1.0, earned / question.points) if question.points else 0.0))
    return rows


def _apply_topics(attempt, sign):
    totals = defaultdict(lambda: [0, 0.0, 0.0, 0.0])  # tag id -> answered, correct, weighted answered, weighted correct
    for bank, fraction in _earned_fractions(attempt):
        weight = LEVEL_WEIGHT.get(bank.level, 1.0)
        for tag in bank.tags.all():
            entry = totals[tag.id]
            entry[0] += 1
            entry[1] += 1 if fraction >= 1 else 0
            entry[2] += weight
            entry[3] += weight * fraction
    for tag_id, (answered, correct, w_answered, w_correct) in totals.items():
        stat, _created = QuizTopicStat.objects.get_or_create(user=attempt.user, tag_id=tag_id)
        if sign > 0:
            QuizTopicStat.objects.filter(pk=stat.pk).update(
                answered=F('answered') + answered, correct=F('correct') + correct,
                weighted_answered=F('weighted_answered') + w_answered,
                weighted_correct=F('weighted_correct') + w_correct)
        else:
            stat.answered = max(0, stat.answered - answered)
            stat.correct = max(0, stat.correct - correct)
            stat.weighted_answered = max(0.0, stat.weighted_answered - w_answered)
            stat.weighted_correct = max(0.0, stat.weighted_correct - w_correct)
            stat.save()


# ------------------------------------------------------------------------------------------ profile summary

def refresh_profile_stat(profile):
    """Recompute the user's summary row from their finished, non-invalidated attempts (cheap aggregates)."""
    attempts = list(QuizAttempt.objects.filter(user=profile, finished__isnull=False, invalidated=False)
                    .select_related('quiz').order_by('finished'))
    stat, _created = QuizProfileStat.objects.get_or_create(user=profile)
    exams = [a for a in attempts if a.quiz.is_exam]
    stat.practice_sessions = len(attempts) - len(exams)
    stat.exams_taken = len(exams)
    stat.questions_answered = sum(a.question_count for a in attempts)
    stat.questions_correct = sum(a.correct_count for a in attempts)
    exam_scores = [score10(a.score, a.max_score) for a in exams]
    stat.avg_exam_score = round(sum(exam_scores) / len(exam_scores), 2) if exam_scores else 0.0
    stat.best_exam_score = max(exam_scores, default=0.0)

    topics = QuizTopicStat.objects.filter(user=profile, weighted_answered__gt=0)
    weighted_answered = sum(t.weighted_answered for t in topics)
    weighted_correct = sum(t.weighted_correct for t in topics)
    topic_score = 10.0 * weighted_correct / weighted_answered if weighted_answered else None
    recent = exam_scores[-RECENT_EXAMS:]
    exam_score = sum(recent) / len(recent) if recent else None

    if stat.questions_answered < MIN_QUESTIONS_FOR_LEVEL or (exam_score is None and topic_score is None):
        stat.level, stat.level_score = '', 0.0
    else:
        if exam_score is not None and topic_score is not None:
            value = EXAM_WEIGHT * exam_score + (1 - EXAM_WEIGHT) * topic_score
        else:
            value = exam_score if exam_score is not None else topic_score
        stat.level_score = round(value, 2)
        stat.level = level_for(value)
    stat.save()
    return stat


def record_attempt(attempt):
    """Called when an attempt has just been graded. Never lets a statistics problem break a submission."""
    if attempt.invalidated or not attempt.finished:
        return
    invalidate_ranking(attempt.quiz_id)
    try:
        with transaction.atomic():
            _apply_topics(attempt, +1)
            refresh_profile_stat(attempt.user)
    except Exception:
        logger.exception('Could not update quiz statistics for attempt %s', attempt.pk)


def set_invalidated(attempt, invalidated):
    """Teacher action: take an attempt out of (or back into) rankings and statistics."""
    invalidate_ranking(attempt.quiz_id)
    if attempt.invalidated == invalidated or not attempt.finished:
        attempt.invalidated = invalidated
        attempt.save(update_fields=['invalidated'])
        return
    with transaction.atomic():
        attempt.invalidated = invalidated
        attempt.save(update_fields=['invalidated'])
        _apply_topics(attempt, -1 if invalidated else +1)
        refresh_profile_stat(attempt.user)


def reopen_attempt(attempt):
    """
    Undo an automatic submission (after an outage, once the deadline was extended): the attempt becomes
    "in progress" again with its saved answers, and its contribution to the statistics is taken back.
    """
    if not attempt.finished or attempt.invalidated:
        return False
    invalidate_ranking(attempt.quiz_id)
    with transaction.atomic():
        _apply_topics(attempt, -1)
        attempt.finished = None
        attempt.auto_submitted = False
        attempt.score = attempt.correct_count = 0
        attempt.results, attempt.scores = {}, {}
        attempt.session_key = ''      # whoever opens it next gets a fresh token
        attempt.save()
        refresh_profile_stat(attempt.user)
    return True


def rebuild_all(users=None):
    """Recompute every statistic from the attempts. Returns the number of users processed."""
    scope = QuizAttempt.objects.filter(finished__isnull=False, invalidated=False)
    if users is not None:
        scope = scope.filter(user__in=users)
        QuizTopicStat.objects.filter(user__in=users).delete()
    else:
        QuizTopicStat.objects.all().delete()
    done = set()
    for attempt in scope.select_related('quiz').order_by('finished').iterator():
        _apply_topics(attempt, +1)
        done.add(attempt.user_id)
    for profile in Profile.objects.filter(id__in=done):
        refresh_profile_stat(profile)
    return len(done)


def topic_breakdown(profile):
    """[(tag name, accuracy 0..1, answered)] weakest first, for the personal progress page."""
    rows = [(t.tag.name, t.accuracy, t.answered)
            for t in QuizTopicStat.objects.filter(user=profile, answered__gt=0).select_related('tag')]
    return sorted(rows, key=lambda row: (row[1], -row[2]))


# ------------------------------------------------------------------------------------------ rankings

def staff_ids(quiz):
    """Teachers and the author take exams too (to preview them) but must not appear in the ranking."""
    ids = set()
    if quiz.creator_id:
        ids.add(quiz.creator_id)
    if quiz.course_id:
        ids.update(CourseRole.objects.filter(course_id=quiz.course_id, role__in=('TE', 'AS'))
                   .values_list('user_id', flat=True))
    return ids


def exam_ranking(quiz):
    """
    One row per user (their best finished attempt), ordered by score then by time taken; equal score and time
    share a rank. Row: {'rank', 'user', 'attempt', 'score', 'max', 'score10', 'seconds'}.
    """
    skip = staff_ids(quiz)
    best = {}
    for attempt in (quiz.attempts.filter(finished__isnull=False, invalidated=False)
                    .select_related('user__user').order_by('-score', 'finished')):
        if attempt.user_id in skip or attempt.user_id in best:
            continue
        best[attempt.user_id] = attempt
    rows = []
    for attempt in best.values():
        seconds = int((attempt.finished - attempt.started).total_seconds())
        rows.append({'user': attempt.user, 'attempt': attempt, 'score': attempt.score, 'max': attempt.max_score,
                     'score10': score10(attempt.score, attempt.max_score), 'seconds': seconds})
    rows.sort(key=lambda r: (-r['score'], r['seconds'], r['user'].user.username))
    previous, rank = None, 0
    for position, row in enumerate(rows, 1):
        key = (row['score'], row['seconds'])
        if key != previous:
            rank, previous = position, key
        row['rank'] = rank
    return rows


RANK_TTL = 15   # seconds. The site's cache is per-process, so keep it short instead of relying on invalidation.


def _rank_key(quiz_id):
    return 'quiz-ranking-%d' % quiz_id


def invalidate_ranking(quiz_id):
    try:
        cache.delete(_rank_key(quiz_id))
    except Exception:
        logger.exception('Could not clear the cached ranking of quiz %s', quiz_id)


def cached_exam_ranking(quiz, fresh=False):
    """
    `exam_ranking`, with the ordering cached for RANK_TTL seconds. Only (rank, attempt id, seconds) is cached;
    rows are rebuilt from the database, so a cached entry can never show a stale score or name.
    """
    key = _rank_key(quiz.id)
    packed = None
    if not fresh:
        try:
            packed = cache.get(key)
        except Exception:
            packed = None
    if packed is not None:
        attempts = {a.id: a for a in QuizAttempt.objects.filter(id__in=[p[1] for p in packed])
                    .select_related('user__user')}
        rows = []
        for rank, attempt_id, seconds in packed:
            attempt = attempts.get(attempt_id)
            if attempt is None or attempt.invalidated or not attempt.finished:
                rows = None   # the cached order is out of date: recompute below
                break
            rows.append({'rank': rank, 'user': attempt.user, 'attempt': attempt, 'score': attempt.score,
                         'max': attempt.max_score, 'score10': score10(attempt.score, attempt.max_score),
                         'seconds': seconds})
        if rows is not None:
            return rows
    rows = exam_ranking(quiz)
    try:
        cache.set(key, [(r['rank'], r['attempt'].id, r['seconds']) for r in rows], RANK_TTL)
    except Exception:
        logger.exception('Could not cache the ranking of quiz %s', quiz.id)
    return rows


def score_distribution(rows, bins=10):
    """Histogram of 0-10 scores for the results page: [(low, high, count)]."""
    counts = [0] * bins
    for row in rows:
        counts[min(bins - 1, int(row['score10'] * bins / 10))] += 1
    width = 10 / bins
    return [(round(i * width, 1), round((i + 1) * width, 1), c) for i, c in enumerate(counts)]


def question_accuracy(quiz, rows):
    """[(question, percent of ranked candidates who got full marks, answered count)] in paper order."""
    attempts = [r['attempt'] for r in rows]
    result = []
    for question in quiz.questions.all():
        key = str(question.id)
        drawn = [a for a in attempts if key in a.results]  # with random draws, not every attempt saw every question
        correct = sum(1 for a in drawn if a.results.get(key))
        answered = sum(1 for a in drawn if key in a.answers and a.answers[key] not in ('', [], {}, None))
        percent = int(round(100.0 * correct / len(drawn))) if drawn else 0
        result.append((question, percent, answered))
    return result


MAX_HEATMAP_TOPICS = 12


def course_topic_matrix(course):
    """
    Class-wide strengths and weaknesses: {'tags': [(name, class accuracy % or None)],
    'rows': [(profile, [(accuracy % or None, answered) per tag])]}; topics with the most answers first.
    """
    students = list(course.get_students())
    stats = list(QuizTopicStat.objects.filter(user__in=students, answered__gt=0).select_related('tag'))
    totals = defaultdict(lambda: [0, 0.0, 0.0])    # tag id -> answered, weighted answered, weighted correct
    for stat in stats:
        entry = totals[stat.tag_id]
        entry[0] += stat.answered
        entry[1] += stat.weighted_answered
        entry[2] += stat.weighted_correct
    names = {stat.tag_id: stat.tag.name for stat in stats}
    tag_ids = sorted(totals, key=lambda t: -totals[t][0])[:MAX_HEATMAP_TOPICS]
    cells = {(stat.user_id, stat.tag_id): stat for stat in stats}
    rows = []
    for student in students:
        row = []
        for tag_id in tag_ids:
            stat = cells.get((student.id, tag_id))
            row.append((int(round(100 * stat.accuracy)), stat.answered) if stat else (None, 0))
        rows.append((student, row))
    header = [(names[t], int(round(100 * totals[t][2] / totals[t][1])) if totals[t][1] else None) for t in tag_ids]
    return {'tags': header, 'rows': rows}


def course_exam_trend(course):
    """[(quiz, candidates, average /10)] for the course's mock exams, oldest first."""
    result = []
    for quiz in Quiz.objects.filter(course=course, mode='exam').order_by('start_time', 'created'):
        skip = staff_ids(quiz)
        best = {}
        for attempt in quiz.attempts.filter(finished__isnull=False, invalidated=False).order_by('-score'):
            if attempt.user_id not in skip and attempt.user_id not in best:
                best[attempt.user_id] = attempt
        scores = [score10(a.score, a.max_score) for a in best.values()]
        result.append((quiz, len(scores), round(sum(scores) / len(scores), 2) if scores else None))
    return result


def course_report(course):
    """One row per student of the course with their mock exam results and level."""
    students = list(course.get_students())
    exam_ids = list(Quiz.objects.filter(course=course, mode='exam').values_list('id', flat=True))
    stats = {s.user_id: s for s in QuizProfileStat.objects.filter(user__in=students)}
    attempts = defaultdict(list)
    for attempt in (QuizAttempt.objects.filter(user__in=students, quiz_id__in=exam_ids, finished__isnull=False,
                                               invalidated=False).order_by('finished')):
        attempts[attempt.user_id].append(attempt)
    all_attempts = defaultdict(int)
    for user_id in (QuizAttempt.objects.filter(user__in=students, finished__isnull=False, invalidated=False)
                    .values_list('user_id', flat=True)):
        all_attempts[user_id] += 1
    rows = []
    for student in students:
        mine = attempts.get(student.id, [])
        scores = [score10(a.score, a.max_score) for a in mine]
        stat = stats.get(student.id)
        rows.append({
            'user': student, 'quizzes_done': all_attempts.get(student.id, 0), 'exams': len(mine),
            'avg': round(sum(scores) / len(scores), 2) if scores else None,
            'best': max(scores) if scores else None, 'last': scores[-1] if scores else None,
            'level': stat.level if stat else '', 'level_label': stat.get_level_display() if stat else '',
            'level_score': stat.level_score if stat else 0.0,
            'violations': sum(a.violation_count for a in mine),
        })
    rows.sort(key=lambda r: (-(r['avg'] if r['avg'] is not None else -1), r['user'].user.username))
    return rows
