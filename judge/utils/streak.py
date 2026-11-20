from datetime import timedelta

from django.db.models.functions import TruncDate
from django.utils import timezone

from judge.models import Submission


def streak_info(profile, days_back=30):
    """
    Activity streak of one profile, counted in days that contain at least one AC submission.
    `current` still counts if the last AC day was yesterday, so the streak is not lost until a day is missed.
    """
    today = timezone.localdate()
    ac_days = set(Submission.objects.filter(user=profile, result='AC')
                  .annotate(day=TruncDate('date')).values_list('day', flat=True).distinct())

    cursor = today if today in ac_days else today - timedelta(days=1)
    current = 0
    while cursor in ac_days:
        current += 1
        cursor -= timedelta(days=1)

    best = run = 0
    previous = None
    for day in sorted(ac_days):
        run = run + 1 if previous is not None and day - previous == timedelta(days=1) else 1
        best = max(best, run)
        previous = day

    recent = [{'day': today - timedelta(days=i), 'ok': (today - timedelta(days=i)) in ac_days}
              for i in range(days_back - 1, -1, -1)]
    return {'current': current, 'best': max(best, current), 'today': today in ac_days, 'recent': recent,
            'days': ac_days}
