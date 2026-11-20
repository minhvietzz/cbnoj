import logging

from celery import shared_task
from django.conf import settings
from django.core.mail import EmailMultiAlternatives, get_connection

__all__ = ('send_email_task',)
logger = logging.getLogger('judge.mail')


@shared_task(bind=True, max_retries=3, ignore_result=True)
def send_email_task(self, data):
    connection = get_connection(backend=settings.ASYNC_EMAIL_REAL_BACKEND)
    message = EmailMultiAlternatives(
        subject=data['subject'], body=data['body'], from_email=data['from_email'],
        to=data['to'], cc=data['cc'], bcc=data['bcc'], reply_to=data['reply_to'],
        headers=data['headers'], connection=connection,
    )
    message.content_subtype = data['content_subtype']
    for content, mimetype in data['alternatives']:
        message.attach_alternative(content, mimetype)
    try:
        message.send()
    except Exception as exc:
        logger.warning('Failed to send mail to %s: %s', data['to'], exc)  # noqa: G200
        raise self.retry(exc=exc, countdown=30)
