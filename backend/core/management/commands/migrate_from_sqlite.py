import logging
import json
from datetime import datetime
from django.core.management.base import BaseCommand
from django.db import connections, transaction
from core.models import Branch, Location, TutorProfile, Group, Student, Resume, ParentReview

logger = logging.getLogger("app_resume")


class Command(BaseCommand):
    help = "Миграция данных из старой БД SQLite в новую структуру PostgreSQL"

    def handle(self, *args, **options):
        self.stdout.write("Начинаем миграцию данных из old_sqlite...")

        try:
            with transaction.atomic():
                cursor = connections['old_sqlite'].cursor()

                # 1. Миграция филиалов (Branch) и локаций (Location)
                self.stdout.write("Шаг 1: Восстановление филиалов и локаций")
                cursor.execute("SELECT DISTINCT branch FROM app_resumes_tutorprofile WHERE branch IS NOT NULL")
                old_branches = cursor.fetchall()

                # Предварительно создадим каноничные филиалы
                canonical_branches = {
                    1: Branch.objects.get_or_create(branch_crm_id=1, defaults={'name': 'Минск'})[0],
                    2: Branch.objects.get_or_create(branch_crm_id=2, defaults={'name': 'Барановичи'})[0],
                    3: Branch.objects.get_or_create(branch_crm_id=3, defaults={'name': 'Брест'})[0],
                    4: Branch.objects.get_or_create(branch_crm_id=4, defaults={'name': 'Гродно'})[0],
                }
                
                for crm_id, b in canonical_branches.items():
                    Location.objects.get_or_create(name=f"Основная локация ({b.name})", branch=b)

                branch_map = {}
                for row in old_branches:
                    branch_name = row[0]
                    bn_lower = str(branch_name).lower()
                    if "минск" in bn_lower or "minsk" in bn_lower:
                        branch_map[branch_name] = canonical_branches[1]
                    elif "барановичи" in bn_lower:
                        branch_map[branch_name] = canonical_branches[2]
                    elif "брест" in bn_lower:
                        branch_map[branch_name] = canonical_branches[3]
                    elif "гродно" in bn_lower:
                        branch_map[branch_name] = canonical_branches[4]
                    else:
                        branch_map[branch_name] = canonical_branches[1]
                        logger.warning(f"migrate_from_sqlite: Неизвестный филиал '{branch_name}' привязан к Минску (CRM ID: 1)")

                default_branch = canonical_branches[1]

                # 2. Миграция тьюторов
                self.stdout.write("Шаг 2: Миграция тьюторов (TutorProfile)")
                cursor.execute("""
                    SELECT id, tutor_crm_id, tutor_name, branch, is_senior, phone_number, dob, note, avatar_url
                    FROM app_resumes_tutorprofile
                """)
                old_tutors = cursor.fetchall()
                tutor_map = {} # old_id -> new_tutor_obj
                
                for row in old_tutors:
                    old_id, crm_id, name, branch_name, is_senior, phone, dob, note, avatar_url = row
                    branch = branch_map.get(branch_name, default_branch)
                    
                    # Парсим дату рождения из строки DD.MM.YYYY
                    dob_parsed = None
                    if dob:
                        try:
                            dob_parsed = datetime.strptime(str(dob), "%d.%m.%Y").date()
                        except ValueError:
                            try:
                                dob_parsed = datetime.strptime(str(dob), "%Y-%m-%d").date()
                            except ValueError:
                                logger.warning(f"migrate_from_sqlite: не удалось распарсить dob='{dob}' для тьютора {name}")
                    
                    tutor, created = TutorProfile.objects.update_or_create(
                        tutor_crm_id=crm_id,
                        defaults={
                            'tutor_name': name,
                            'branch': branch,
                            'is_senior': bool(is_senior),
                            'phone_number': phone,
                            'dob': dob_parsed,
                            'note': note,
                            'avatar_url': avatar_url
                        }
                    )
                    tutor_map[old_id] = tutor

                # 3. Миграция групп
                self.stdout.write("Шаг 3: Миграция групп (Group)")
                cursor.execute("""
                    SELECT id, crm_group_id, branch_ids, teacher_ids, name, custom_aerodromnaya
                    FROM app_resumes_group
                """)
                old_groups = cursor.fetchall()
                group_map = {} # old_id -> new_group_obj
                
                for row in old_groups:
                    old_id, crm_id, branch_ids_raw, teacher_ids_raw, name, custom_aero = row
                    
                    # Пытаемся найти тьютора
                    tutor_obj = None
                    if teacher_ids_raw:
                        from django.db.models import Q
                        try:
                            t_ids = json.loads(teacher_ids_raw)
                            if isinstance(t_ids, list) and len(t_ids) > 0:
                                t_id = str(t_ids[0])
                            else:
                                t_id = str(t_ids)
                        except (json.JSONDecodeError, ValueError, TypeError):
                            t_id = str(teacher_ids_raw)
                            
                        # Ищем по tutor_crm_id ИЛИ по имени
                        tutor_obj = TutorProfile.objects.filter(
                            Q(tutor_crm_id=t_id) | Q(tutor_name=t_id)
                        ).first()
                            
                    group, created = Group.objects.update_or_create(
                        crm_group_id=str(crm_id),
                        defaults={
                            'branch': default_branch, # Пока ставим дефолтный, если нет branch_ids
                            'tutor': tutor_obj,
                            'name': name or f"Группа {crm_id}",
                            'custom_aerodromnaya': custom_aero == '1' or custom_aero is True or str(custom_aero).lower() == 'true'
                        }
                    )
                    group_map[old_id] = group

                # 4. Миграция студентов
                self.stdout.write("Шаг 4: Миграция студентов (Student)")
                cursor.execute("""
                    SELECT id, student_crm_id, student_name, group_id, study_start_date
                    FROM app_resumes_student
                """)
                old_students = cursor.fetchall()
                student_map = {} # old_id -> new_student_obj
                
                for row in old_students:
                    old_id, crm_id, name, group_id, study_start_date = row
                    
                    # Ищем группу
                    group_obj = group_map.get(group_id)
                    branch_obj = group_obj.branch if group_obj else default_branch
                    
                    # Парсим дату
                    start_date_obj = None
                    if study_start_date:
                        try:
                            start_date_obj = datetime.strptime(str(study_start_date), "%d.%m.%Y").date()
                        except ValueError:
                            try:
                                start_date_obj = datetime.strptime(str(study_start_date), "%Y-%m-%d").date()
                            except ValueError:
                                pass
                                
                    student, created = Student.objects.update_or_create(
                        student_crm_id=str(crm_id),
                        defaults={
                            'student_name': name,
                            'group': group_obj,
                            'branch': branch_obj,
                            'study_start_date': start_date_obj
                        }
                    )
                    student_map[old_id] = student

                # 5. Миграция резюме и отзывов
                self.stdout.write("Шаг 5: Миграция резюме (Resume) и отзывов (ParentReview)")
                cursor.execute("""
                    SELECT id, student_id, content, is_verified, created_at, updated_at
                    FROM app_resumes_resume
                """)
                old_resumes = cursor.fetchall()
                resume_count = 0
                for row in old_resumes:
                    old_id, student_id, content, is_verified, created_at, updated_at = row
                    student_obj = student_map.get(student_id)
                    
                    if student_obj:
                        Resume.objects.update_or_create(
                            student=student_obj,
                            content=content,
                            defaults={
                                'is_verified': bool(is_verified)
                            }
                        )
                        resume_count += 1
                        
                cursor.execute("""
                    SELECT id, student_id, content, created_at, updated_at
                    FROM app_resumes_parentreview
                """)
                old_reviews = cursor.fetchall()
                review_count = 0
                for row in old_reviews:
                    old_id, student_id, content, created_at, updated_at = row
                    student_obj = student_map.get(student_id)
                    
                    if student_obj:
                        # Поскольку ParentReview не имеет уникальных ключей кроме id,
                        # чтобы избежать дублей, ищем по студенту и контенту
                        ParentReview.objects.get_or_create(
                            student=student_obj,
                            content=content
                        )
                        review_count += 1

                self.stdout.write(self.style.SUCCESS(
                    f"Миграция успешно завершена! Перенесено:\n"
                    f"- Тьюторов: {len(tutor_map)}\n"
                    f"- Групп: {len(group_map)}\n"
                    f"- Студентов: {len(student_map)}\n"
                    f"- Резюме: {resume_count}\n"
                    f"- Отзывов: {review_count}"
                ))

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Произошла ошибка при миграции: {str(e)}"))
            logger.exception("migrate_from_sqlite error")
