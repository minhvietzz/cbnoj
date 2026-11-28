"""Classes ("lớp") inside the school. A class belongs to an organization (optional) and has members with roles.

Courses, contests and quizzes keep working as before; later phases attach them to classes.
"""
from django.core.validators import RegexValidator
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from judge.models.profile import Organization, Profile

__all__ = ['Subject', 'Classroom', 'ClassMember', 'RoleInClass', 'ClassAssignment', 'ClassAnnouncement']


class RoleInClass(models.TextChoices):
    STUDENT = 'ST', _('Student')
    ASSISTANT = 'AS', _('Assistant')
    TEACHER = 'TE', _('Subject teacher')
    HOMEROOM = 'HR', _('Homeroom teacher')


MANAGER_ROLES = (RoleInClass.HOMEROOM, RoleInClass.TEACHER)
STAFF_ROLES = (RoleInClass.HOMEROOM, RoleInClass.TEACHER, RoleInClass.ASSISTANT)


class Subject(models.Model):
    name = models.CharField(max_length=64, verbose_name=_('subject name'))
    slug = models.SlugField(max_length=64, unique=True, verbose_name=_('subject slug'),
                            validators=[RegexValidator('^[-a-zA-Z0-9]+$', _('Only alphanumeric and hyphens'))])
    order = models.PositiveIntegerField(default=0, verbose_name=_('order'))
    is_active = models.BooleanField(default=True, verbose_name=_('active'))

    class Meta:
        ordering = ('order', 'name')
        verbose_name = _('subject')
        verbose_name_plural = _('subjects')

    def __str__(self):
        return self.name


class Classroom(models.Model):
    name = models.CharField(max_length=64, verbose_name=_('class name'))
    slug = models.SlugField(max_length=64, unique=True, verbose_name=_('class slug'),
                            help_text=_('Class name shown in the URL'),
                            validators=[RegexValidator('^[-a-zA-Z0-9]+$', _('Only alphanumeric and hyphens'))])
    organization = models.ForeignKey(Organization, verbose_name=_('organization'), null=True, blank=True,
                                     on_delete=models.SET_NULL, related_name='classes',
                                     help_text=_('Optional. A class can also exist outside any organization.'))
    school_year = models.CharField(max_length=16, blank=True, default='', verbose_name=_('school year'),
                                   help_text=_('For example 2026-2027.'))
    subject = models.ForeignKey(Subject, verbose_name=_('subject'), null=True, blank=True,
                                on_delete=models.SET_NULL, related_name='classes')
    about = models.TextField(blank=True, verbose_name=_('class description'))
    join_code = models.CharField(max_length=12, blank=True, default='', verbose_name=_('join code'),
                                 help_text=_('Students who enter this code can join the class. Empty = disabled.'))
    is_archived = models.BooleanField(default=False, verbose_name=_('archived'))
    ranking_weights = models.JSONField(default=dict, blank=True, verbose_name=_('ranking weights'),
                                       help_text=_('Percent of the ranking score: {"code": 50, "quiz": 40, '
                                                   '"att": 10}. Empty = default.'))
    created = models.DateTimeField(auto_now_add=True, verbose_name=_('created'))

    class Meta:
        ordering = ('-school_year', 'name')
        verbose_name = _('class')
        verbose_name_plural = _('classes')

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse('class_detail', args=(self.slug,))

    @property
    def initial(self):
        return (self.name.strip()[:1] or '?').upper()

    def get_role(self, profile):
        if not profile:
            return None
        return ClassMember.objects.filter(classroom=self, user=profile).values_list('role', flat=True).first()

    def is_org_admin(self, user):
        return bool(user.is_authenticated and self.organization_id and
                    self.organization.admins.filter(id=user.profile.id).exists())

    def is_visible_to(self, user):
        if not user.is_authenticated:
            return False
        return user.is_superuser or self.is_org_admin(user) or self.get_role(user.profile) is not None

    def is_managed_by(self, user):
        """May add and remove members and change class settings."""
        if not user.is_authenticated:
            return False
        if user.is_superuser or self.is_org_admin(user):
            return True
        return self.get_role(user.profile) in MANAGER_ROLES

    def is_staffed_by(self, user):
        """Teachers and assistants: may see the grade book and warnings."""
        if not user.is_authenticated:
            return False
        if user.is_superuser or self.is_org_admin(user):
            return True
        return self.get_role(user.profile) in STAFF_ROLES

    def members_with_role(self, *roles):
        return Profile.objects.filter(class_roles__classroom=self, class_roles__role__in=roles) \
            .select_related('user').order_by('user__username')

    def get_students(self):
        return self.members_with_role(RoleInClass.STUDENT)

    def get_teachers(self):
        return self.members_with_role(RoleInClass.HOMEROOM, RoleInClass.TEACHER)


class ClassMember(models.Model):
    classroom = models.ForeignKey(Classroom, verbose_name=_('class'), on_delete=models.CASCADE,
                                  related_name='members')
    user = models.ForeignKey(Profile, verbose_name=_('user'), on_delete=models.CASCADE, related_name='class_roles')
    role = models.CharField(max_length=2, choices=RoleInClass.choices, default=RoleInClass.STUDENT,
                            verbose_name=_('role'))
    joined = models.DateTimeField(auto_now_add=True, verbose_name=_('joined'))

    class Meta:
        unique_together = ('classroom', 'user')
        verbose_name = _('class member')
        verbose_name_plural = _('class members')

    def __str__(self):
        return '%s in %s (%s)' % (self.user, self.classroom, self.role)


class ClassAssignment(models.Model):
    """Work given to a whole class with an optional deadline: some programming problems, or one quiz."""
    KIND_PROBLEM = 'problem'
    KIND_QUIZ = 'quiz'
    KIND_LESSON = 'lesson'
    KINDS = ((KIND_PROBLEM, _('Programming problems')), (KIND_QUIZ, _('Quiz')),
             (KIND_LESSON, _('Whole course lesson')))

    classroom = models.ForeignKey(Classroom, verbose_name=_('class'), on_delete=models.CASCADE,
                                  related_name='assignments')
    title = models.CharField(max_length=200, verbose_name=_('title'))
    kind = models.CharField(max_length=8, choices=KINDS, default=KIND_PROBLEM, verbose_name=_('type'))
    problems = models.ManyToManyField('judge.Problem', verbose_name=_('problems'), blank=True,
                                      related_name='class_assignments')
    quiz = models.ForeignKey('judge.Quiz', verbose_name=_('quiz'), null=True, blank=True, on_delete=models.CASCADE,
                             related_name='class_assignments')
    lesson = models.ForeignKey('judge.CourseLesson', verbose_name=_('course lesson'), null=True, blank=True,
                               on_delete=models.CASCADE, related_name='class_assignments',
                               help_text=_('A whole lesson: its problems and quizzes, including ones added later. '
                                           'For a list of problems it only records where they came from.'))
    description = models.TextField(blank=True, verbose_name=_('description'))
    opens = models.DateTimeField(default=timezone.now, verbose_name=_('opens'))
    due = models.DateTimeField(null=True, blank=True, verbose_name=_('due'))
    created_by = models.ForeignKey(Profile, verbose_name=_('created by'), null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name='+')
    created = models.DateTimeField(auto_now_add=True, verbose_name=_('created'))
    reminded = models.BooleanField(default=False, editable=False)

    class Meta:
        ordering = ('due', '-created')
        verbose_name = _('class assignment')
        verbose_name_plural = _('class assignments')

    def __str__(self):
        return '%s (%s)' % (self.title, self.classroom)

    def get_absolute_url(self):
        return reverse('class_assignments', args=(self.classroom.slug,))

    def get_problems(self):
        """Problems to solve: the chosen ones, or every problem of the lesson for a whole-lesson assignment."""
        if self.kind == self.KIND_LESSON:
            if self.lesson_id is None:
                return []
            return [lp.problem for lp in self.lesson.lesson_problems.select_related('problem').order_by('order', 'id')]
        return list(self.problems.all())

    def get_quizzes(self):
        """Quizzes to take: the chosen one, or the quizzes of the lesson for a whole-lesson assignment."""
        if self.kind == self.KIND_LESSON:
            return list(self.lesson.quizzes.order_by('title')) if self.lesson_id else []
        return [self.quiz] if self.kind == self.KIND_QUIZ and self.quiz_id else []

    @property
    def is_open(self):
        return self.opens <= timezone.now()

    @property
    def is_overdue(self):
        return self.due is not None and self.due < timezone.now()


class ClassAnnouncement(models.Model):
    classroom = models.ForeignKey(Classroom, verbose_name=_('class'), on_delete=models.CASCADE,
                                  related_name='announcements')
    author = models.ForeignKey(Profile, verbose_name=_('author'), null=True, on_delete=models.SET_NULL,
                               related_name='+')
    text = models.TextField(verbose_name=_('announcement'))
    pinned = models.BooleanField(default=False, verbose_name=_('pinned'))
    created = models.DateTimeField(auto_now_add=True, verbose_name=_('created'))

    class Meta:
        ordering = ('-pinned', '-created')
        verbose_name = _('class announcement')
        verbose_name_plural = _('class announcements')

    def __str__(self):
        return self.text[:60]
