from django.contrib import admin
from .models import (
    Branch, Location, TutorProfile, Manager,
    Group, Student, Resume, ParentReview,
    Category, Subcategory, Module, Lesson, TutorModule, News, Employee,
)


@admin.register(Branch)
class BranchAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'branch_crm_id')
    search_fields = ('name',)


@admin.register(Location)
class LocationAdmin(admin.ModelAdmin):
    list_display = ('id', 'location_crm_id', 'name', 'branch', 'is_active')
    list_filter = ('branch', 'is_active')


@admin.register(TutorProfile)
class TutorProfileAdmin(admin.ModelAdmin):
    list_display = ('id', 'tutor_name', 'phone_number', 'branch', 'is_active','is_senior')
    list_filter = ('branch', 'is_senior')
    search_fields = ('tutor_name', 'phone_number')


@admin.register(Manager)
class ManagerAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'phone', 'location', 'is_senior')
    list_filter = ('location', 'is_senior')
    search_fields = ('name', 'phone')


@admin.register(Group)
class GroupAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'crm_group_id', 'branch', 'location', 'tutor')
    list_filter = ('branch', 'location')
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
    list_display = ('id', 'name', 'subcategory', 'validity_period', 'is_active', 'is_public')
    list_filter = ('is_active', 'is_public', 'subcategory')


@admin.register(Lesson)
class LessonAdmin(admin.ModelAdmin):
    list_display = ('id', 'lesson_number', 'module')
    list_filter = ('module',)


@admin.register(TutorModule)
class TutorModuleAdmin(admin.ModelAdmin):
    list_display = ('id', 'tutor', 'module', 'expires_at')
    list_filter = ('module',)


@admin.register(News)
class NewsAdmin(admin.ModelAdmin):
    list_display = ('id', 'title', 'created_at')


@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    list_display = ('id', 'full_name', 'category', 'position', 'branch', 'location')
    list_filter = ('category', 'branch', 'location')
    search_fields = ('full_name', 'position', 'telegram_url')


