from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from judge.models import BankQuestion, BankTag, Quiz, QuizQuestion, Subject
from judge.utils.question_bank import add_to_bank, question_hash

# Fixed names (not translated) so the same chapter tag is used whatever language the command runs in.
TRACK_NAMES = {'ict': 'Tin học ứng dụng', 'cs': 'Khoa học máy tính'}


def question_to_dict(question, tags):
    options = [{'text': o.text, 'correct': o.is_correct} for o in question.options.all()]
    return {'kind': question.kind, 'text': question.text, 'options': options if question.kind != 'short' else [],
            'answers': question.accepted_list() if question.kind == 'short' else [],
            'explanation': question.explanation, 'points': question.points, 'level': 0, 'tags': list(tags)}


class Command(BaseCommand):
    help = ('Copy the questions of existing quizzes (not personal practice sets) into the question bank, '
            'skipping questions that are already there (same content hash).')

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Only count, write nothing.')
        parser.add_argument('--quiz', action='append', default=[], metavar='SLUG',
                            help='Only this quiz (repeat the option for several).')
        parser.add_argument('--link', action='store_true',
                            help='Also link the quiz questions to their bank copy (so past attempts feed the mistake '
                                 'notebook and topic statistics). Off by default: it edits the quizzes.')
        parser.add_argument('--subject', default='', metavar='SLUG',
                            help='Subject slug for the new bank questions (default: the quiz subject, else tin-hoc).')

    def handle(self, *args, **options):
        dry = options['dry_run']
        subject_slug = options['subject']
        forced = None
        if subject_slug:
            forced = Subject.objects.filter(slug=subject_slug).first()
            if forced is None:
                raise CommandError('Subject %r does not exist.' % subject_slug)
        default_subject = Subject.objects.filter(slug='tin-hoc').first()
        quizzes = Quiz.objects.exclude(mode='personal').order_by('id')
        if options['quiz']:
            quizzes = quizzes.filter(slug__in=options['quiz'])
            missing = set(options['quiz']) - set(quizzes.values_list('slug', flat=True))
            if missing:
                raise CommandError('Unknown or personal quiz: %s' % ', '.join(sorted(missing)))
        total = {'quizzes': 0, 'seen': 0, 'added': 0, 'skipped': 0}
        seen_hashes = set()
        with transaction.atomic():
            for quiz in quizzes.select_related('subject'):
                subject = forced or quiz.subject or default_subject
                tag_names = [' '.join(quiz.title.split())[:40]]
                added = skipped = 0
                questions = [q for q in QuizQuestion.objects.filter(quiz=quiz).prefetch_related('options')
                             .order_by('order', 'id')]
                data = [question_to_dict(q, tag_names) for q in questions]
                if dry:
                    for item in data:
                        digest = question_hash(item)
                        if digest in seen_hashes or BankQuestion.objects.filter(content_hash=digest).exists():
                            skipped += 1
                        else:
                            added += 1
                            seen_hashes.add(digest)
                else:
                    _, added, skipped = add_to_bank(data, quiz.creator, quiz.title[:255], subject=subject)
                    if quiz.track in TRACK_NAMES:
                        track = BankTag.objects.filter(name__iexact=TRACK_NAMES[quiz.track]).first() or \
                            BankTag.objects.create(name=TRACK_NAMES[quiz.track], group='track')
                        for item in data:
                            bank = BankQuestion.objects.filter(content_hash=question_hash(item)).first()
                            if bank is not None:
                                bank.tags.add(track)
                    for question, item in zip(questions, data):
                        if options['link'] and question.bank_question_id is None:
                            bank = BankQuestion.objects.filter(content_hash=question_hash(item)).first()
                            if bank is not None:
                                QuizQuestion.objects.filter(id=question.id).update(bank_question=bank)
                total['quizzes'] += 1
                total['seen'] += len(data)
                total['added'] += added
                total['skipped'] += skipped
                self.stdout.write('%s: %d questions, %d %s, %d duplicates skipped' % (
                    quiz.slug, len(data), added, 'would be added' if dry else 'added', skipped))
            if dry:
                transaction.set_rollback(True)
        self.stdout.write('%s%d quizzes, %d questions: %d %s, %d duplicates skipped.' % (
            '[dry run] ' if dry else '', total['quizzes'], total['seen'], total['added'],
            'would be added' if dry else 'added', total['skipped']))
