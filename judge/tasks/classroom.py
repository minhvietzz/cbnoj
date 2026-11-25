"""Reminders for class assignments (the bell in the navbar)."""
from datetime import timedelta

from celery import shared_task
from django.utils import timezone

from judge.models import ClassAssignment, make_notification
from judge.utils import classroom as stats

__all__ = ['remind_due_assignments']

REMIND_BEFORE = timedelta(hours=24)


@shared_task(ignore_result=True)
def remind_due_assignments():
    """Once per assignment, about a day before the deadline, remind the students who have not finished it."""
    now = timezone.now()
    due_soon = (ClassAssignment.objects.filter(reminded=False, due__gt=now, due__lte=now + REMIND_BEFORE,
                                               opens__lte=now).select_related('classroom'))
    for assignment in due_soon:
        # The flag is flipped first with a conditional update, so two overlapping runs cannot both send.
        if not ClassAssignment.objects.filter(pk=assignment.pk, reminded=False).update(reminded=True):
            continue
        ids = stats.student_ids(assignment.classroom)
        progress = stats.assignment_progress(assignment, ids)
        late = [pid for pid, p in progress.items() if p['done'] < 0.999]
        if late:
            due = timezone.localtime(assignment.due).strftime('%H:%M %d/%m')
            make_notification(late, title='Sắp đến hạn nộp bài',
                              body='%s: %s (hạn %s)' % (assignment.classroom.name, assignment.title, due),
                              url=assignment.get_absolute_url(), popup=True)
