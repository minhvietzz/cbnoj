"""
Grading rules shared by mock exams, practice and score recalculation.

This module deliberately knows nothing about Django models, so it can be unit tested without a database.
"""

# THPTQG 2025 "true/false" questions: points earned by the number of correctly judged statements (of 4).
TF4_LADDER = {0: 0.0, 1: 0.1, 2: 0.25, 3: 0.5, 4: 1.0}


def normalize_answer(text):
    return ' '.join((text or '').casefold().split())


def tf4_fraction(given, options):
    """
    given: {option id: True/False} - the candidate's verdict for each statement ("True" = Đúng).
    options: [(option id, statement is true)].
    Statements left unanswered count as wrong.
    """
    if not isinstance(given, dict) or not options:
        return 0.0
    verdicts = {}
    for key, value in given.items():
        try:
            verdicts[int(key)] = value in (True, 'T', 't', 'true', 'True', 1, '1')
        except (TypeError, ValueError):
            continue
    right = sum(1 for option_id, is_true in options
                if option_id in verdicts and verdicts[option_id] == bool(is_true))
    if len(options) == 4:
        return TF4_LADDER[right]
    return right / len(options) if right == len(options) else 0.0


def score_fraction(kind, given, accepted=(), options=()):
    """
    Returns the fraction (0..1) of a question's points earned.
    kind: 'single' / 'multi' / 'short' / 'tf4'
    given: list of option ids, {option id: bool} (tf4) or a string (short answer).
    accepted: accepted answers (short); options: [(option id, is_correct)].
    """
    if kind == 'short':
        text = normalize_answer(given if isinstance(given, str) else '')
        return 1.0 if text and text in {normalize_answer(a) for a in accepted} else 0.0
    if kind == 'tf4':
        return tf4_fraction(given, options)
    try:
        chosen = {int(x) for x in (given or [])}
    except (TypeError, ValueError):
        return 0.0
    correct = {option_id for option_id, is_correct in options if is_correct}
    return 1.0 if chosen and chosen == correct else 0.0


def is_answered(kind, given):
    if kind == 'short':
        return bool(isinstance(given, str) and given.strip())
    if kind == 'tf4':
        return isinstance(given, dict) and bool(given)
    return bool(given)
