import logging

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from django.conf import settings
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.tokens import RefreshToken

from .models import (
    Category,
    Group,
    Lesson,
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
        token["user_id"] = user.id

        if isinstance(user, Manager):
            token["role"] = "manager"
            token["is_senior"] = user.is_senior
            token["branch_id"] = user.location.branch_id if user.location else None
            token["location_id"] = user.location_id
        elif isinstance(user, TutorProfile):
            token["role"] = "tutor"
            token["is_senior"] = user.is_senior
            token["branch_id"] = user.branch_id
        else:
            raise serializers.ValidationError("Неизвестный тип пользователя.")

        return token


# ---------------------------------------------------------------------------
# Вспомогательная функция генерации pre-signed URL
# ---------------------------------------------------------------------------


def _get_s3_client():
    """Создаёт и возвращает boto3-клиент для S3. Raises RuntimeError если не сконфигурирован."""
    access_key = getattr(settings, "AWS_ACCESS_KEY_ID", None)
    secret_key = getattr(settings, "AWS_SECRET_ACCESS_KEY", None)

    if not access_key or not secret_key:
        raise RuntimeError("S3 не сконфигурирован: отсутствуют AWS_ACCESS_KEY_ID или AWS_SECRET_ACCESS_KEY")

    return boto3.client(
        "s3",
        endpoint_url=getattr(settings, "AWS_S3_ENDPOINT_URL", None),
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name=getattr(settings, "AWS_S3_REGION_NAME", None),
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
# Сериализаторы данных
# ---------------------------------------------------------------------------


class GroupSerializer(serializers.ModelSerializer):
    class Meta:
        model = Group
        fields = ["id", "crm_group_id", "name", "custom_aerodromnaya", "branch", "tutor"]


class StudentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Student
        fields = ["id", "student_crm_id", "student_name", "study_start_date", "branch", "group"]


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
        fields = ["id", "file_url", "archive_url"]

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


class ModuleSerializer(serializers.ModelSerializer):
    is_accessible = serializers.SerializerMethodField()
    lessons = serializers.SerializerMethodField()

    class Meta:
        model = Module
        fields = ["id", "name", "validity_period", "is_active", "is_accessible", "lessons"]

    def _check_tutor_access(self, obj) -> bool:
        """Проверяет наличие активного доступа тьютора к модулю."""
        request = self.context.get("request")
        if not request or not request.auth:
            return False

        role = request.auth.get("role")
        user_id = request.auth.get("user_id")

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
    # Только активные подкатегории в ответе
    subcategories = serializers.SerializerMethodField()

    class Meta:
        model = Category
        fields = ["id", "name", "is_active", "subcategories"]

    def get_subcategories(self, obj) -> list:
        active_subcategories = obj.subcategories.filter(is_active=True)
        return SubcategorySerializer(active_subcategories, many=True, context=self.context).data
