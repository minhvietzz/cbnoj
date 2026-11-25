from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from judge.models import CourseLesson, CourseLessonProblem, CourseRole


class CourseRoleInline(admin.TabularInline):
    model = CourseRole
    extra = 1
    raw_id_fields = ('user',)


class CourseLessonInline(admin.TabularInline):
    model = CourseLesson
    extra = 0
    fields = ('order', 'title', 'is_visible', 'prerequisite', 'prerequisite_percent')
    show_change_link = True


class CourseAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'is_public', 'is_open', 'created')
    list_filter = ('is_public', 'is_open')
    search_fields = ('name', 'slug', 'about')
    prepopulated_fields = {'slug': ('name',)}
    inlines = [CourseRoleInline, CourseLessonInline]
    fieldsets = (
        (None, {'fields': ('name', 'slug', 'about', 'image_url', 'subject', 'classes')}),
        (_('Visibility'), {'fields': ('is_public', 'is_open')}),
    )

    def has_change_permission(self, request, obj=None):
        if obj is not None and not request.user.is_superuser:
            return obj.is_editable_by(request.user) and request.user.is_staff
        return super().has_change_permission(request, obj)


class CourseLessonProblemInline(admin.TabularInline):
    model = CourseLessonProblem
    extra = 1
    raw_id_fields = ('problem',)


class CourseLessonAdmin(admin.ModelAdmin):
    list_display = ('title', 'course', 'order', 'is_visible')
    list_filter = ('course', 'is_visible')
    search_fields = ('title', 'course__name')
    fields = ('course', 'title', 'order', 'is_visible', 'prerequisite', 'prerequisite_percent', 'content')
    inlines = [CourseLessonProblemInline]
