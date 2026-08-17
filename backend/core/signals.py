import logging

from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import Lesson, Employee

logger = logging.getLogger("core")


@receiver(post_delete, sender=Lesson)
def delete_lesson_files_from_s3(sender, instance, **kwargs):
    """Удаляет файлы урока из S3-хранилища при удалении записи Lesson."""
    for field_name in ("file", "archive"):
        file_field = getattr(instance, field_name, None)
        if file_field and file_field.name:
            try:
                file_field.delete(save=False)
                logger.info(
                    "Удалён файл из S3: %s (Lesson id=%s)",
                    file_field.name,
                    instance.pk,
                )
            except Exception as exc:
                logger.error(
                    "Ошибка удаления файла %s из S3 (Lesson id=%s): %s",
                    file_field.name,
                    instance.pk,
                    exc,
                )


@receiver(post_delete, sender=Employee)
def delete_employee_photo_from_s3(sender, instance, **kwargs):
    """Удаляет файл фотографии сотрудника из S3/хранилища при удалении записи Employee."""
    if instance.photo and instance.photo.name:
        try:
            instance.photo.delete(save=False)
            logger.info(
                "Удалена фотография сотрудника: %s (Employee id=%s)",
                instance.photo.name,
                instance.pk,
            )
        except Exception as exc:
            logger.error(
                "Ошибка удаления фотографии %s (Employee id=%s): %s",
                instance.photo.name,
                instance.pk,
                exc,
            )

