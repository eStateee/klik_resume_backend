import logging
from datetime import datetime
from django.core.management.base import BaseCommand
from core.models import Group, Student, Branch
from core.crm_integration import get_group_clients_from_crm

logger = logging.getLogger("app_resume")


def parse_date(date_str):
    if not date_str:
        return None
    try:
        # Assuming DD.MM.YYYY format
        return datetime.strptime(date_str, "%d.%m.%Y").date()
    except ValueError:
        try:
            # Fallback to YYYY-MM-DD
            return datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            return None


class Command(BaseCommand):
    help = "Synchronize all students from CRM to the database"

    def handle(self, *args, **options):
        try:
            groups = Group.objects.select_related('branch').all()

            if not groups.exists():
                self.stdout.write(self.style.WARNING("No groups found in database. Run sync_groups first."))
                return

            synced_student_ids = set()
            created_count = 0
            updated_count = 0
            api_failed = False

            for group in groups:
                branch_crm_id = str(group.branch.branch_crm_id)

                self.stdout.write(f"ADD Получение клиентов для группы с CRM ID {group.crm_group_id}, филиал: {branch_crm_id}...")
                group_clients = get_group_clients_from_crm(group.crm_group_id, branch_crm_id)

                # Safety-check: если CRM вернул None, прерываем
                if group_clients is None:
                    api_failed = True
                    self.stdout.write(self.style.ERROR(
                        f"Ошибка: не удалось получить клиентов для группы {group.crm_group_id}."
                    ))
                    logger.error(f"sync_students: get_group_clients_from_crm вернул None для группы {group.crm_group_id}. Прерывание.")
                    break

                if group_clients:
                    for client in group_clients:
                        customer_id = str(client.get("customer_id"))
                        client_name = client.get("client_name")

                        if customer_id and client_name:
                            study_start_date_str = client.get("custom_datano")
                            study_start_date = parse_date(study_start_date_str)
                            
                            # Определяем реальный филиал студента из CRM
                            student_branch = group.branch
                            branch_ids = client.get("branch_ids", [])
                            if branch_ids and len(branch_ids) > 0:
                                try:
                                    # Пытаемся найти первый филиал из массива
                                    crm_b_id = int(branch_ids[0])
                                    found_branch = Branch.objects.filter(branch_crm_id=crm_b_id).first()
                                    if found_branch:
                                        student_branch = found_branch
                                except (ValueError, TypeError):
                                    pass
                            
                            student, created = Student.objects.update_or_create(
                                student_crm_id=customer_id, 
                                defaults={
                                    "student_name": client_name, 
                                    "group": group,
                                    "branch": student_branch,
                                    "study_start_date": study_start_date
                                }
                            )
                            synced_student_ids.add(customer_id)
                            if created:
                                created_count += 1
                            else:
                                updated_count += 1

            if api_failed:
                self.stdout.write(self.style.ERROR("Синхронизация прервана из-за ошибок API."))
                return

            self.stdout.write(self.style.SUCCESS(
                f"Синхронизация завершена: {len(synced_student_ids)} уникальных студентов. "
                f"Создано: {created_count}, Обновлено: {updated_count}"
            ))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"An error occurred while synchronizing students: {str(e)}"))
            logger.exception("sync_students error")
