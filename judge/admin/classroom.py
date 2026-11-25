from django.contrib import admin

from judge.models import ClassMember


class ClassMemberInline(admin.TabularInline):
    model = ClassMember
    extra = 1
    raw_id_fields = ('user',)


class ClassroomAdmin(admin.ModelAdmin):
    list_display = ('name', 'school_year', 'organization', 'subject', 'is_archived', 'created')
    list_filter = ('is_archived', 'organization', 'subject')
    search_fields = ('name', 'slug')
    prepopulated_fields = {'slug': ('name',)}
    raw_id_fields = ('organization',)
    inlines = [ClassMemberInline]


class SubjectAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'order', 'is_active')
    prepopulated_fields = {'slug': ('name',)}


class ClassAssignmentAdmin(admin.ModelAdmin):
    list_display = ('title', 'classroom', 'kind', 'due', 'created')
    list_filter = ('kind', 'classroom')
    search_fields = ('title', 'classroom__name')
    raw_id_fields = ('quiz', 'created_by')
    filter_horizontal = ('problems',)


class ClassAnnouncementAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'classroom', 'author', 'pinned', 'created')
    list_filter = ('pinned', 'classroom')
    raw_id_fields = ('author',)
