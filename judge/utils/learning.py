"""Numbers shown on the learning home page, the profile page and the course list (the "paper" interface).

Everything here is computed from real rows (submissions, quiz attempts, course roles, class members); nothing is
cached in the database. Functions take a Profile and return plain data, so the templates only format it.
"""
from collections import defaultdict
from datetime import timedelta

from django.db.models import Count, Max
from django.utils import timezone

from judge.models import (ClassMember, Course, CourseLesson, CourseRole, Problem, ProblemGroup, QuizAttempt,
                          RoleInClass, Submission)
from judge.utils import classroom as class_stats

SOLVED_TIERS = (500, 100, 50, 10)
STREAK_TIERS = (30, 7)


def week_average(profile, now=None, days=7):
    """Mean score on a 0..10 scale of the work done in the last ``days`` days, or None when there was none.

    Work = finished quiz attempts (score / max score) and programming problems submitted in the period (best points
    on that problem / full points). Every attempt and every problem counts once.
    """
    now = now or timezone.now()
    since = now - timedelta(days=days)
    fractions = []
    for row in (QuizAttempt.objects.filter(user=profile, finished__gte=since, finished__lte=now, invalidated=False)
                .values('score', 'max_score')):
        if row['max_score']:
            fractions.append(min(1.0, row['score'] / row['max_score']))
    best = (Submission.objects.filter(user=profile, date__gte=since, date__lte=now, points__isnull=False,
                                      problem__points__gt=0)
            .values('problem_id', 'problem__points').annotate(top=Max('points')))
    for row in best:
        fractions.append(min(1.0, row['top'] / row['problem__points']))
    if not fractions:
        return None
    return round(10 * sum(fractions) / len(fractions), 1)


def heat_grid(profile, weeks=12, now=None):
    """Cells of the activity grid, row-major (7 weekday rows x ``weeks`` columns).

    Each cell is {'level': 0..4, 'day': date, 'count': n}; days after today have count 0 and level 0.
    """
    now = timezone.localtime(now or timezone.now())
    counts = class_stats.activity_by_day([profile.id], weeks=weeks, now=now)
    levels = class_stats.heat_levels(counts, weeks=weeks, now=now)
    today = now.date()
    first = today - timedelta(days=today.weekday()) - timedelta(weeks=weeks - 1)
    cells = []
    for index, level in enumerate(levels):
        weekday, week = divmod(index, weeks)
        day = first + timedelta(days=week * 7 + weekday)
        cells.append({'level': level, 'day': day, 'count': counts.get(day, 0) if day <= today else 0})
    return cells


def topic_skills(profile, limit=6):
    """Topics (problem groups) the profile worked on most: solved problems / all public problems of the group."""
    public = {'problem__is_public': True, 'problem__is_organization_private': False}
    tried = dict(Submission.objects.filter(user=profile, **public).values_list('problem__group')
                 .annotate(n=Count('id')).order_by().values_list('problem__group', 'n'))
    if not tried:
        return []
    solved = dict(Submission.objects.filter(user=profile, result='AC', **public).values('problem__group')
                  .annotate(n=Count('problem', distinct=True)).order_by().values_list('problem__group', 'n'))
    totals = dict(Problem.objects.filter(is_public=True, is_organization_private=False, group__in=list(tried))
                  .values('group').annotate(n=Count('id')).order_by().values_list('group', 'n'))
    names = dict(ProblemGroup.objects.filter(id__in=list(tried)).values_list('id', 'full_name'))
    rows = []
    for group_id, attempts in tried.items():
        total = totals.get(group_id, 0)
        if not total:
            continue
        done = min(solved.get(group_id, 0), total)
        rows.append({'name': names.get(group_id, ''), 'solved': done, 'total': total, 'attempts': attempts,
                     'percent': int(round(100.0 * done / total))})
    rows.sort(key=lambda r: (-r['attempts'], -r['percent'], r['name']))
    return rows[:limit]


def earned_badges(profile, best_streak=0, solved=None):
    """Badges to show: those granted in the admin (Badge model) plus ones computed from the numbers.

    Returns [{'name', 'image', 'computed'}]; a computed badge appears only once it has been earned.
    """
    solved = profile.problem_count if solved is None else solved
    out = [{'name': badge.name, 'image': badge.mini or badge.full_size, 'computed': False}
           for badge in profile.badges.all()]
    for tier in STREAK_TIERS:
        if best_streak >= tier:
            out.append({'name': tier, 'kind': 'streak', 'image': '', 'computed': True})
            break
    for tier in SOLVED_TIERS:
        if solved >= tier:
            out.append({'name': tier, 'kind': 'solved', 'image': '', 'computed': True})
            break
    return out


def my_classes(profile):
    """Classes the profile belongs to: [{'classroom', 'role', 'is_student'}], newest school year first."""
    rows = (ClassMember.objects.filter(user=profile, classroom__is_archived=False).select_related('classroom')
            .order_by('-classroom__school_year', 'classroom__name'))
    labels = dict(RoleInClass.choices)
    return [{'classroom': m.classroom, 'role': labels.get(m.role, m.role), 'is_student': m.role == RoleInClass.STUDENT}
            for m in rows]


def course_progress_map(profile, courses):
    """{course id: {'solved', 'total', 'percent', 'lessons'}} over problems of the visible lessons of each course."""
    from judge.views.course import lesson_progress
    if profile is None or not courses:
        return {}
    ids = [c.id for c in courses]
    lessons = list(CourseLesson.objects.filter(course_id__in=ids, is_visible=True).order_by('order', 'id')
                   .prefetch_related('lesson_problems__problem'))
    progress = lesson_progress(profile, lessons)
    sums = defaultdict(lambda: {'solved': 0, 'total': 0, 'lessons': 0})
    for lesson in lessons:
        row = sums[lesson.course_id]
        row['lessons'] += 1
        row['solved'] += progress[lesson.id]['solved']
        row['total'] += progress[lesson.id]['total']
    out = {}
    for cid in ids:
        row = sums[cid]
        row['percent'] = int(round(100.0 * row['solved'] / row['total'])) if row['total'] else 0
        out[cid] = row
    return out


def continue_courses(profile, limit=3):
    """Courses the profile is enrolled in, most recently joined first, each with its progress."""
    roles = (CourseRole.objects.filter(user=profile).select_related('course').order_by('-id')[:limit])
    courses = [r.course for r in roles]
    progress = course_progress_map(profile, courses)
    return [{'course': c, 'progress': progress[c.id]} for c in courses]


def open_courses(limit=3, exclude=()):
    """Public, open courses with their lesson counts (for people who are not studying any course yet)."""
    qs = (Course.objects.filter(is_public=True, is_open=True).exclude(id__in=list(exclude))
          .annotate(n_lessons=Count('lessons')).order_by('-n_lessons', '-created'))
    return list(qs[:limit])


def nav_menu_orgs(user):
    """Organizations of the user for the "Organizations" drop-down: [{'org', 'role', 'initials', 'is_admin'}]."""
    if not getattr(user, 'is_authenticated', False):
        return []
    profile = user.profile
    admin_ids = set(profile.admin_of.values_list('id', flat=True))
    out = []
    for org in profile.organizations.all():
        short = (org.short_name or org.name or '?').strip()
        out.append({'org': org, 'is_admin': org.id in admin_ids, 'initials': short[:2].upper()})
    return out


def initials(name):
    """Two-letter avatar text: first letters of the first and last word ("Nguyễn Minh Anh" -> "NA")."""
    parts = (name or '').split()
    if not parts:
        return '?'
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


def nav_problem_count():
    """Number of public problems for the "Problems" menu entry (cached for five minutes)."""
    from django.core.cache import cache
    count = cache.get('nav_problem_count')
    if count is None:
        count = Problem.get_public_problems().count()
        cache.set('nav_problem_count', count, 300)
    return count
