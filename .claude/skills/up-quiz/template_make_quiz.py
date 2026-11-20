# Mẫu tạo quiz. Chạy: cd /home/vnojsite/site && /home/vnojsite/bin/python manage.py shell < file_nay.py
# Sửa SLUG, TITLE, dữ liệu MC / TF / SHORT trước khi chạy.
from django.db import transaction
from judge.models import Quiz, QuizQuestion, QuizOption

SLUG = 'kt-vi-du'
TITLE = 'KT ví dụ'
REF_SLUG = 'kt-giua-ki-11-hoa'     # quiz cùng loại để lấy người tạo (creator)
P1 = 'Phần I: Trắc nghiệm'
P2 = 'Phần II: Đúng / Sai'

# (nội dung, [các đáp án], số thứ tự đáp án đúng 1..n)  ; multi: dùng danh sách số, ví dụ [1, 3]
MC = [
    ('Ví dụ câu hỏi?', ['A1', 'B1', 'C1', 'D1'], 2),
]
# (nội dung chung, [(ý, đúng/sai), ...4 ý])
TF = []
# (nội dung, 'đáp án 1|đáp án 2')
SHORT = []

POINTS_MC, POINTS_TF, POINTS_SHORT = 0.25, 1.0, 0.25

with transaction.atomic():
    assert not Quiz.objects.filter(slug=SLUG).exists(), 'slug đã tồn tại'
    ref = Quiz.objects.get(slug=REF_SLUG)
    quiz = Quiz.objects.create(
        slug=SLUG, title=TITLE, creator=ref.creator,
        mode='exam', proctoring='strict', max_violations=3, time_limit=45, max_attempts=1,
        questions_per_attempt=0, shuffle_questions=True, shuffle_options=False,
        show_answers=True, results_release='after_end', is_public=True,
        source_name='tên-file-nguồn', description='Mô tả ngắn.')
    n = 0
    for text, opts, ans in MC:
        n += 1
        right = set(ans if isinstance(ans, (list, tuple)) else [ans])
        q = QuizQuestion.objects.create(quiz=quiz, order=n, kind='multi' if len(right) > 1 else 'single',
                                        section=P1, text=text, points=POINTS_MC)
        for j, t in enumerate(opts, 1):
            QuizOption.objects.create(question=q, order=j, text=t, is_correct=(j in right))
    for text, stmts in TF:
        n += 1
        q = QuizQuestion.objects.create(quiz=quiz, order=n, kind='tf4', section=P2, text=text, points=POINTS_TF)
        for j, (t, ok) in enumerate(stmts, 1):
            QuizOption.objects.create(question=q, order=j, text=t, is_correct=ok)
    for text, accepted in SHORT:
        n += 1
        QuizQuestion.objects.create(quiz=quiz, order=n, kind='short', text=text, points=POINTS_SHORT,
                                    accepted_answers=accepted)
print(quiz.id, quiz.slug, quiz.questions.count(), quiz.total_points)
