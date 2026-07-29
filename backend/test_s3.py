import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', '_settings.settings')
django.setup()

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage


def test_s3_connection():
    file_name = "test_hoster_s3.txt"
    content = b"Testing hoster.by S3 integration"

    print(f"[1/3] Загрузка тестового файла '{file_name}' в S3...")
    try:
        saved_path = default_storage.save(file_name, ContentFile(content))
        print(f"      Успешно! Путь в бакете: {saved_path}")
    except Exception as e:
        print(f"      ОШИБКА при загрузке: {e}")
        return False

    print("[2/3] Проверка существования файла...")
    if default_storage.exists(saved_path):
        print("      Файл успешно найден в S3!")
    else:
        print("      ОШИБКА: Файл не найден после сохранения!")
        return False

    print("[3/3] Очистка: удаление тестового файла...")
    try:
        default_storage.delete(saved_path)
        print("      Тестовый файл успешно удален из S3.")
    except Exception as e:
        print(f"      Ошибка при удалении: {e}")
        return False

    print("\n>>> ТЕСТ S3 УСПЕШНО ПРОЙДЕН! <<<")
    return True


if __name__ == "__main__":
    test_s3_connection()
