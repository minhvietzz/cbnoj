from django.core.management.base import BaseCommand

from judge.utils import practice


class Command(BaseCommand):
    help = ('Delete personal practice sets that were created but never finished. Sets with finished attempts are '
            'kept because the statistics and the mistake notebook are built from them.')

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=30, help='Only sets older than this many days (default 30).')

    def handle(self, *args, **options):
        count = practice.purge_unused(options['days'])
        if options['verbosity'] > 0:
            self.stdout.write('Deleted %d unused practice set(s).' % count)
