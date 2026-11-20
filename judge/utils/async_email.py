import logging

from django.conf import settings
from django.core.mail import get_connection
from django.core.mail.backends.base import BaseEmailBackend

logger = logging.getLogger('judge.mail')


class AsyncEmailBackend(BaseEmailBackend):
    """Hand each message to a celery worker so web workers never wait on SMTP.

    Falls back to sending synchronously if a message has attachments or the broker is unreachable.
    """

    def send_messages(self, email_messages):
        from judge.tasks.email import send_email_task

        sent = 0
        sync_fallback = []
        for message in email_messages:
            if message.attachments:
                sync_fallback.append(message)
                continue
            data = {
                'subject': message.subject, 'body': message.body, 'from_email': message.from_email,
                'to': list(message.to), 'cc': list(message.cc), 'bcc': list(message.bcc),
                'reply_to': list(message.reply_to), 'headers': dict(message.extra_headers),
                'content_subtype': message.content_subtype,
                'alternatives': [(c, m) for c, m in getattr(message, 'alternatives', [])],
            }
            try:
                send_email_task.apply_async(args=(data,), expires=3600)
                sent += 1
            except Exception:
                logger.exception('Could not queue mail, sending synchronously')
                sync_fallback.append(message)
        if sync_fallback:
            real = get_connection(backend=settings.ASYNC_EMAIL_REAL_BACKEND, fail_silently=self.fail_silently)
            sent += real.send_messages(sync_fallback) or 0
        return sent
