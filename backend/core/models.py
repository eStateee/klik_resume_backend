from django.db import models

class Branch(models.Model):
    name = models.CharField(max_length=255, verbose_name="Название")
    branch_crm_id = models.IntegerField(unique=True, verbose_name="ID филиала в CRM")

    def __str__(self):
        return self.name

class Location(models.Model):
    name = models.CharField(max_length=255, verbose_name="Название локации")
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, verbose_name="Филиал", related_name="locations")

    def __str__(self):
        return f"{self.name} ({self.branch.name})"

class AuthenticatedModelMixin:
    @property
    def is_authenticated(self):
        return True

    @property
    def is_anonymous(self):
        return False

    @property
    def is_active(self):
        return True

class TutorProfile(AuthenticatedModelMixin, models.Model):
    tutor_crm_id = models.CharField(max_length=100, unique=True, null=True, blank=True, verbose_name="ID преподавателя из CRM")
    tutor_name = models.CharField(max_length=255, verbose_name="ФИО преподавателя")
    branch = models.ForeignKey(Branch, on_delete=models.PROTECT, verbose_name="Филиал", related_name="tutors")
    is_senior = models.BooleanField(default=False, verbose_name="Старший тьютор")
    phone_number = models.CharField(max_length=50, unique=True, verbose_name="Уникальный телефон")
    dob = models.DateField(null=True, blank=True, verbose_name="Дата рождения")
    note = models.TextField(null=True, blank=True, verbose_name="Заметка")
    avatar_url = models.CharField(max_length=500, null=True, blank=True, verbose_name="URL аватара")

    def __str__(self):
        return self.tutor_name

class Manager(AuthenticatedModelMixin, models.Model):
    name = models.CharField(max_length=255, verbose_name="ФИО менеджера")
    telegram = models.CharField(max_length=255, null=True, blank=True, verbose_name="Telegram")
    location = models.ForeignKey(Location, on_delete=models.PROTECT, verbose_name="Локация", related_name="managers")
    phone = models.CharField(max_length=50, unique=True, verbose_name="Уникальный телефон")
    is_senior = models.BooleanField(default=False, verbose_name="Старший менеджер")

    def __str__(self):
        return self.name

class Group(models.Model):
    crm_group_id = models.CharField(max_length=100, unique=True, verbose_name="ID группы из CRM")
    branch = models.ForeignKey(Branch, on_delete=models.PROTECT, verbose_name="Филиал", related_name="groups")
    tutor = models.ForeignKey(TutorProfile, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Тьютор", related_name="groups")
    name = models.CharField(max_length=255, verbose_name="Название группы")
    custom_aerodromnaya = models.BooleanField(default=False, verbose_name="Кастомная Аэродромная")

    def __str__(self):
        return self.name

class Student(models.Model):
    student_crm_id = models.CharField(max_length=100, unique=True, verbose_name="ID ученика из CRM")
    group = models.ForeignKey(Group, on_delete=models.CASCADE, null=True, blank=True, verbose_name="Группа", related_name="students")
    student_name = models.CharField(max_length=255, verbose_name="ФИО ученика")
    study_start_date = models.DateField(null=True, blank=True, verbose_name="Дата начала обучения")
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, verbose_name="Филиал", related_name="students")

    def __str__(self):
        return self.student_name

class Resume(models.Model):
    student = models.ForeignKey(Student, on_delete=models.CASCADE, verbose_name="Студент", related_name="resumes")
    content = models.TextField(verbose_name="Текст резюме")
    is_verified = models.BooleanField(default=False, verbose_name="Проверено")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Создано")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Обновлено")

    def __str__(self):
        return f"Резюме: {self.student.student_name}"

class ParentReview(models.Model):
    student = models.ForeignKey(Student, on_delete=models.CASCADE, verbose_name="Студент", related_name="parent_reviews")
    content = models.TextField(verbose_name="Текст отзыва")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Создано")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Обновлено")

    def __str__(self):
        return f"Отзыв: {self.student.student_name}"

class Category(models.Model):
    name = models.CharField(max_length=255, verbose_name="Название категории")
    is_active = models.BooleanField(default=True, verbose_name="Активна")

    def __str__(self):
        return self.name

class Subcategory(models.Model):
    name = models.CharField(max_length=255, verbose_name="Название подкатегории")
    category = models.ForeignKey(Category, on_delete=models.CASCADE, verbose_name="Категория", related_name="subcategories")
    is_active = models.BooleanField(default=True, verbose_name="Активна")

    def __str__(self):
        return self.name

class Module(models.Model):
    name = models.CharField(max_length=255, verbose_name="Название модуля")
    subcategory = models.ForeignKey(Subcategory, on_delete=models.CASCADE, verbose_name="Подкатегория", related_name="modules")
    validity_period = models.IntegerField(default=7, verbose_name="Период действия (дни)")
    is_active = models.BooleanField(default=True, verbose_name="Активен")

    def __str__(self):
        return self.name

class Lesson(models.Model):
    module = models.ForeignKey(Module, on_delete=models.CASCADE, verbose_name="Модуль", related_name="lessons")
    file = models.FileField(upload_to="lessons/files/", verbose_name="Файл для просмотра (PDF)")
    archive = models.FileField(upload_to="lessons/archives/", verbose_name="Архив для скачивания")

    def __str__(self):
        return f"Урок для модуля {self.module.name}"

class TutorModule(models.Model):
    tutor = models.ForeignKey(TutorProfile, on_delete=models.CASCADE, verbose_name="Тьютор", related_name="tutor_modules")
    module = models.ForeignKey(Module, on_delete=models.CASCADE, verbose_name="Модуль", related_name="tutor_modules")
    expires_at = models.DateTimeField(verbose_name="Истекает")

    def __str__(self):
        return f"Доступ: {self.tutor.tutor_name} -> {self.module.name}"

class News(models.Model):
    title = models.CharField(max_length=255, verbose_name="Заголовок")
    content = models.TextField(verbose_name="Контент")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Создано")

    def __str__(self):
        return self.title
    
    class Meta:
        verbose_name = 'Новость'
        verbose_name_plural = "Новости"
