from django.core.management.base import BaseCommand

from judge.models import QuizAttempt


class Command(BaseCommand):
    help = ('Grade quiz attempts whose deadline has passed. Students who closed the browser would otherwise stay '
            '"in progress" forever. Run it every minute from cron.')

    def handle(self, *args, **options):
        done = 0
        pending = QuizAttempt.objects.filter(finished__isnull=True).select_related('quiz')
        for attempt in pending.iterator():
            if attempt.finish_if_expired():
                done += 1
        if options['verbosity'] > 0:
            self.stdout.write('Finalized %d attempt(s).' % done)
