import logging
from django.core.management.base import BaseCommand
from core.models import Group, Student
from core.crm_integration import get_group_clients_from_crm

logger = logging.getLogger("app_resume")


class Command(BaseCommand):
    help = "Удаление локальных студентов, которые больше не числятся ни в одной группе CRM"

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Запустить команду без фактического удаления данных',
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Принудительно продолжить удаление, даже если превышен лимит 30%',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        force = options['force']
        
        try:
            self.stdout.write("Проверка всех студентов в существующих группах из CRM...")
            groups = Group.objects.select_related('branch').all()

            if not groups.exists():
                self.stdout.write(self.style.WARNING("В локальной базе нет групп. Невозможно проверить студентов."))
                return

            active_crm_student_ids = set()
            api_failed = False

            for group in groups:
                branch_crm_id = str(group.branch.branch_crm_id)

                self.stdout.write(f"Получение клиентов для группы с CRM ID: {group.crm_group_id}, филиал: {branch_crm_id}...")
                group_clients = get_group_clients_from_crm(group.crm_group_id, branch_crm_id)

                # Предохранитель (Safety Check): Если вернулся None, прерываем проверку
                if group_clients is None:
                    api_failed = True
                    self.stdout.write(self.style.ERROR(
                        f"Ошибка: Не удалось получить клиентов для группы {group.crm_group_id}."
                    ))
                    logger.error(f"sync_students_remove: get_group_clients_from_crm вернул None для группы {group.crm_group_id}. Прерывание.")
                    break
                
                for client in group_clients:
                    customer_id = client.get("customer_id")
                    if customer_id:
                        active_crm_student_ids.add(str(customer_id))

            if api_failed:
                self.stdout.write(self.style.ERROR("Синхронизация прервана из-за ошибок API для предотвращения потери данных."))
                return

            self.stdout.write(f"Собрано {len(active_crm_student_ids)} уникальных ID студентов из CRM.")

            # Вычисляем студентов, подлежащих удалению
            students_to_delete = Student.objects.exclude(student_crm_id__in=active_crm_student_ids)
            count_to_delete = students_to_delete.count()

            if count_to_delete == 0:
                self.stdout.write(self.style.SUCCESS("Локальная база актуальна. Нет студентов для удаления."))
                return

            # Проверка предохранителя на 30%
            total_students_count = Student.objects.count()
            if total_students_count > 0:
                deletion_ratio = count_to_delete / total_students_count
                if deletion_ratio > 0.3 and not force:
                    self.stdout.write(self.style.ERROR(
                        f"ОШИБКА БЕЗОПАСНОСТИ: Попытка удалить {count_to_delete} из {total_students_count} студентов ({deletion_ratio:.1%}), "
                        "что превышает порог в 30%!\n"
                        "Операция остановлена во избежание массовой потери данных. Для принудительного запуска используйте флаг --force."
                    ))
                    logger.error(f"sync_students_remove: Прервано удаление {count_to_delete}/{total_students_count} ({deletion_ratio:.1%}) без флага --force.")
                    return

            if dry_run:
                self.stdout.write(self.style.WARNING(
                    f"[DRY-RUN] Было бы удалено {count_to_delete} неактуальных студентов из локальной базы данных."
                ))
            else:
                self.stdout.write(self.style.WARNING(f"Удаление {count_to_delete} неактуальных студентов..."))
                deleted_count, deletions_detail = students_to_delete.delete()
                students_deleted = deletions_detail.get('core.Student', 0)
                self.stdout.write(self.style.SUCCESS(
                    f"Успешно удалено {students_deleted} студентов (всего объектов: {deleted_count})."
                ))

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Произошла ошибка при удалении студентов: {str(e)}"))
            logger.error(f"sync_students_remove: Ошибка: {str(e)}")
