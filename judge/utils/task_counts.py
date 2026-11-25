from django.db.models import Q

from judge.models import Quiz


def visible_quiz_count(user):
    """Number of quizzes in the "all" tab of the quiz list for `user` (public practice sets and open exams)."""
    visible = Q(is_public=True, mode='practice')
    exams = Q(mode='exam', course__isnull=True)
    if user.is_authenticated:
        visible |= exams & (Q(organizations__member=user.profile) | Q(is_public=True, organizations__isnull=True))
    else:
        visible |= exams & Q(is_public=True, organizations__isnull=True)
    return Quiz.objects.filter(id__in=Quiz.objects.filter(visible).values('id')).count()
