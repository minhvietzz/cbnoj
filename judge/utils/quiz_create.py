"""Creating or replacing a quiz from parsed questions. Shared by the upload view and the MCP tools."""
import unicodedata
from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from judge.models import Quiz, QuizOption, QuizQuestion
from judge.utils.question_bank import add_to_bank


def make_slug(title):
    text = title.replace('đ', 'd').replace('Đ', 'D')
    text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('ascii')
    base = slugify(text)[:100] or 'quiz'
    slug, counter = base, 2
    while Quiz.objects.filter(slug=slug).exists():
        slug = '%s-%d' % (base, counter)
        counter += 1
    return slug


def save_questions(quiz, questions, banks=None):
    for number, q in enumerate(questions, 1):
        question = QuizQuestion.objects.create(
            quiz=quiz, order=number, kind=q['kind'], text=q['text'], points=q['points'],
            section=q.get('section', ''), passage=q.get('passage', ''), explanation=q['explanation'], accepted_answers='\n'.join(q['answers']),  # noqa: E501
            bank_question=banks[number - 1] if banks else None)
        for index, option in enumerate(q['options'], 1):
            QuizOption.objects.create(question=question, order=index, text=option['text'],
                                      is_correct=option['correct'])


def apply_quiz(profile, questions, *, quiz=None, title='', description='', time_limit=0, max_attempts=0,
               shuffle_questions=False, shuffle_options=False, show_answers=True, is_public=False, lesson=None,
               source='', org=None, classroom=None, to_bank=False, bank_tags=()):
    """
    Create a quiz (``quiz=None``) or replace the questions and settings of ``quiz``.
    Callers must already have checked permissions. A new quiz made for a class or an organization becomes a
    private exam with a placeholder window (tomorrow) that the organizer adjusts on the manage page.
    Returns ``(quiz, bank_result)`` where bank_result is ``(added, skipped)`` or None.
    """
    replacing = quiz is not None
    with transaction.atomic():
        if replacing:
            quiz.questions.all().delete()
        else:
            quiz = Quiz(slug=make_slug(title), creator=profile)
        quiz.title = title
        quiz.description = description
        quiz.time_limit = time_limit
        quiz.max_attempts = max_attempts
        quiz.shuffle_questions = shuffle_questions
        quiz.shuffle_options = shuffle_options
        quiz.show_answers = show_answers
        quiz.is_public = is_public
        quiz.lesson = lesson
        quiz.source_name = source
        if not replacing and (classroom is not None or org is not None):
            start = timezone.now().replace(minute=0, second=0, microsecond=0) + timedelta(days=1)
            quiz.mode = 'exam'
            quiz.start_time = start
            quiz.end_time = start + timedelta(minutes=(time_limit or 45) + 15)
            quiz.is_public = False
        quiz.save()
        if not replacing:
            if classroom is not None:
                quiz.classes.add(classroom)
            elif org is not None:
                quiz.organizations.add(org)
        banks, bank_result = None, None
        if to_bank:
            banks, added, skipped = add_to_bank(questions, profile, source, list(bank_tags))
            bank_result = (added, skipped)
        save_questions(quiz, questions, banks)
    return quiz, bank_result
