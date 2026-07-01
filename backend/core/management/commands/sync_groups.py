import logging
from django.core.management.base import BaseCommand
from core.models import Group, Branch, TutorProfile
from core.crm_integration import get_all_groups

logger = logging.getLogger("app_resume")


class Command(BaseCommand):
    help = "Synchronize all groups from CRM to the database"

    def handle(self, *args, **options):
        try:
            self.stdout.write("Получение групп из CRM...")
            groups_data = get_all_groups()
            
            if not groups_data:
                self.stdout.write(self.style.WARNING("No groups found in CRM"))
                return

            synced_count = 0
            skipped_count = 0
            
            for group_data in groups_data:
                crm_group_id = str(group_data.get("id"))
                name = group_data.get("name")
                
                # Извлечение teacher IDs из CRM-ответа:
                # CRM возвращает поле `teachers` — массив объектов [{"id": 123, ...}]
                # Фолбэк на `teacher_ids` — плоский массив [123, 456], если `teachers` пуст
                raw_teachers = group_data.get("teachers", [])
                if raw_teachers and isinstance(raw_teachers, list):
                    teacher_ids = [t.get("id") for t in raw_teachers if isinstance(t, dict) and t.get("id")]
                else:
                    teacher_ids = group_data.get("teacher_ids", [])
                
                branch_ids = group_data.get("branch_ids", [])
                custom_aerodromnaya = group_data.get("custom_aerodromnaya", False)
                if custom_aerodromnaya is None:
                    custom_aerodromnaya = False
                elif isinstance(custom_aerodromnaya, str):
                    custom_aerodromnaya = custom_aerodromnaya.lower() == "true"
                
                # Обработка филиала
                branch_obj = None
                if branch_ids:
                    first_branch_id = branch_ids[0] if isinstance(branch_ids, list) else branch_ids
                    try:
                        branch_obj = Branch.objects.get(branch_crm_id=int(first_branch_id))
                    except (Branch.DoesNotExist, ValueError, TypeError):
                        logger.warning(
                            f"sync_groups: не найден филиал с CRM ID = {first_branch_id} "
                            f"для группы {crm_group_id} ({name})"
                        )
                
                if not branch_obj:
                    # Используем дефолтный филиал (Минск) вместо пропуска
                    branch_obj = Branch.objects.filter(branch_crm_id=1).first()
                    if not branch_obj:
                        self.stdout.write(self.style.WARNING(
                            f"ПРОПУСК группы crm_id={crm_group_id}, name=\"{name}\": нет ни нужного, ни дефолтного филиала."
                        ))
                        skipped_count += 1
                        continue
                    logger.warning(
                        f"sync_groups: группа {crm_group_id} ({name}) — нет филиала из CRM, привязана к Минску."
                    )
                
                # Обработка преподавателя — поиск только по tutor_crm_id среди активных
                tutor_obj = None
                if isinstance(teacher_ids, list) and len(teacher_ids) > 0:
                    first_teacher_id = str(teacher_ids[0])
                    tutor_obj = TutorProfile.objects.filter(
                        tutor_crm_id=first_teacher_id, is_active=True
                    ).first()
                    
                    if len(teacher_ids) > 1:
                        logger.warning(
                            f"sync_groups: Группа {crm_group_id} ({name}) имеет несколько преподавателей {teacher_ids}. "
                            f"Привязан только первый: {first_teacher_id}."
                        )
                elif teacher_ids:
                    tutor_obj = TutorProfile.objects.filter(
                        tutor_crm_id=str(teacher_ids), is_active=True
                    ).first()
                        
                # Обновление или создание группы
                group, created = Group.objects.update_or_create(
                    crm_group_id=crm_group_id,
                    defaults={
                        "branch": branch_obj,
                        "tutor": tutor_obj,
                        "name": name or f"Group {crm_group_id}",
                        "custom_aerodromnaya": custom_aerodromnaya,
                    },
                )
                
                synced_count += 1

            result_msg = f"Successfully synchronized {synced_count} groups"
            if skipped_count:
                result_msg += f", skipped {skipped_count} groups"
            self.stdout.write(self.style.SUCCESS(result_msg))

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"An error occurred while synchronizing groups: {str(e)}"))
            logger.exception("sync_groups error")
