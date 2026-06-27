import logging
import sqlite3
import os
from django.core.management.base import BaseCommand
from django.conf import settings
from core.models import Student, Resume, ParentReview

logger = logging.getLogger("app_resume")

class Command(BaseCommand):
    help = "Перенос резюме и отзывов из старой базы SQLite в новую БД"

    def handle(self, *args, **options):
        self.stdout.write("Начинаем миграцию резюме из old_sqlite...")

        # Путь к старой базе данных (по умолчанию backend/core/db.sqlite3)
        old_db_path = os.path.join(settings.BASE_DIR, 'core', 'db.sqlite3')
        
        if not os.path.exists(old_db_path):
            self.stdout.write(self.style.ERROR(f"Старая база данных не найдена по пути: {old_db_path}"))
            return

        try:
            conn = sqlite3.connect(old_db_path)
            cursor = conn.cursor()

            # Получаем всех студентов из старой БД, чтобы сопоставить их старые ID с CRM ID
            cursor.execute("SELECT id, student_crm_id FROM app_resumes_student")
            old_students = cursor.fetchall()
            
            # old_id -> crm_id
            student_id_to_crm_id = {row[0]: row[1] for row in old_students}

            # 1. Миграция резюме
            self.stdout.write("Миграция резюме (Resume)...")
            cursor.execute("""
                SELECT id, student_id, content, is_verified, created_at, updated_at
                FROM app_resumes_resume
            """)
            old_resumes = cursor.fetchall()
            resume_count = 0
            
            for row in old_resumes:
                old_id, student_id, content, is_verified, created_at, updated_at = row
                
                crm_id = student_id_to_crm_id.get(student_id)
                if not crm_id:
                    continue
                    
                # Ищем студента в новой БД по crm_id
                student_obj = Student.objects.filter(student_crm_id=str(crm_id)).first()
                
                if student_obj:
                    Resume.objects.update_or_create(
                        student=student_obj,
                        content=content,
                        defaults={
                            'is_verified': bool(is_verified)
                        }
                    )
                    resume_count += 1

            # 2. Миграция отзывов (ParentReview)
            self.stdout.write("Миграция отзывов (ParentReview)...")
            cursor.execute("""
                SELECT id, student_id, content, created_at, updated_at
                FROM app_resumes_parentreview
            """)
            old_reviews = cursor.fetchall()
            review_count = 0
            
            for row in old_reviews:
                old_id, student_id, content, created_at, updated_at = row
                
                crm_id = student_id_to_crm_id.get(student_id)
                if not crm_id:
                    continue
                    
                student_obj = Student.objects.filter(student_crm_id=str(crm_id)).first()
                
                if student_obj:
                    ParentReview.objects.get_or_create(
                        student=student_obj,
                        content=content
                    )
                    review_count += 1

            self.stdout.write(self.style.SUCCESS(
                f"Успешно перенесено:\n"
                f"- Резюме: {resume_count}\n"
                f"- Отзывов: {review_count}"
            ))

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Произошла ошибка при миграции: {str(e)}"))
            logger.exception("migrate_resumes error")
        finally:
            if 'conn' in locals():
                conn.close()
