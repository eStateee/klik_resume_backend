import logging
from django.core.management.base import BaseCommand
from core.models import Location, Branch
from core.crm_integration import get_all_locations_from_crm

logger = logging.getLogger("app_resume")


class Command(BaseCommand):
    help = "Синхронизация локаций из CRM с базой данных"

    def handle(self, *args, **options):
        try:
            branches = list(Branch.objects.all())
            if not branches:
                self.stdout.write(self.style.WARNING("Нет филиалов в базе данных."))
                return

            branches_dict = {b.branch_crm_id: b for b in branches}

            # 1. Получаем все локации из CRM
            self.stdout.write("Получение локаций из CRM...")
            locations_data = get_all_locations_from_crm(branches)
            if locations_data is None:
                self.stdout.write(self.style.ERROR("Не удалось получить локации из CRM."))
                return

            self.stdout.write(f"Получено {len(locations_data)} локаций из CRM.")

            # 2. Синхронизация локаций
            synced_db_pks = set()
            created_count = 0
            updated_count = 0
            skipped_count = 0

            for item in locations_data:
                crm_id = item.get("id")
                name = item.get("name")

                if not crm_id or not name:
                    self.stdout.write(self.style.WARNING(
                        f"  Пропущена локация: отсутствует id или name. Данные: {item}"
                    ))
                    skipped_count += 1
                    continue

                # Определяем филиал: CRM возвращает branch_id (единичный int)
                branch_crm_id = item.get("branch_id") or item.get("fetched_branch_crm_id")
                branch_obj = branches_dict.get(branch_crm_id)
                if not branch_obj:
                    # Фолбэк на первый филиал
                    branch_obj = Branch.objects.filter(branch_crm_id=1).first()
                    if not branch_obj:
                        self.stdout.write(self.style.WARNING(
                            f"  Пропущена локация '{name}' (CRM ID: {crm_id}): нет подходящего филиала."
                        ))
                        skipped_count += 1
                        continue
                    logger.warning(
                        f"sync_locations: локация {crm_id} ({name}) — нет филиала из CRM, привязана к Минску."
                    )

                # CRM возвращает is_active как int (1/0)
                is_active = bool(item.get("is_active", 1))

                location, created = Location.objects.update_or_create(
                    location_crm_id=crm_id,
                    defaults={
                        "name": name,
                        "branch": branch_obj,
                        "is_active": is_active,
                    },
                )
                synced_db_pks.add(location.pk)

                if created:
                    created_count += 1
                else:
                    updated_count += 1

            self.stdout.write(self.style.SUCCESS(
                f"Синхронизация завершена. Создано: {created_count}, "
                f"Обновлено: {updated_count}, Пропущено: {skipped_count}"
            ))

            # 3. Деактивация локаций, отсутствующих в CRM
            locations_to_deactivate = Location.objects.filter(
                is_active=True, location_crm_id__isnull=False
            ).exclude(pk__in=synced_db_pks)
            deactivate_count = locations_to_deactivate.count()

            if deactivate_count > 0:
                for loc in locations_to_deactivate:
                    self.stdout.write(self.style.WARNING(
                        f"  Деактивирована: {loc.name} (ID: {loc.pk}, CRM ID: {loc.location_crm_id})"
                    ))
                locations_to_deactivate.update(is_active=False)
                self.stdout.write(self.style.WARNING(
                    f"Деактивировано {deactivate_count} локаций, отсутствующих в CRM."
                ))
            else:
                self.stdout.write("Нет локаций для деактивации.")

        except Exception as e:
            self.stdout.write(self.style.ERROR(
                f"Ошибка при синхронизации локаций: {str(e)}"
            ))
            logger.exception("sync_locations error")
