from django.contrib import admin
from .models import (
    Branch, Location, TutorProfile, Manager,
    Group, Student, Resume, ParentReview,
    Category, Subcategory, Module, Lesson, TutorModule, News,
)


@admin.register(Branch)
class BranchAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'branch_crm_id')
    search_fields = ('name',)


@admin.register(Location)
class LocationAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'branch')
    list_filter = ('branch',)


@admin.register(TutorProfile)
class TutorProfileAdmin(admin.ModelAdmin):
    list_display = ('id', 'tutor_name', 'phone_number', 'branch', 'is_senior')
    list_filter = ('branch', 'is_senior')
    search_fields = ('tutor_name', 'phone_number')


@admin.register(Manager)
class ManagerAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'phone', 'location', 'is_senior')
    list_filter = ('location', 'is_senior')
    search_fields = ('name', 'phone')


@admin.register(Group)
class GroupAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'crm_group_id', 'branch', 'tutor')
    list_filter = ('branch',)
    search_fields = ('name', 'crm_group_id')


@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = ('id', 'student_name', 'student_crm_id', 'group', 'branch')
    list_filter = ('branch',)
    search_fields = ('student_name', 'student_crm_id')


@admin.register(Resume)
class ResumeAdmin(admin.ModelAdmin):
    list_display = ('id', 'student', 'is_verified', 'created_at')
    list_filter = ('is_verified',)


@admin.register(ParentReview)
class ParentReviewAdmin(admin.ModelAdmin):
    list_display = ('id', 'student', 'created_at')


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'is_active')


@admin.register(Subcategory)
class SubcategoryAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'category', 'is_active')
    list_filter = ('category',)


@admin.register(Module)
class ModuleAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'subcategory', 'validity_period', 'is_active')
    list_filter = ('is_active', 'subcategory')


@admin.register(Lesson)
class LessonAdmin(admin.ModelAdmin):
    list_display = ('id', 'module')


@admin.register(TutorModule)
class TutorModuleAdmin(admin.ModelAdmin):
    list_display = ('id', 'tutor', 'module', 'expires_at')
    list_filter = ('module',)


@admin.register(News)
class NewsAdmin(admin.ModelAdmin):
    list_display = ('id', 'title', 'created_at')
