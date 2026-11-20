from django.core.management.base import BaseCommand

from judge.utils import quiz_stats


class Command(BaseCommand):
    help = 'Recompute quiz topic statistics, user summaries and levels from the finished attempts.'

    def handle(self, *args, **options):
        users = quiz_stats.rebuild_all()
        if options['verbosity'] > 0:
            self.stdout.write('Rebuilt statistics for %d user(s).' % users)
