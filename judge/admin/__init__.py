from django.conf import settings
from django.contrib import admin
from django.contrib.admin.models import LogEntry
from django.contrib.auth.models import User
from django.contrib.flatpages.models import FlatPage

from judge.admin.comments import CommentAdmin
from judge.admin.contest import ContestAdmin, ContestParticipationAdmin, ContestTagAdmin
from judge.admin.course import CourseAdmin, CourseLessonAdmin
from judge.admin.interface import BlogPostAdmin, BlogPostTagAdmin, FlatPageAdmin, LicenseAdmin, LogEntryAdmin, \
    NavigationBarAdmin
from judge.admin.organization import OrganizationAdmin, OrganizationRequestAdmin
from judge.admin.problem import ProblemAdmin
from judge.admin.profile import ProfileAdmin, UserAdmin
from judge.admin.quiz import BankQuestionAdmin, BankTagAdmin, QuizAdmin, QuizAttemptAdmin, QuizProfileStatAdmin, \
    QuizQuestionAdmin
from judge.admin.runtime import JudgeAdmin, LanguageAdmin
from judge.admin.submission import SubmissionAdmin
from judge.admin.tag import TagAdmin, TagGroupAdmin, TagProblemAdmin
from judge.admin.taxon import OrganizationProblemTagAdmin, ProblemGroupAdmin, ProblemTypeAdmin
from judge.admin.ticket import TicketAdmin
from judge.models import Badge, BankQuestion, BankTag, BlogPost, BlogPostTag, Comment, CommentLock, Contest, \
    ContestParticipation, ContestTag, Course, CourseLesson, Judge, Language, License, MiscConfig, NavigationBar, \
    Organization, OrganizationProblemTag, OrganizationRequest, Problem, ProblemGroup, ProblemType, Profile, Quiz, \
    QuizAttempt, QuizProfileStat, QuizQuestion, Submission, Tag, TagGroup, TagProblem, Ticket

admin.site.register(BlogPost, BlogPostAdmin)
admin.site.register(BlogPostTag, BlogPostTagAdmin)
admin.site.register(Comment, CommentAdmin)
admin.site.register(CommentLock)
admin.site.register(Contest, ContestAdmin)
admin.site.register(Course, CourseAdmin)
if getattr(settings, 'QUIZ_ENABLED', False):   # switched off: see dmoj/urls.py
    admin.site.register(Quiz, QuizAdmin)
    admin.site.register(BankQuestion, BankQuestionAdmin)
    admin.site.register(BankTag, BankTagAdmin)
    admin.site.register(QuizQuestion, QuizQuestionAdmin)
    admin.site.register(QuizAttempt, QuizAttemptAdmin)
    admin.site.register(QuizProfileStat, QuizProfileStatAdmin)
admin.site.register(CourseLesson, CourseLessonAdmin)
admin.site.register(ContestParticipation, ContestParticipationAdmin)
admin.site.register(ContestTag, ContestTagAdmin)
admin.site.unregister(FlatPage)
admin.site.register(FlatPage, FlatPageAdmin)
admin.site.register(Judge, JudgeAdmin)
admin.site.register(Language, LanguageAdmin)
admin.site.register(License, LicenseAdmin)
admin.site.register(LogEntry, LogEntryAdmin)
admin.site.register(MiscConfig)
admin.site.register(Badge)
admin.site.register(NavigationBar, NavigationBarAdmin)
admin.site.register(Organization, OrganizationAdmin)
admin.site.register(OrganizationProblemTag, OrganizationProblemTagAdmin)
admin.site.register(OrganizationRequest, OrganizationRequestAdmin)
admin.site.register(Problem, ProblemAdmin)
admin.site.register(ProblemGroup, ProblemGroupAdmin)
admin.site.register(ProblemType, ProblemTypeAdmin)
admin.site.register(Profile, ProfileAdmin)
admin.site.register(Submission, SubmissionAdmin)
admin.site.register(Ticket, TicketAdmin)
admin.site.register(Tag, TagAdmin)
admin.site.register(TagGroup, TagGroupAdmin)
admin.site.register(TagProblem, TagProblemAdmin)
admin.site.unregister(User)
admin.site.register(User, UserAdmin)
