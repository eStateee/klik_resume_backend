import logging

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import BotoCoreError, ClientError
from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers
from rest_framework_simplejwt.exceptions import AuthenticationFailed
from rest_framework_simplejwt.serializers import (
    TokenObtainPairSerializer,
    TokenRefreshSerializer,
)
from rest_framework_simplejwt.settings import api_settings as jwt_settings
from rest_framework_simplejwt.tokens import RefreshToken

from .authentication import resolve_user_by_role
from .models import (
    Branch,
    Category,
    Group,
    Lesson,
    Location,
    Manager,
    Module,
    News,
    ParentReview,
    Resume,
    Student,
    Subcategory,
    TutorModule,
    TutorProfile,
)

logger = logging.getLogger("core")


# ---------------------------------------------------------------------------
# Авторизация
# ---------------------------------------------------------------------------


def build_token_claims(user):
    """Кастомные клеймы токена в зависимости от роли пользователя."""
    if isinstance(user, Manager):
        return {
            "user_id": user.id,
            "role": "manager",
            "is_senior": user.is_senior,
            "branch_id": user.location.branch_id if user.location else None,
            "location_id": user.location_id,
        }

    if isinstance(user, TutorProfile):
        return {
            "user_id": user.id,
            "role": "tutor",
            "is_senior": user.is_senior,
            "branch_id": user.branch_id,
        }

    raise serializers.ValidationError("Неизвестный тип пользователя.")


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Убираем стандартные поля логина/пароля
        self.fields.pop("username", None)
        self.fields.pop("password", None)
        self.fields["phone_number"] = serializers.CharField()

    def validate(self, attrs):
        phone_number = attrs.get("phone_number", "")

        # Очищаем телефон от всего кроме цифр
        phone_number = "".join(filter(str.isdigit, phone_number))

        from django.contrib.auth import authenticate

        user = authenticate(request=self.context.get("request"), phone_number=phone_number)

        if user is None:
            # Различаем «не найден» и «деактивирован» для корректного UX
            if TutorProfile.objects.filter(phone_number=phone_number, is_active=False).exists():
                raise serializers.ValidationError(
                    {"phone_number": "Ваш аккаунт деактивирован. Обратитесь к администратору."}
                )
            raise serializers.ValidationError(
                {"phone_number": "Пользователь с таким номером телефона не найден."}
            )

        refresh = self.get_token(user)
        return {
            "refresh": str(refresh),
            "access": str(refresh.access_token),
        }

    @classmethod
    def get_token(cls, user):
        """Генерирует RefreshToken с кастомными клеймами в зависимости от роли."""
        token = RefreshToken()
        for claim, value in build_token_claims(user).items():
            token[claim] = value

        return token


class CustomTokenRefreshSerializer(TokenRefreshSerializer):
    """
    Обновление access-токена для Manager/TutorProfile.

    Стандартный TokenRefreshSerializer ищет владельца токена в
    `django.contrib.auth.User`, которого в проекте нет — для любого
    user_id без совпадающей строки в auth_user это падало с 500
    (`User matching query does not exist`). Поэтому пользователя ищем сами,
    по клейму `role`, как это делает CustomJWTAuthentication.
    """

    def validate(self, attrs):
        refresh = self.token_class(attrs["refresh"])

        role = refresh.payload.get("role")
        user = resolve_user_by_role(role, refresh.payload.get("user_id"))

        if user is None:
            # Токен без кастомной роли — суперпользователь Django Admin
            try:
                return super().validate(attrs)
            except ObjectDoesNotExist:
                raise AuthenticationFailed(
                    "Пользователь не найден", code="user_not_found"
                )

        access = refresh.access_token
        # Клеймы перечитываем из БД: is_senior, филиал или локация могли
        # измениться уже после выдачи refresh-токена.
        for claim, value in build_token_claims(user).items():
            access[claim] = value

        data = {"access": str(access)}

        if jwt_settings.ROTATE_REFRESH_TOKENS:
            if jwt_settings.BLACKLIST_AFTER_ROTATION:
                try:
                    refresh.blacklist()
                except AttributeError:
                    # Приложение blacklist не подключено — метода нет
                    pass

            refresh.set_jti()
            refresh.set_exp()
            refresh.set_iat()
            refresh.outstand()

            data["refresh"] = str(refresh)

        return data


# ---------------------------------------------------------------------------
# Вспомогательная функция генерации pre-signed URL
# ---------------------------------------------------------------------------


def _get_s3_client():
    """Создаёт и возвращает boto3-клиент для S3. Raises RuntimeError если не сконфигурирован."""
    access_key = getattr(settings, "AWS_ACCESS_KEY_ID", None)
    secret_key = getattr(settings, "AWS_SECRET_ACCESS_KEY", None)

    if not access_key or not secret_key:
        raise RuntimeError("S3 не сконфигурирован: отсутствуют AWS_ACCESS_KEY_ID или AWS_SECRET_ACCESS_KEY")

    endpoint_url = getattr(settings, "AWS_S3_ENDPOINT_URL", "https://storage-1022.s3hoster.by")
    if not endpoint_url.startswith(("http://", "https://")):
        endpoint_url = f"https://{endpoint_url}"

    addressing_style = getattr(settings, "AWS_S3_ADDRESSING_STYLE", "path")

    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name=getattr(settings, "AWS_S3_REGION_NAME", "us-east-1"),
        config=BotoConfig(signature_version="s3v4", s3={"addressing_style": addressing_style}),
    )


def generate_presigned_url(file_field, expires_in: int = 900) -> str | None:
    """
    Генерирует временный pre-signed URL для файла в S3.
    Возвращает None если файл не задан.
    Raises RuntimeError/ClientError при проблемах с S3.
    """
    if not file_field or not file_field.name:
        return None

    s3_client = _get_s3_client()
    bucket = getattr(settings, "AWS_STORAGE_BUCKET_NAME", "")

    if not bucket:
        raise RuntimeError("S3 не сконфигурирован: отсутствует AWS_STORAGE_BUCKET_NAME")

    try:
        url = s3_client.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": file_field.name},
            ExpiresIn=expires_in,
        )
    except (BotoCoreError, ClientError) as exc:
        logger.error("Ошибка генерации pre-signed URL для %s: %s", file_field.name, exc)
        raise

    return url


# ---------------------------------------------------------------------------
# Доступ тьютора к модулям
# ---------------------------------------------------------------------------

# Сообщение для тьютора, у которого нет ни одного доступного модуля
NO_MODULE_ACCESS_MESSAGE = "Нет доступа ни к одному модулю."


def resolve_viewer(request):
    """
    Определяет (role, user_id, is_senior) текущего пользователя.
    Основной источник — клеймы JWT в request.auth; фолбэк — request.user.
    """
    if request is None:
        return None, None, False

    auth = getattr(request, "auth", None)
    if auth:
        return auth.get("role"), auth.get("user_id"), bool(auth.get("is_senior", False))

    user = getattr(request, "user", None)
    if isinstance(user, TutorProfile):
        return "tutor", user.id, bool(user.is_senior)
    if isinstance(user, Manager):
        return "manager", user.id, bool(user.is_senior)

    return None, None, False


def is_privileged_viewer(role, is_senior) -> bool:
    """Менеджер и старший тьютор имеют полный доступ ко всем модулям."""
    return role == "manager" or (role == "tutor" and bool(is_senior))


def accessible_module_ids(tutor_id):
    """ID модулей, к которым у тьютора есть непросроченный доступ."""
    return TutorModule.objects.filter(
        tutor_id=tutor_id, expires_at__gt=timezone.now()
    ).values_list("module_id", flat=True)


# ---------------------------------------------------------------------------
# Сериализаторы данных
# ---------------------------------------------------------------------------


class GroupSerializer(serializers.ModelSerializer):
    total_students = serializers.IntegerField(read_only=True)
    resumes_written_count = serializers.IntegerField(read_only=True)
    resumes_verified_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Group
        fields = [
            "id", "crm_group_id", "name", "location", "branch", "tutor",
            "total_students", "resumes_written_count", "resumes_verified_count"
        ]


class StudentSerializer(serializers.ModelSerializer):
    is_verified = serializers.SerializerMethodField()
    is_review_exist = serializers.SerializerMethodField()
    group_name = serializers.SerializerMethodField()

    class Meta:
        model = Student
        fields = [
            "id", "student_crm_id", "student_name", "study_start_date",
            "branch", "group", "group_name", "is_added", "is_verified",
            "is_review_exist",
        ]

    @extend_schema_field(serializers.BooleanField())
    def get_is_verified(self, obj):
        """Возвращает True, если у студента есть резюме и все они проверены."""
        resumes = obj.resumes.all()
        if not resumes.exists():
            return False
        return not resumes.filter(is_verified=False).exists()

    @extend_schema_field(serializers.BooleanField())
    def get_is_review_exist(self, obj):
        """Возвращает True, если у студента есть хотя бы один отзыв за последние 60 дней."""
        from datetime import timedelta
        threshold = timezone.now() - timedelta(days=60)
        return obj.parent_reviews.filter(created_at__gte=threshold).exists()

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_group_name(self, obj):
        """Возвращает название группы студента или None."""
        if obj.group is None:
            return None
        return obj.group.name


class ResumeSerializer(serializers.ModelSerializer):
    student_crm_id = serializers.CharField(write_only=True)
    student = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = Resume
        fields = ["id", "student", "student_crm_id", "content", "is_verified", "created_at", "updated_at"]
        read_only_fields = ["is_verified", "created_at", "updated_at", "student"]

    def create(self, validated_data):
        student_crm_id = validated_data.pop("student_crm_id")
        student = get_object_or_404(Student, student_crm_id=student_crm_id)
        validated_data["student"] = student
        
        if not student.is_added:
            student.is_added = True
            student.save(update_fields=['is_added'])
            
        return super().create(validated_data)


class ParentReviewSerializer(serializers.ModelSerializer):
    student_crm_id = serializers.CharField(write_only=True)
    student = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = ParentReview
        fields = ["id", "student", "student_crm_id", "content", "created_at", "updated_at"]
        read_only_fields = ["created_at", "updated_at", "student"]

    def create(self, validated_data):
        student_crm_id = validated_data.pop("student_crm_id")
        student = get_object_or_404(Student, student_crm_id=student_crm_id)
        validated_data["student"] = student
        return super().create(validated_data)


class NewsSerializer(serializers.ModelSerializer):
    class Meta:
        model = News
        fields = ["id", "title", "content", "created_at"]


class LessonSerializer(serializers.ModelSerializer):
    file_url = serializers.SerializerMethodField()
    archive_url = serializers.SerializerMethodField()

    class Meta:
        model = Lesson
        fields = ["id", "lesson_number", "file_url", "archive_url"]

    def get_file_url(self, obj) -> str | None:
        try:
            return generate_presigned_url(obj.file)
        except (RuntimeError, BotoCoreError, ClientError) as exc:
            logger.error("get_file_url для Lesson id=%s: %s", obj.pk, exc)
            return None

    def get_archive_url(self, obj) -> str | None:
        try:
            return generate_presigned_url(obj.archive)
        except (RuntimeError, BotoCoreError, ClientError) as exc:
            logger.error("get_archive_url для Lesson id=%s: %s", obj.pk, exc)
            return None


class ModuleListSerializer(serializers.ModelSerializer):
    """Модуль без уроков — используется в списке модулей."""

    is_accessible = serializers.SerializerMethodField()

    class Meta:
        model = Module
        fields = ["id", "name", "validity_period", "is_active", "is_accessible"]

    def _check_tutor_access(self, obj) -> bool:
        """
        Проверяет наличие доступа к модулю у текущего пользователя.
        Менеджер и старший тьютор — полный доступ; обычному тьютору нужен
        активный (непросроченный) TutorModule.
        """
        role, user_id, is_senior = resolve_viewer(self.context.get("request"))

        if is_privileged_viewer(role, is_senior):
            return True

        if role != "tutor":
            return False

        return TutorModule.objects.filter(
            tutor_id=user_id,
            module=obj,
            expires_at__gt=timezone.now(),
        ).exists()

    def get_is_accessible(self, obj) -> bool:
        # Кэшируем результат в контексте, чтобы не делать повторный запрос в get_lessons
        cache_key = f"_accessible_{obj.pk}"
        if cache_key not in self.context:
            self.context[cache_key] = self._check_tutor_access(obj)
        return self.context[cache_key]


class ModuleSerializer(ModuleListSerializer):
    """Модуль вместе с уроками — используется там, где уроки нужны."""

    lessons = serializers.SerializerMethodField()

    class Meta(ModuleListSerializer.Meta):
        fields = ModuleListSerializer.Meta.fields + ["lessons"]

    def get_lessons(self, obj) -> list:
        # Используем кэшированный результат — без повторного DB-запроса
        if not self.get_is_accessible(obj):
            return []
        lessons = obj.lessons.all()
        return LessonSerializer(lessons, many=True, context=self.context).data


class SubcategorySerializer(serializers.ModelSerializer):
    # Только активные модули в ответе
    modules = serializers.SerializerMethodField()

    class Meta:
        model = Subcategory
        fields = ["id", "name", "is_active", "modules"]

    def get_modules(self, obj) -> list:
        active_modules = obj.modules.filter(is_active=True)
        return ModuleSerializer(active_modules, many=True, context=self.context).data


class CategorySerializer(serializers.ModelSerializer):
    """Полная версия: подкатегории вместе с модулями и уроками. Используется в retrieve."""

    # Только активные подкатегории в ответе
    subcategories = serializers.SerializerMethodField()

    class Meta:
        model = Category
        fields = ["id", "name", "is_active", "subcategories"]

    def get_subcategories(self, obj) -> list:
        active_subcategories = obj.subcategories.filter(is_active=True)
        return SubcategorySerializer(active_subcategories, many=True, context=self.context).data


class SubcategoryListSerializer(serializers.ModelSerializer):
    """Подкатегория без модулей — используется в списке категорий."""

    class Meta:
        model = Subcategory
        fields = ["id", "name", "is_active"]


class CategoryListSerializer(serializers.ModelSerializer):
    """Облегчённая версия: только подкатегории, без модулей и уроков. Используется в list."""

    subcategories = serializers.SerializerMethodField()

    class Meta:
        model = Category
        fields = ["id", "name", "is_active", "subcategories"]

    def get_subcategories(self, obj) -> list:
        active_subcategories = obj.subcategories.filter(is_active=True)
        return SubcategoryListSerializer(active_subcategories, many=True, context=self.context).data


class BranchSerializer(serializers.ModelSerializer):
    class Meta:
        model = Branch
        fields = ["id", "name", "branch_crm_id"]


class LocationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Location
        fields = ["id", "name", "location_crm_id", "branch", "is_active"]
