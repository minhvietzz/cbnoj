import json
import logging

from celery import shared_task
from django.conf import settings
from django.db import IntegrityError

from judge.models import ContestSimilarity, ContestSubmission, SubmissionFingerprint
from judge.utils import code_similarity as cs_

__all__ = ('check_submission_similarity', 'rebuild_contest_similarity')
logger = logging.getLogger('judge.celery')

MAX_OTHERS = 2000


def _fingerprint(submission):
    """Lấy (hoặc tạo) dấu vân tay của bài nộp. None nếu không hỗ trợ ngôn ngữ / bài quá ngắn."""
    try:
        fp = submission.fingerprint
    except SubmissionFingerprint.DoesNotExist:
        fp = None
    if fp is not None:
        return fp
    family = cs_.lang_family(submission.language.key)
    if not family:
        return None
    try:
        source = submission.source.source
    except Exception:
        return None
    struct, literal, tokens = cs_.compute(source, family)
    fp, _ = SubmissionFingerprint.objects.get_or_create(
        submission=submission,
        defaults={'family': family, 'tokens': tokens, 'struct': json.dumps(struct), 'literal': json.dumps(literal)})
    return fp


def _best_per_participation(contest_id, problem_id, exclude_participation_id=None):
    """Bài nộp tốt nhất (điểm cao nhất, mới nhất) của mỗi thí sinh thi trực tiếp cho bài này."""
    qs = (ContestSubmission.objects
          .filter(participation__contest_id=contest_id, participation__virtual=0, problem__problem_id=problem_id,
                  submission__points__gt=0)
          .select_related('submission__language')
          .order_by('submission__points', 'submission_id'))
    if exclude_participation_id is not None:
        qs = qs.exclude(participation_id=exclude_participation_id)
    best = {}
    for cs in qs.iterator():
        best[cs.participation_id] = cs      # sắp xếp tăng dần nên bản ghi sau thắng
    if len(best) > MAX_OTHERS:
        logger.warning('similarity: kỳ thi %s bài %s có %d thí sinh, chỉ so %d', contest_id, problem_id, len(best),
                       MAX_OTHERS)
        best = dict(list(best.items())[:MAX_OTHERS])
    return best


def _save_pair(contest_id, problem_id, cs, other_cs, score, literal, shared, rare, level):
    a, b = (cs, other_cs) if cs.participation_id < other_cs.participation_id else (other_cs, cs)
    key = dict(contest_id=contest_id, problem_id=problem_id,
               participation_a_id=a.participation_id, participation_b_id=b.participation_id)
    values = dict(submission_a_id=a.submission_id, submission_b_id=b.submission_id, score=score,
                  literal_score=literal, shared=shared, rare=rare, level=level)
    try:
        obj = ContestSimilarity.objects.filter(**key).first()
        if obj is None:
            ContestSimilarity.objects.create(**key, **values)
            return True
        # Đã có: chỉ cập nhật khi giống hơn. Nếu đã đánh dấu "không phải gian lận" thì chỉ mở lại khi tăng rõ rệt.
        if score > obj.score + 1e-9 or literal > obj.literal_score + 1e-9:
            reopen = obj.status != ContestSimilarity.STATUS_DISMISSED or score > obj.score + 0.05
            for k, v in values.items():
                setattr(obj, k, v)
            if reopen:
                obj.status = ContestSimilarity.STATUS_NEW
            obj.save()
            return reopen
    except IntegrityError:
        logger.info('similarity: cặp đã được tạo bởi tiến trình khác, bỏ qua')
    return False


def _check(submission_id):
    cs = (ContestSubmission.objects.filter(submission_id=submission_id)
          .select_related('participation', 'submission__language', 'problem').first())
    if cs is None or cs.participation.virtual != 0 or cs.submission.points <= 0:
        return 0
    contest_id, problem_id = cs.participation.contest_id, cs.problem.problem_id
    mine = _fingerprint(cs.submission)
    if mine is None:
        return 0
    my_struct, my_literal = json.loads(mine.struct), json.loads(mine.literal)
    if not my_struct:
        return 0
    others, others_cs = {}, {}
    for pid, ocs in _best_per_participation(contest_id, problem_id, cs.participation_id).items():
        ofp = _fingerprint(ocs.submission)
        if ofp is None or ofp.family != mine.family:
            continue
        others[pid] = (json.loads(ofp.struct), json.loads(ofp.literal))
        others_cs[pid] = ocs
    found = 0
    for pid, score, literal, shared, rare in cs_.compare_new(my_struct, my_literal, others):
        level = cs_.classify(score, literal)
        if level and _save_pair(contest_id, problem_id, cs, others_cs[pid], score, literal, shared, rare, level):
            found += 1
    return found


@shared_task(ignore_result=True)
def check_submission_similarity(submission_id):
    """Chạy ngay sau khi một bài nộp trong kỳ thi chấm xong (gọi từ judge/bridge/judge_handler.py)."""
    if not getattr(settings, 'CONTEST_SIMILARITY_ENABLED', True):
        return
    try:
        _check(submission_id)
    except Exception:
        logger.exception('similarity: lỗi khi kiểm tra bài nộp %s', submission_id)


@shared_task(ignore_result=True)
def rebuild_contest_similarity(contest_key):
    """Quét lại toàn bộ một kỳ thi (dùng cho kỳ thi đã diễn ra hoặc khi chỉnh ngưỡng)."""
    ids = (ContestSubmission.objects
           .filter(participation__contest__key=contest_key, participation__virtual=0, submission__points__gt=0)
           .order_by('submission_id').values_list('submission_id', flat=True))
    for sid in ids:
        check_submission_similarity(sid)
