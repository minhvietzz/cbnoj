import random
from datetime import timedelta

from django.core.validators import MinValueValidator, RegexValidator
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from judge.models.course import Course, CourseLesson
from judge.models.profile import Organization, Profile
from judge.utils import quiz_grading

__all__ = ['Quiz', 'QuizQuestion', 'QuizOption', 'QuizAttempt', 'QuizViolation', 'QuizTopicStat',
           'QuizProfileStat', 'BankTag', 'BankQuestion']

QUESTION_KINDS = (
    ('single', _('Single choice')),
    ('multi', _('Multiple choice')),
    ('short', _('Short answer')),
    ('tf4', _('True/False (4 statements)')),
)

QUIZ_MODES = (
    ('practice', _('Practice')),
    ('exam', _('Mock exam')),
    # A set of bank questions a student built for themselves on the practice page; visible to them only.
    ('personal', _('Personal practice')),
)

PROCTORING_LEVELS = (
    ('off', _('Off')),
    ('light', _('Light (block copy and right click)')),
    ('strict', _('Strict (fullscreen lock and monitoring)')),
)

RESULTS_RELEASE = (
    ('immediate', _('Right after submitting')),
    ('after_end', _('After the exam window closes')),
    ('manual', _('When the teacher publishes them')),
)

TRACKS = (
    ('', _('Not specified')),
    ('ict', _('Applied informatics')),
    ('cs', _('Computer science')),
)


def normalize_answer(text):
    return ' '.join((text or '').casefold().split())


class Quiz(models.Model):
    title = models.CharField(max_length=200, verbose_name=_('quiz title'))
    slug = models.SlugField(max_length=128, unique=True, verbose_name=_('quiz slug'),
                            validators=[RegexValidator('^[-a-zA-Z0-9]+$', _('Only alphanumeric and hyphens'))])
    description = models.TextField(verbose_name=_('description'), blank=True)
    time_limit = models.PositiveIntegerField(verbose_name=_('time limit (minutes)'), default=0,
                                             help_text=_('0 means no time limit.'))
    max_attempts = models.PositiveIntegerField(verbose_name=_('maximum attempts'), default=0,
                                               help_text=_('0 means unlimited attempts.'))
    questions_per_attempt = models.PositiveIntegerField(verbose_name=_('questions per attempt'), default=0,
                                                        help_text=_('Each attempt draws this many random questions '
                                                                    'from the quiz. 0 means all questions.'))
    shuffle_questions = models.BooleanField(verbose_name=_('shuffle questions'), default=False)
    shuffle_options = models.BooleanField(verbose_name=_('shuffle options'), default=False)
    show_answers = models.BooleanField(verbose_name=_('show correct answers after submitting'), default=True)
    is_public = models.BooleanField(verbose_name=_('publicly visible'), default=False)
    lesson = models.ForeignKey(CourseLesson, verbose_name=_('course lesson'), null=True, blank=True,
                               on_delete=models.SET_NULL, related_name='quizzes',
                               help_text=_('Optional. Members of the course can take it even if it is not public.'))
    creator = models.ForeignKey(Profile, verbose_name=_('creator'), null=True, blank=True,
                                on_delete=models.SET_NULL, related_name='created_quizzes')
    source_name = models.CharField(max_length=255, blank=True, verbose_name=_('source file'))
    created = models.DateTimeField(auto_now_add=True, verbose_name=_('created'))
    updated = models.DateTimeField(auto_now=True, verbose_name=_('updated'))

    mode = models.CharField(max_length=8, choices=QUIZ_MODES, default='practice', verbose_name=_('mode'),
                            db_index=True)
    course = models.ForeignKey(Course, verbose_name=_('course'), null=True, blank=True,
                               on_delete=models.SET_NULL, related_name='quizzes',
                               help_text=_('Required for mock exams: only members of the course can take them.'))
    organizations = models.ManyToManyField(Organization, verbose_name=_('organizations'), blank=True,
                                           related_name='quizzes',
                                           help_text=_('Optional. A mock exam without a course and with organizations '
                                                       'is open only to their members.'))
    track = models.CharField(max_length=3, choices=TRACKS, blank=True, default='', verbose_name=_('track'))
    start_time = models.DateTimeField(verbose_name=_('exam start'), null=True, blank=True,
                                      help_text=_('Mock exam only. Nobody can start before this time.'))
    end_time = models.DateTimeField(verbose_name=_('exam end'), null=True, blank=True,
                                    help_text=_('Mock exam only. Every attempt is closed at this time.'))
    proctoring = models.CharField(max_length=6, choices=PROCTORING_LEVELS, default='off',
                                  verbose_name=_('proctoring'))
    max_violations = models.PositiveIntegerField(verbose_name=_('violations before auto-submit'), default=3,
                                                 help_text=_('0 means never auto-submit.'))
    results_release = models.CharField(max_length=9, choices=RESULTS_RELEASE, default='immediate',
                                       verbose_name=_('release results'))
    results_published = models.BooleanField(verbose_name=_('results published'), default=False,
                                            help_text=_('Used when results are released manually.'))
    rules_text = models.TextField(verbose_name=_('exam rules'), blank=True)
    extra_minutes = models.PositiveIntegerField(verbose_name=_('extra minutes for everyone'), default=0,
                                                help_text=_('Added by a teacher during the exam, e.g. after an outage.'))
    seb_browser_key = models.CharField(max_length=64, blank=True, verbose_name=_('Safe Exam Browser key'),
                                       help_text=_('Optional. When set, the exam can only be taken in Safe Exam '
                                                   'Browser configured with this Browser Exam Key.'))

    class Meta:
        ordering = ('-created',)
        verbose_name = _('quiz')
        verbose_name_plural = _('quizzes')

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse('quiz_detail', args=(self.slug,))

    @property
    def question_count(self):
        return self.questions.count()

    @property
    def total_points(self):
        return sum(q.points for q in self.questions.all())

    @property
    def paper_size(self):
        """Number of questions in one attempt: the draw size, or every question when no draw is set."""
        count = self.questions.count()
        return min(self.questions_per_attempt, count) if self.questions_per_attempt else count

    @property
    def paper_points(self):
        """Points of one attempt (the average question value times the draw size when questions are drawn)."""
        points = [q.points for q in self.questions.all()]
        if not points or not self.questions_per_attempt or self.questions_per_attempt >= len(points):
            return sum(points)
        return sum(points) / len(points) * self.questions_per_attempt

    @property
    def is_exam(self):
        return self.mode == 'exam'

    @property
    def is_secured(self):
        """Attempts carry a per-page token and heartbeat (all mock exams and any proctored quiz)."""
        return self.is_exam or self.proctoring != 'off'

    @property
    def attempt_limit(self):
        """Allowed finished attempts per user; 0 means unlimited. A mock exam is taken once unless said otherwise."""
        if self.is_exam:
            return self.max_attempts or 1
        return self.max_attempts

    @property
    def effective_end(self):
        """Closing time including the minutes a teacher added for the whole room."""
        if self.end_time is None:
            return None
        return self.end_time + timedelta(minutes=self.extra_minutes)

    def phase(self, now=None):
        """'upcoming' / 'running' / 'ended' for mock exams; 'running' for everything else."""
        if not self.is_exam:
            return 'running'
        now = now or timezone.now()
        if self.start_time and now < self.start_time:
            return 'upcoming'
        end = self.effective_end
        if end and now >= end:
            return 'ended'
        return 'running'

    def answers_released(self):
        """
        The correct answers and explanations of a mock exam stay hidden until nobody can still be writing it,
        otherwise early finishers could pass them on. Always true for other quizzes.
        """
        if not self.is_exam:
            return True
        if self.phase() != 'ended':
            return False
        for attempt in self.attempts.filter(finished__isnull=True):
            attempt.finish_if_expired()
        return not self.attempts.filter(finished__isnull=True).exists()

    def results_visible_to(self, user):
        """May `user` see scores, ranking and answers of finished attempts?"""
        if self.is_manageable_by(user) or not self.is_exam or self.results_release == 'immediate':
            return True
        if self.results_release == 'after_end':
            return self.phase() == 'ended'
        return self.results_published

    def is_manageable_by(self, user):
        if not user.is_authenticated:
            return False
        if user.is_superuser:
            return True
        if self.course_id and self.course.is_editable_by(user):
            return True
        if self.pk and self.organizations.filter(admins=user.profile).exists():
            return True
        return user.has_perm('judge.add_quiz') and self.creator_id == user.profile.id

    def is_accessible_by(self, user):
        if self.is_manageable_by(user):
            return True
        if self.mode == 'personal':
            return user.is_authenticated and self.creator_id == user.profile.id
        if self.is_exam:
            # A mock exam in a course is for its members; one without a course follows is_public.
            if self.course_id:
                return self.course.is_accessible_by(user)
            if self.organizations.exists():
                return user.is_authenticated and self.organizations.filter(member=user.profile).exists()
            return self.is_public
        if self.is_public:
            return True
        if self.course_id and self.course.is_accessible_by(user):
            return True
        return bool(self.lesson_id and self.lesson.course.is_accessible_by(user))


class QuizQuestion(models.Model):
    quiz = models.ForeignKey(Quiz, verbose_name=_('quiz'), on_delete=models.CASCADE, related_name='questions')
    order = models.PositiveIntegerField(verbose_name=_('order'), default=1)
    kind = models.CharField(max_length=6, choices=QUESTION_KINDS, default='single', verbose_name=_('type'))
    section = models.CharField(max_length=60, blank=True, verbose_name=_('section'),
                               help_text=_('Optional heading such as "Part I"; consecutive questions share a section.'))
    passage = models.TextField(verbose_name=_('reading passage'), blank=True,
                               help_text=_('Optional shared text shown beside the question in the exam room. '
                                           'Consecutive questions with the same text share one passage.'))
    text = models.TextField(verbose_name=_('question'))
    points = models.FloatField(verbose_name=_('points'), default=1, validators=[MinValueValidator(0)])
    accepted_answers = models.TextField(verbose_name=_('accepted answers'), blank=True,
                                        help_text=_('Short answer only: one accepted answer per line.'))
    explanation = models.TextField(verbose_name=_('explanation'), blank=True)
    bank_question = models.ForeignKey('BankQuestion', verbose_name=_('bank question'), null=True, blank=True,
                                      on_delete=models.SET_NULL, related_name='used_in')

    class Meta:
        ordering = ('order', 'id')
        verbose_name = _('quiz question')
        verbose_name_plural = _('quiz questions')

    def __str__(self):
        return '%s #%d' % (self.quiz.title, self.order)

    def accepted_list(self):
        return [line.strip() for line in self.accepted_answers.splitlines() if line.strip()]

    def correct_option_ids(self):
        return {o.id for o in self.options.all() if o.is_correct}

    def score_fraction(self, given):
        """Fraction (0..1) of the question's points earned by `given`; see judge.utils.quiz_grading."""
        return quiz_grading.score_fraction(self.kind, given, accepted=self.accepted_list(),
                                           options=[(o.id, o.is_correct) for o in self.options.all()])

    def grade(self, given):
        """given: list of option ids, a {option id: bool} dict (tf4) or a string. True only for full marks."""
        return self.score_fraction(given) >= 1


class QuizOption(models.Model):
    question = models.ForeignKey(QuizQuestion, verbose_name=_('question'), on_delete=models.CASCADE,
                                 related_name='options')
    order = models.PositiveIntegerField(verbose_name=_('order'), default=1)
    text = models.TextField(verbose_name=_('option'))
    is_correct = models.BooleanField(verbose_name=_('correct'), default=False)

    class Meta:
        ordering = ('order', 'id')
        verbose_name = _('quiz option')
        verbose_name_plural = _('quiz options')

    def __str__(self):
        return '%s: %s' % (chr(64 + self.order), self.text[:40])

    @property
    def label(self):
        return chr(64 + self.order) if 1 <= self.order <= 26 else str(self.order)


class QuizAttempt(models.Model):
    quiz = models.ForeignKey(Quiz, verbose_name=_('quiz'), on_delete=models.CASCADE, related_name='attempts')
    user = models.ForeignKey(Profile, verbose_name=_('user'), on_delete=models.CASCADE,
                             related_name='quiz_attempts')
    started = models.DateTimeField(auto_now_add=True, verbose_name=_('started'))
    finished = models.DateTimeField(null=True, blank=True, verbose_name=_('finished'))
    seed = models.PositiveIntegerField(default=0)
    answers = models.JSONField(default=dict, blank=True)
    results = models.JSONField(default=dict, blank=True)
    score = models.FloatField(default=0)
    max_score = models.FloatField(default=0)
    correct_count = models.PositiveIntegerField(default=0)
    question_count = models.PositiveIntegerField(default=0)
    scores = models.JSONField(default=dict, blank=True, help_text=_('Points earned per question id.'))
    auto_submitted = models.BooleanField(default=False, verbose_name=_('auto-submitted'))
    invalidated = models.BooleanField(default=False, verbose_name=_('invalidated'),
                                      help_text=_('Excluded from rankings and statistics.'))
    violation_count = models.PositiveIntegerField(default=0, verbose_name=_('violations'))
    last_heartbeat = models.DateTimeField(null=True, blank=True)
    session_key = models.CharField(max_length=64, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=255, blank=True)
    extra_minutes = models.PositiveIntegerField(default=0, verbose_name=_('extra minutes'),
                                                help_text=_('Extra time granted to this candidate only.'))

    class Meta:
        ordering = ('-started',)
        verbose_name = _('quiz attempt')
        verbose_name_plural = _('quiz attempts')
        indexes = [
            models.Index(fields=['quiz', 'user'], name='quizattempt_quiz_user_idx'),
            models.Index(fields=['user', 'finished'], name='quizattempt_user_fin_idx'),
            models.Index(fields=['finished'], name='quizattempt_finished_idx'),
        ]

    def __str__(self):
        return '%s — %s' % (self.user, self.quiz)

    @property
    def exam_code(self):
        """Paper code shown to the candidate; derived from the shuffle seed, so it is stable per attempt."""
        return '%03d' % (100 + self.seed % 900)

    @property
    def deadline(self):
        quiz = self.quiz
        extra = timedelta(minutes=quiz.extra_minutes + self.extra_minutes)
        limits = []
        if quiz.time_limit:
            limits.append(self.started + timedelta(minutes=quiz.time_limit) + extra)
        if quiz.is_exam and quiz.end_time:
            limits.append(quiz.end_time + extra)
        return min(limits) if limits else None

    @property
    def is_finished(self):
        return self.finished is not None

    @property
    def is_expired(self):
        deadline = self.deadline
        return bool(deadline and timezone.now() > deadline)

    @property
    def seconds_left(self):
        deadline = self.deadline
        if not deadline:
            return None
        return max(0, int((deadline - timezone.now()).total_seconds()))

    @property
    def percent(self):
        return int(round(100 * self.score / self.max_score)) if self.max_score else 0

    def rng(self, salt):
        return random.Random(self.seed * 1000003 + salt)

    def drawn_questions(self):
        """The questions of this attempt: all of them, or a random draw fixed by the attempt's seed."""
        questions = list(self.quiz.questions.prefetch_related('options'))
        size = self.quiz.questions_per_attempt
        if size and size < len(questions):
            chosen = set(q.id for q in self.rng(1).sample(sorted(questions, key=lambda q: q.id), size))
            questions = [q for q in questions if q.id in chosen]
        return questions

    def ordered_questions(self):
        questions = self.drawn_questions()
        if self.quiz.shuffle_questions:
            # Shuffle inside each section so "Part I" / "Part II" headings stay in order.
            sections = {}
            for question in questions:
                sections.setdefault(question.section, []).append(question)
            rng = self.rng(0)
            questions = []
            for group in sections.values():
                rng.shuffle(group)
                questions.extend(group)
        for question in questions:
            options = list(question.options.all())
            if self.quiz.shuffle_options and question.kind != 'short':
                self.rng(question.id).shuffle(options)
            question.shown_options = options
        return questions

    def finish_if_expired(self):
        """Close the attempt if its deadline passed (answers saved so far are graded). True if it is finished."""
        if not self.finished and self.is_expired:
            self.finish(auto_submitted=True)
        return self.is_finished

    def finish(self, answers=None, auto_submitted=False):
        """Grade the attempt (once) and store the per-question outcome."""
        if self.finished:
            return
        if answers is not None:
            self.answers = answers
        score, maximum, correct, total, results, scores = 0.0, 0.0, 0, 0, {}, {}
        for question in self.drawn_questions():
            given = self.answers.get(str(question.id))
            fraction = question.score_fraction(given)
            earned = question.points * fraction
            maximum += question.points
            total += 1
            score += earned
            if fraction >= 1:
                correct += 1
            results[str(question.id)] = fraction >= 1
            scores[str(question.id)] = round(earned, 4)
        self.score, self.max_score = round(score, 2), round(maximum, 2)
        self.correct_count, self.question_count = correct, total
        self.results, self.scores = results, scores
        self.auto_submitted = auto_submitted
        self.finished = timezone.now()
        self.save()
        from judge.utils import quiz_stats  # imported here: quiz_stats needs the models
        quiz_stats.record_attempt(self)


class QuizViolation(models.Model):
    KINDS = (
        ('fullscreen_exit', _('Left fullscreen')),
        ('tab_hidden', _('Switched tab or window')),
        ('blur', _('Lost focus')),
        ('copy', _('Copy attempt')),
        ('paste', _('Paste attempt')),
        ('contextmenu', _('Right click')),
        ('print', _('Print attempt')),
        ('shortcut', _('Blocked shortcut')),
        ('devtools', _('Possible developer tools')),
        ('reload', _('Page reload')),
        ('second_session', _('Opened in another tab or device')),
        ('offline', _('Connection lost')),
    )
    # Kinds that count towards `max_violations`; the others are only recorded as evidence.
    COUNTED = frozenset({'fullscreen_exit', 'tab_hidden', 'second_session'})

    attempt = models.ForeignKey(QuizAttempt, verbose_name=_('attempt'), on_delete=models.CASCADE,
                                related_name='violations')
    kind = models.CharField(max_length=20, choices=KINDS, verbose_name=_('type'))
    detail = models.CharField(max_length=255, blank=True, verbose_name=_('detail'))
    counted = models.BooleanField(default=False)
    created = models.DateTimeField(auto_now_add=True, verbose_name=_('time'))

    class Meta:
        ordering = ('created', 'id')
        verbose_name = _('quiz violation')
        verbose_name_plural = _('quiz violations')

    def __str__(self):
        return '%s @ %s' % (self.get_kind_display(), self.created)


class QuizTopicStat(models.Model):
    """Per user and topic tag: how many questions were answered / answered correctly."""
    user = models.ForeignKey(Profile, verbose_name=_('user'), on_delete=models.CASCADE, related_name='quiz_topic_stats')
    tag = models.ForeignKey('BankTag', verbose_name=_('tag'), on_delete=models.CASCADE, related_name='user_stats')
    answered = models.PositiveIntegerField(default=0)
    correct = models.PositiveIntegerField(default=0)
    weighted_answered = models.FloatField(default=0, help_text=_('Questions weighted by difficulty.'))
    weighted_correct = models.FloatField(default=0)
    updated = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('user', 'tag')
        verbose_name = _('quiz topic statistic')
        verbose_name_plural = _('quiz topic statistics')

    @property
    def accuracy(self):
        return self.weighted_correct / self.weighted_answered if self.weighted_answered else 0.0


class QuizProfileStat(models.Model):
    """Per user summary used for rankings and the level shown to teachers."""
    LEVELS = (
        ('', _('Not rated')),
        ('weak', _('Weak')),
        ('average', _('Average')),
        ('good', _('Good')),
        ('excellent', _('Excellent')),
    )

    user = models.OneToOneField(Profile, verbose_name=_('user'), on_delete=models.CASCADE,
                                related_name='quiz_stat')
    practice_sessions = models.PositiveIntegerField(default=0, verbose_name=_('practice sessions'))
    exams_taken = models.PositiveIntegerField(default=0, verbose_name=_('mock exams taken'))
    questions_answered = models.PositiveIntegerField(default=0, verbose_name=_('questions answered'))
    questions_correct = models.PositiveIntegerField(default=0, verbose_name=_('questions correct'))
    avg_exam_score = models.FloatField(default=0, verbose_name=_('average exam score (/10)'))
    best_exam_score = models.FloatField(default=0, verbose_name=_('best exam score (/10)'))
    level = models.CharField(max_length=9, choices=LEVELS, blank=True, default='', verbose_name=_('level'))
    level_score = models.FloatField(default=0, verbose_name=_('level score (/10)'))
    updated = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('quiz user statistic')
        verbose_name_plural = _('quiz user statistics')
        ordering = ('-level_score',)

    def __str__(self):
        return str(self.user)


class BankTag(models.Model):
    GROUPS = (
        ('topic', _('Topic')),
        ('track', _('Track')),
    )

    name = models.CharField(max_length=40, unique=True, verbose_name=_('tag'))
    group = models.CharField(max_length=5, choices=GROUPS, default='topic', verbose_name=_('group'))

    class Meta:
        ordering = ('name',)
        verbose_name = _('question bank tag')
        verbose_name_plural = _('question bank tags')

    def __str__(self):
        return self.name


LEVELS = ((0, _('Unrated')), (1, _('Easy')), (2, _('Medium')), (3, _('Hard')))


class BankQuestion(models.Model):
    """A reusable question. Quizzes copy it, so editing or deleting a quiz never touches the bank."""
    kind = models.CharField(max_length=6, choices=QUESTION_KINDS, default='single', verbose_name=_('type'))
    text = models.TextField(verbose_name=_('question'))
    options = models.JSONField(default=list, blank=True, verbose_name=_('options'),
                               help_text=_('List of {"text": ..., "correct": true/false}'))
    accepted_answers = models.TextField(verbose_name=_('accepted answers'), blank=True)
    explanation = models.TextField(verbose_name=_('explanation'), blank=True)
    points = models.FloatField(verbose_name=_('points'), default=1, validators=[MinValueValidator(0)])
    level = models.PositiveSmallIntegerField(verbose_name=_('difficulty'), choices=LEVELS, default=0)
    tags = models.ManyToManyField(BankTag, verbose_name=_('tags'), blank=True, related_name='questions')
    source_name = models.CharField(max_length=255, blank=True, verbose_name=_('source file'))
    creator = models.ForeignKey(Profile, verbose_name=_('creator'), null=True, blank=True,
                                on_delete=models.SET_NULL, related_name='bank_questions')
    content_hash = models.CharField(max_length=40, unique=True, editable=False)
    created = models.DateTimeField(auto_now_add=True, verbose_name=_('created'))

    class Meta:
        ordering = ('-created', '-id')
        verbose_name = _('bank question')
        verbose_name_plural = _('question bank')

    def __str__(self):
        return self.text[:60]

    def is_manageable_by(self, user):
        if not user.is_authenticated:
            return False
        return user.is_superuser or (user.has_perm('judge.add_quiz') and self.creator_id == user.profile.id)

    def accepted_list(self):
        return [line.strip() for line in self.accepted_answers.splitlines() if line.strip()]

    @property
    def kind_label(self):
        return dict(QUESTION_KINDS)[self.kind]
