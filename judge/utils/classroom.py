"""Numbers behind the class pages: assignment progress, ranking, grade book and warnings.

Every function takes plain profile ids, so the cost does not depend on how the page is drawn. A class has a few dozen
students, so the queries below stay small.
"""
from collections import defaultdict
from datetime import timedelta

from django.db.models import Max, Q
from django.db.models.functions import TruncDate
from django.utils import timezone

from judge.models import ClassAssignment, Classroom, Contest, Quiz, QuizAttempt, RoleInClass, Submission

DEFAULT_WEIGHTS = {'code': 50, 'quiz': 40, 'att': 10}
PERIODS = ('week', 'month', 'term', 'year')
INACTIVE_DAYS = 7


def student_ids(classroom):
    from judge.models import ClassMember
    return list(ClassMember.objects.filter(classroom=classroom, role=RoleInClass.STUDENT)
                .values_list('user_id', flat=True))


def class_weights(classroom):
    weights = dict(DEFAULT_WEIGHTS)
    raw = classroom.ranking_weights or {}
    for key in weights:
        try:
            value = float(raw.get(key, weights[key]))
        except (TypeError, ValueError):
            continue
        if value >= 0:
            weights[key] = value
    if sum(weights.values()) <= 0:
        return dict(DEFAULT_WEIGHTS)
    return weights


def assignment_progress(assignment, ids):
    """{profile id: {'done': 0..1, 'score': 0..10}} for the given students."""
    result = {pid: {'done': 0.0, 'score': 0.0} for pid in ids}
    if not ids:
        return result
    if assignment.kind == ClassAssignment.KIND_QUIZ:
        if assignment.quiz_id is None:
            return result
        rows = (QuizAttempt.objects.filter(quiz_id=assignment.quiz_id, user_id__in=ids, finished__isnull=False,
                                           invalidated=False)
                .values('user_id', 'score', 'max_score'))
        for row in rows:
            best = result[row['user_id']]
            frac = row['score'] / row['max_score'] if row['max_score'] else 0.0
            best['done'] = 1.0
            best['score'] = max(best['score'], round(10 * frac, 2))
        return result
    problems = {p.id: p.points for p in assignment.problems.all()}
    if not problems:
        return result
    rows = (Submission.objects.filter(user_id__in=ids, problem_id__in=list(problems), points__isnull=False)
            .values('user_id', 'problem_id').annotate(best=Max('points')))
    solved = defaultdict(float)
    ratio_sum = defaultdict(float)
    for row in rows:
        full = problems[row['problem_id']]
        ratio = min(1.0, row['best'] / full) if full else 0.0
        ratio_sum[row['user_id']] += ratio
        if ratio >= 0.999:
            solved[row['user_id']] += 1
    total = len(problems)
    for pid in ids:
        result[pid] = {'done': solved[pid] / total, 'score': round(10 * ratio_sum[pid] / total, 2)}
    return result


def grade_book(classroom, assignments, ids):
    """rows: {pid: {'cells': [score or None per assignment], 'average': float or None}}.

    A cell is None while the work is neither done nor overdue; an overdue empty cell counts as 0.
    """
    now = timezone.now()
    cells = {pid: [] for pid in ids}
    for assignment in assignments:
        progress = assignment_progress(assignment, ids)
        for pid in ids:
            p = progress[pid]
            if p['done'] > 0 or p['score'] > 0:
                cells[pid].append(p['score'])
            elif assignment.due is not None and assignment.due < now:
                cells[pid].append(0.0)
            else:
                cells[pid].append(None)
    rows = {}
    for pid, values in cells.items():
        got = [v for v in values if v is not None]
        rows[pid] = {'cells': values, 'average': round(sum(got) / len(got), 2) if got else None}
    return rows


# ---- ranking ---------------------------------------------------------------------------------------------------------

def period_start(period, now=None):
    now = timezone.localtime(now or timezone.now())
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == 'week':
        return midnight - timedelta(days=midnight.weekday())
    if period == 'month':
        return midnight.replace(day=1)
    school_year_start = midnight.replace(month=9, day=1)
    if school_year_start > midnight:
        school_year_start = school_year_start.replace(year=school_year_start.year - 1)
    if period == 'year':
        return school_year_start
    # term: first term Sep-Jan, second term Feb-Aug
    if midnight.month >= 9 or midnight.month == 1:
        return school_year_start
    return midnight.replace(month=2, day=1)


def _raw_scores(ids, start, end):
    code = defaultdict(float)
    for row in (Submission.objects.filter(user_id__in=ids, date__gte=start, date__lte=end, points__isnull=False)
                .values('user_id', 'problem_id').annotate(best=Max('points'))):
        code[row['user_id']] += row['best']
    quiz_best = {}
    attempts = QuizAttempt.objects.filter(user_id__in=ids, finished__gte=start, finished__lte=end,
                                          invalidated=False).values('user_id', 'quiz_id', 'score', 'max_score')
    for row in attempts:
        frac = row['score'] / row['max_score'] if row['max_score'] else 0.0
        key = (row['user_id'], row['quiz_id'])
        quiz_best[key] = max(quiz_best.get(key, 0.0), frac)
    quiz = defaultdict(float)
    for (pid, _quiz_id), frac in quiz_best.items():
        quiz[pid] += 10 * frac
    days = defaultdict(set)
    for row in (Submission.objects.filter(user_id__in=ids, date__gte=start, date__lte=end)
                .annotate(day=TruncDate('date')).values('user_id', 'day').distinct()):
        days[row['user_id']].add(row['day'])
    for row in (QuizAttempt.objects.filter(user_id__in=ids, started__gte=start, started__lte=end)
                .annotate(day=TruncDate('started')).values('user_id', 'day').distinct()):
        days[row['user_id']].add(row['day'])
    return code, quiz, {pid: len(d) for pid, d in days.items()}


def _scored(ids, weights, start, end):
    code, quiz, att = _raw_scores(ids, start, end)
    top = {'code': max(code.values(), default=0), 'quiz': max(quiz.values(), default=0),
           'att': max(att.values(), default=0)}
    total_weight = sum(weights.values())
    rows = {}
    for pid in ids:
        raw = {'code': code.get(pid, 0.0), 'quiz': quiz.get(pid, 0.0), 'att': float(att.get(pid, 0))}
        part = sum(weights[k] * (100 * raw[k] / top[k] if top[k] else 0.0) for k in raw)
        rows[pid] = {'raw': raw, 'total': round(part / total_weight, 1)}
    return rows


def _rank(rows, names):
    ordered = sorted(rows, key=lambda pid: (-rows[pid]['total'], names.get(pid, '')))
    ranks, last_total, last_rank = {}, None, 0
    for index, pid in enumerate(ordered, start=1):
        if rows[pid]['total'] != last_total:
            last_rank, last_total = index, rows[pid]['total']
        ranks[pid] = last_rank
    return ordered, ranks


def ranking(classroom, period='week', now=None):
    """Rows sorted by rank with the movement against the same ranking seven days earlier."""
    from judge.models import Profile
    now = now or timezone.now()
    period = period if period in PERIODS else 'week'
    ids = student_ids(classroom)
    names = dict(Profile.objects.filter(id__in=ids).values_list('id', 'user__username'))
    weights = class_weights(classroom)
    start = period_start(period, now)
    current = _scored(ids, weights, start, now)
    ordered, ranks = _rank(current, names)
    before = now - timedelta(days=7)
    if before > start:
        _o, old_ranks = _rank(_scored(ids, weights, start, before), names)
    else:
        old_ranks = {}
    out = []
    for pid in ordered:
        delta = old_ranks[pid] - ranks[pid] if pid in old_ranks else None
        out.append({'profile_id': pid, 'rank': ranks[pid], 'delta': delta, 'raw': current[pid]['raw'],
                    'total': current[pid]['total']})
    return out, weights, start


# ---- activity and warnings -------------------------------------------------------------------------------------------

def activity_by_day(ids, weeks=12, now=None):
    """{date: number of submissions and quiz attempts} for the last ``weeks`` weeks."""
    now = timezone.localtime(now or timezone.now())
    since = now - timedelta(weeks=weeks)
    counts = defaultdict(int)
    for row in (Submission.objects.filter(user_id__in=ids, date__gte=since)
                .annotate(day=TruncDate('date')).values('day')):
        counts[row['day']] += 1
    for row in (QuizAttempt.objects.filter(user_id__in=ids, started__gte=since)
                .annotate(day=TruncDate('started')).values('day')):
        counts[row['day']] += 1
    return counts


def heat_levels(counts, weeks=12, now=None):
    """A weeks x 7 grid (column = week, row = weekday) of levels 0..4, oldest week first."""
    now = timezone.localtime(now or timezone.now())
    today = now.date()
    first = today - timedelta(days=today.weekday()) - timedelta(weeks=weeks - 1)
    peak = max(counts.values(), default=0)
    cells = []
    for week in range(weeks):
        for weekday in range(7):
            day = first + timedelta(days=week * 7 + weekday)
            n = counts.get(day, 0) if day <= today else 0
            level = 0 if n == 0 or peak == 0 else min(4, 1 + int(3 * (n - 1) / max(peak - 1, 1)))
            cells.append(level)
    # Row-major for a 12-column grid: rows are weekdays, columns are weeks.
    return [cells[week * 7 + weekday] for weekday in range(7) for week in range(weeks)]


def inactive_students(classroom, ids=None, days=INACTIVE_DAYS, now=None):
    """Students with no submission or quiz attempt in the last ``days`` days (only meant for teachers)."""
    from judge.models import Profile
    now = now or timezone.now()
    ids = student_ids(classroom) if ids is None else ids
    since = now - timedelta(days=days)
    last = {}
    for row in Submission.objects.filter(user_id__in=ids).values('user_id').annotate(last=Max('date')):
        last[row['user_id']] = row['last']
    for row in QuizAttempt.objects.filter(user_id__in=ids).values('user_id').annotate(last=Max('started')):
        if row['user_id'] not in last or row['last'] > last[row['user_id']]:
            last[row['user_id']] = row['last']
    out = []
    for profile in Profile.objects.filter(id__in=ids).select_related('user').order_by('user__username'):
        seen = last.get(profile.id)
        if seen is None or seen < since:
            gap = (now - seen).days if seen else None
            out.append({'profile': profile, 'days': gap})
    return out


def missed_exams(classroom, ids=None, now=None):
    """{profile id: number of finished exams of this class the student never started}."""
    now = now or timezone.now()
    ids = student_ids(classroom) if ids is None else ids
    exams = list(Quiz.objects.filter(classes=classroom, mode='exam', end_time__lt=now).values_list('id', flat=True))
    missed = {}
    if not exams or not ids:
        return missed
    took = defaultdict(set)
    for quiz_id, user_id in QuizAttempt.objects.filter(quiz_id__in=exams, user_id__in=ids) \
            .values_list('quiz_id', 'user_id').distinct():
        took[user_id].add(quiz_id)
    for pid in ids:
        count = len(exams) - len(took[pid])
        if count:
            missed[pid] = count
    return missed


def needs_support(classroom, ids=None, limit=8, now=None):
    """Students who were silent for a week or skipped finished exams: ``{profile, days, missed, silent}`` rows."""
    from judge.models import Profile
    ids = student_ids(classroom) if ids is None else ids
    rows = {row['profile'].id: dict(row, missed=0, silent=True) for row in inactive_students(classroom, ids, now=now)}
    for pid, count in missed_exams(classroom, ids, now=now).items():
        if pid in rows:
            rows[pid]['missed'] = count
        else:
            rows[pid] = {'profile': Profile.objects.select_related('user').get(id=pid), 'days': 0, 'missed': count,
                         'silent': False}
    ordered = sorted(rows.values(), key=lambda r: (-(r['days'] if r['days'] is not None else 10 ** 6), -r['missed']))
    return ordered[:limit]


def upcoming_assignments(classroom, limit=5, now=None):
    now = now or timezone.now()
    return list(classroom.assignments.filter(due__isnull=False, due__gte=now, opens__lte=now).order_by('due')[:limit])


def todo_for(profile, limit=5, now=None):
    """Unfinished assignments of the classes this profile studies in, soonest deadline first."""
    now = now or timezone.now()
    classes = Classroom.objects.filter(members__user=profile, members__role=RoleInClass.STUDENT, is_archived=False)
    assignments = (ClassAssignment.objects.filter(classroom__in=classes, opens__lte=now)
                   .filter(Q(due__isnull=True) | Q(due__gte=now))
                   .select_related('classroom', 'quiz').prefetch_related('problems'))
    rows = []
    for assignment in assignments:
        progress = assignment_progress(assignment, [profile.id])[profile.id]
        if progress['done'] < 0.999:
            rows.append({'assignment': assignment, 'done': progress['done'], 'started': progress['done'] > 0})
    far = now + timedelta(days=3650)
    rows.sort(key=lambda r: (r['assignment'].due or far, r['assignment'].id))
    return rows[:limit]


def upcoming_exams(user, limit=3, days=21, now=None):
    """Exams the user can see that start soon: timed quizzes and contests, soonest first."""
    now = now or timezone.now()
    horizon = now + timedelta(days=days)
    items = []
    for quiz in Quiz.objects.filter(mode='exam', start_time__gt=now, start_time__lte=horizon).order_by('start_time'):
        if quiz.is_accessible_by(user):
            items.append({'name': quiz.title, 'url': quiz.get_absolute_url(), 'when': quiz.start_time,
                          'kind': 'quiz', 'minutes': quiz.time_limit})
    if user.is_authenticated:
        contests = Contest.get_visible_contests(user).filter(start_time__gt=now, start_time__lte=horizon)
    else:
        contests = Contest.objects.filter(is_visible=True, is_private=False, is_organization_private=False,
                                          start_time__gt=now, start_time__lte=horizon)
    for contest in contests.order_by('start_time')[:limit]:
        items.append({'name': contest.name, 'url': contest.get_absolute_url(), 'when': contest.start_time,
                      'kind': 'contest', 'minutes': int((contest.end_time - contest.start_time).total_seconds() // 60)})
    items.sort(key=lambda i: i['when'])
    return items[:limit]
