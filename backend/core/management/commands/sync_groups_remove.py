import logging
from django.core.management.base import BaseCommand
from core.models import Group
from core.crm_integration import get_all_groups

logger = logging.getLogger("app_resume")


class Command(BaseCommand):
    help = "Удаление локальных групп, которые больше не существуют в CRM"

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Запустить команду без фактического удаления данных',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        
        try:
            self.stdout.write("Получение групп из CRM...")
            groups_data = get_all_groups()

            # Предохранитель (Safety Check): если get_all_groups возвращает None, прерываем выполнение
            if groups_data is None:
                self.stdout.write(self.style.ERROR(
                    "Ошибка: get_all_groups() вернул None. Произошла ошибка сети или API. Удаление прервано во избежание потери данных."
                ))
                logger.error("sync_groups_remove: get_all_groups() вернул None. Операция прервана.")
                return

            # Сбор всех ID групп, полученных из CRM
            active_crm_ids = {str(g.get("id")) for g in groups_data if g.get("id") is not None}
            self.stdout.write(f"Получено {len(active_crm_ids)} активных ID групп из CRM.")

            # Поиск локальных групп, отсутствующих в CRM
            groups_to_delete = Group.objects.exclude(crm_group_id__in=active_crm_ids)
            count_to_delete = groups_to_delete.count()

            if count_to_delete == 0:
                self.stdout.write(self.style.SUCCESS("Локальная база актуальна. Нет групп для удаления."))
                return

            if dry_run:
                self.stdout.write(self.style.WARNING(
                    f"[DRY-RUN] Было бы удалено {count_to_delete} неактуальных групп из локальной базы данных."
                ))
            else:
                self.stdout.write(self.style.WARNING(f"Удаление {count_to_delete} неактуальных групп..."))
                # Удаляем группы. Благодаря on_delete=CASCADE, связанные студенты также будут удалены (если настроено в модели, в новой модели student.group on_delete=CASCADE).
                deleted_count, deletions_detail = groups_to_delete.delete()
                groups_deleted = deletions_detail.get('core.Group', 0)
                
                self.stdout.write(self.style.SUCCESS(
                    f"Успешно удалено {groups_deleted} групп"
                ))

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Произошла ошибка при удалении групп: {str(e)}"))
            logger.error(f"sync_groups_remove: Ошибка: {str(e)}")
