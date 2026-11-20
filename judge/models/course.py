from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from judge.models.problem import Problem
from judge.models.profile import Profile

__all__ = ['Course', 'CourseRole', 'CourseLesson', 'CourseLessonProblem', 'RoleInCourse']


class RoleInCourse(models.TextChoices):
    STUDENT = 'ST', _('Student')
    ASSISTANT = 'AS', _('Assistant')
    TEACHER = 'TE', _('Teacher')


EDITABLE_ROLES = (RoleInCourse.TEACHER, RoleInCourse.ASSISTANT)


class Course(models.Model):
    name = models.CharField(max_length=128, verbose_name=_('course name'))
    slug = models.SlugField(max_length=128, unique=True, verbose_name=_('course slug'),
                            help_text=_('Course name shown in URL'),
                            validators=[RegexValidator('^[-a-zA-Z0-9]+$', _('Only alphanumeric and hyphens'))])
    about = models.TextField(verbose_name=_('course description'), blank=True)
    image_url = models.URLField(verbose_name=_('course image URL'), blank=True,
                                help_text=_('Optional. A letter is shown when empty.'))
    is_public = models.BooleanField(verbose_name=_('publicly visible'), default=False)
    is_open = models.BooleanField(verbose_name=_('public registration'), default=False,
                                  help_text=_('Anyone logged in can join without approval.'))
    created = models.DateTimeField(auto_now_add=True, verbose_name=_('created'))

    class Meta:
        ordering = ('-created', 'name')
        verbose_name = _('course')
        verbose_name_plural = _('courses')

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse('course_detail', args=(self.slug,))

    @property
    def initial(self):
        return (self.name.strip()[:1] or '?').upper()

    def get_role(self, profile):
        if not profile:
            return None
        role = CourseRole.objects.filter(course=self, user=profile).values_list('role', flat=True).first()
        return role

    def is_accessible_by(self, user):
        if not user.is_authenticated:
            return False
        if user.is_superuser:
            return True
        return CourseRole.objects.filter(course=self, user=user.profile).exists()

    def is_editable_by(self, user):
        if not user.is_authenticated:
            return False
        if user.is_superuser:
            return True
        return CourseRole.objects.filter(course=self, user=user.profile, role__in=EDITABLE_ROLES).exists()

    def is_visible_to(self, user):
        return self.is_public or self.is_accessible_by(user)

    def can_join(self, user):
        return (user.is_authenticated and self.is_public and self.is_open and
                not CourseRole.objects.filter(course=self, user=user.profile).exists())

    def get_teachers(self):
        return Profile.objects.filter(course_roles__course=self, course_roles__role=RoleInCourse.TEACHER) \
            .select_related('user')

    def get_students(self):
        return Profile.objects.filter(course_roles__course=self, course_roles__role=RoleInCourse.STUDENT) \
            .select_related('user').order_by('user__username')

    def get_lessons(self, include_hidden=False):
        lessons = self.lessons.all()
        if not include_hidden:
            lessons = lessons.filter(is_visible=True)
        return lessons.order_by('order', 'id')


class CourseRole(models.Model):
    course = models.ForeignKey(Course, verbose_name=_('course'), on_delete=models.CASCADE, related_name='roles')
    user = models.ForeignKey(Profile, verbose_name=_('user'), on_delete=models.CASCADE, related_name='course_roles')
    role = models.CharField(max_length=2, choices=RoleInCourse.choices, default=RoleInCourse.STUDENT,
                            verbose_name=_('role'))

    class Meta:
        unique_together = ('course', 'user')
        verbose_name = _('course member')
        verbose_name_plural = _('course members')

    def __str__(self):
        return '%s in %s (%s)' % (self.user, self.course, self.role)


class CourseLesson(models.Model):
    course = models.ForeignKey(Course, verbose_name=_('course'), on_delete=models.CASCADE, related_name='lessons')
    title = models.CharField(max_length=200, verbose_name=_('lesson title'))
    content = models.TextField(verbose_name=_('lesson content'), blank=True)
    order = models.PositiveIntegerField(verbose_name=_('order'), default=1, db_index=True)
    is_visible = models.BooleanField(verbose_name=_('publicly visible'), default=True)
    prerequisite = models.ForeignKey('self', verbose_name=_('prerequisite lesson'), null=True, blank=True,
                                     on_delete=models.SET_NULL, related_name='unlocks',
                                     help_text=_('Students must reach the required score in this lesson first.'))
    prerequisite_percent = models.PositiveSmallIntegerField(
        verbose_name=_('required score (%)'), default=60, validators=[MinValueValidator(1), MaxValueValidator(100)])

    class Meta:
        ordering = ('order', 'id')
        verbose_name = _('lesson')
        verbose_name_plural = _('lessons')

    def __str__(self):
        return '%s — %s' % (self.course.name, self.title)

    def get_absolute_url(self):
        return reverse('course_lesson', args=(self.course.slug, self.id))


class CourseLessonProblem(models.Model):
    lesson = models.ForeignKey(CourseLesson, verbose_name=_('lesson'), on_delete=models.CASCADE,
                               related_name='lesson_problems')
    problem = models.ForeignKey(Problem, verbose_name=_('problem'), on_delete=models.CASCADE,
                                related_name='course_lessons')
    order = models.PositiveIntegerField(verbose_name=_('order'), default=1)
    points = models.PositiveIntegerField(verbose_name=_('points in this lesson'), default=100,
                                         validators=[MinValueValidator(1)])

    class Meta:
        ordering = ('order', 'id')
        unique_together = ('lesson', 'problem')
        verbose_name = _('lesson problem')
        verbose_name_plural = _('lesson problems')

    def __str__(self):
        return '%s / %s' % (self.lesson, self.problem.code)
