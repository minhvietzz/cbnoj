"""Notifications for the quiz / mock exam feature (the bell in the navbar).

* ``notify_upcoming_quizzes`` runs from celery beat every few minutes and tells the people who may take a mock
  exam that it starts soon (once per exam and start time).
* ``notify_quiz_results`` is queued when a teacher publishes the results of a quiz.
"""
from datetime import timedelta

import pytz
from celery import shared_task
from django.core.cache import cache
from django.utils import timezone

from judge.models import Notification, Profile, Quiz, make_notification

__all__ = ['notify_upcoming_quizzes', 'notify_quiz_results']

SOON = timedelta(minutes=30)
LOCAL_TZ = pytz.timezone('Asia/Ho_Chi_Minh')


def quiz_recipients(quiz):
    """Profiles that may take the quiz, as a queryset of ids."""
    if quiz.course_id:
        return quiz.course.get_students()
    if quiz.pk and quiz.classes.exists():
        return Profile.objects.filter(class_roles__classroom__in=quiz.classes.all(),
                                      class_roles__role='ST').distinct()
    if quiz.organizations.exists():
        return Profile.objects.filter(organizations__in=quiz.organizations.all()).distinct()
    if quiz.is_public:
        return Profile.objects.filter(user__is_active=True)
    return Profile.objects.none()


@shared_task(ignore_result=True)
def notify_upcoming_quizzes():
    now = timezone.now()
    upcoming = Quiz.objects.filter(mode='exam', start_time__gt=now, start_time__lte=now + SOON)
    for quiz in upcoming:
        # cache.add is atomic: only the first run for this exam and start time gets True.
        if not cache.add('quiz-start-notified:%d:%d' % (quiz.id, int(quiz.start_time.timestamp())), 1, 3 * 86400):
            continue
        recipients = list(quiz_recipients(quiz).values_list('id', flat=True))
        if not recipients:
            continue
        local_start = quiz.start_time.astimezone(LOCAL_TZ)
        body = '%s: bắt đầu lúc %s ngày %s (giờ Việt Nam)' % (quiz.title, local_start.strftime('%H:%M'),
                                                              local_start.strftime('%d/%m/%Y'))
        if quiz.time_limit:
            body += ', làm bài trong %d phút.' % quiz.time_limit
        else:
            body += '.'
        make_notification(recipients, title='Bài thi sắp bắt đầu', body=body, url=quiz.get_absolute_url(),
                          popup=True, priority=Notification.Priority.CONTEST_ANNOUNCEMENT)


@shared_task(ignore_result=True)
def notify_quiz_results(quiz_id):
    quiz = Quiz.objects.filter(id=quiz_id).first()
    if quiz is None or not quiz.results_published:
        return
    recipients = list(quiz.attempts.filter(finished__isnull=False, invalidated=False)
                      .values_list('user_id', flat=True).distinct())
    if not recipients:
        return
    make_notification(recipients, title='Đã có điểm bài thi', body='Điểm của bài "%s" đã được công bố.' % quiz.title,
                      url=quiz.get_absolute_url(), popup=True)
