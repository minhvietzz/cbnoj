from django.contrib import admin
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from judge.models import CourseLesson, CourseLessonProblem, CourseRole, Organization


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
    list_display = ('name', 'slug', 'organization', 'is_public', 'is_open', 'created')
    list_filter = ('is_public', 'is_open', 'organization')
    search_fields = ('name', 'slug', 'about')
    prepopulated_fields = {'slug': ('name',)}
    inlines = [CourseRoleInline, CourseLessonInline]
    fieldsets = (
        (None, {'fields': ('name', 'slug', 'about', 'image_url', 'subject', 'organization', 'classes')}),
        (_('Visibility'), {'fields': ('is_public', 'is_open')}),
    )

    def has_change_permission(self, request, obj=None):
        if obj is not None and not request.user.is_superuser:
            return obj.is_editable_by(request.user) and request.user.is_staff
        return super().has_change_permission(request, obj)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        # Only superusers may put a course into any organization; others only into ones they administer.
        if db_field.name == 'organization' and not request.user.is_superuser:
            current = getattr(request, '_course_org_id', None)
            kwargs['queryset'] = Organization.objects.filter(Q(admins=request.user.profile) | Q(pk=current))
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def get_form(self, request, obj=None, **kwargs):
        request._course_org_id = obj.organization_id if obj is not None else None
        return super().get_form(request, obj, **kwargs)


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
