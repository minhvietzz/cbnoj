from django.db import models
from django.db.models import CASCADE, SET_NULL
from django.utils.translation import gettext_lazy as _

__all__ = ['SubmissionFingerprint', 'ContestSimilarity']


class SubmissionFingerprint(models.Model):
    """Dấu vân tay mã nguồn của một bài nộp (xem judge/utils/code_similarity.py)."""
    submission = models.OneToOneField('Submission', verbose_name=_('submission'), related_name='fingerprint',
                                      on_delete=CASCADE)
    family = models.CharField(max_length=8)
    tokens = models.PositiveIntegerField(default=0)
    struct = models.TextField(default='[]')    # JSON: danh sách băm cấu trúc (tên biến đã chuẩn hóa)
    literal = models.TextField(default='[]')   # JSON: danh sách băm giữ nguyên tên biến

    class Meta:
        verbose_name = _('submission fingerprint')
        verbose_name_plural = _('submission fingerprints')


class ContestSimilarity(models.Model):
    LEVEL_STRONG = 'strong'
    LEVEL_REVIEW = 'review'
    LEVELS = ((LEVEL_STRONG, _('very suspicious')), (LEVEL_REVIEW, _('needs review')))
    STATUS_NEW = 'new'
    STATUS_SEEN = 'seen'
    STATUS_DISMISSED = 'dismissed'
    STATUSES = ((STATUS_NEW, _('new')), (STATUS_SEEN, _('seen')), (STATUS_DISMISSED, _('not cheating')))

    contest = models.ForeignKey('Contest', verbose_name=_('contest'), related_name='similarities', on_delete=CASCADE)
    problem = models.ForeignKey('Problem', verbose_name=_('problem'), related_name='similarities',
                                on_delete=CASCADE)
    participation_a = models.ForeignKey('ContestParticipation', related_name='+', on_delete=CASCADE)
    participation_b = models.ForeignKey('ContestParticipation', related_name='+', on_delete=CASCADE)
    submission_a = models.ForeignKey('Submission', related_name='+', on_delete=CASCADE)
    submission_b = models.ForeignKey('Submission', related_name='+', on_delete=CASCADE)
    score = models.FloatField(verbose_name=_('structure similarity'))
    literal_score = models.FloatField(verbose_name=_('similarity incl. identifiers'))
    shared = models.PositiveIntegerField(default=0)
    rare = models.PositiveIntegerField(default=0)
    level = models.CharField(max_length=8, choices=LEVELS)
    status = models.CharField(max_length=10, choices=STATUSES, default=STATUS_NEW)
    reviewed_by = models.ForeignKey('Profile', null=True, blank=True, related_name='+', on_delete=SET_NULL)
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('contest', 'problem', 'participation_a', 'participation_b')
        index_together = [('contest', 'status')]
        verbose_name = _('contest similarity')
        verbose_name_plural = _('contest similarities')
