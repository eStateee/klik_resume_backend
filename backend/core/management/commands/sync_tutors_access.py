import logging
from datetime import datetime, time, timedelta

from asgiref.sync import async_to_sync, sync_to_async
from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import Branch, Module, TutorModule, TutorProfile
from core.services.alfa_crm_async import (
    AlfaCRMClient,
    AlfaCRMError,
    format_api_date,
    get_tutor_subject_ids,
    get_week_range,
    resolve_subject_names,
)

logger = logging.getLogger("app_resume")


class Command(BaseCommand):
    help = "Синхронизация доступов тьюторов к модулям по расписанию AlfaCRM"

    def add_arguments(self, parser):
        parser.add_argument(
            "--crm-id",
            type=int,
            dest="crm_id",
            help="Запустить проверку/синхронизацию только для одного тьютора по CRM ID",
        )
        parser.add_argument(
            "--names",
            action="store_true",
            help="Отображать названия предметов из AlfaCRM",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Только показать планируемые изменения доступов без записи в БД",
        )
        parser.add_argument(
            "--verbose",
            action="store_true",
            help="Включить подробный вывод логов",
        )

    def handle(self, *args, **options):
        single_crm_id = options.get("crm_id")
        with_names = options.get("names", False)
        dry_run = options.get("dry_run", False)
        verbose = options.get("verbose", False)

        if verbose:
            logger.setLevel(logging.DEBUG)

        date_from, date_to = get_week_range()
        target_end = timezone.make_aware(datetime.combine(date_to, time.max))

        self.stdout.write(
            self.style.NOTICE(
                f"Целевой период: {format_api_date(date_from)} — {format_api_date(date_to)} "
                f"({'[DRY-RUN - без записи в БД]' if dry_run else '[LIVE - с записью в БД]'})"
            )
        )

        branch_ids = list(Branch.objects.values_list("branch_crm_id", flat=True))
        if not branch_ids:
            self.stdout.write(self.style.ERROR("В базе данных нет филиалов."))
            return

        if single_crm_id:
            tutors = TutorProfile.objects.filter(tutor_crm_id=str(single_crm_id))
            if not tutors.exists():
                self.stdout.write(
                    self.style.WARNING(
                        f"Тьютор с tutor_crm_id={single_crm_id} не найден в БД. "
                        f"Запускаем тестовую проверку только по API CRM."
                    )
                )
                self._run_crm_only_check(single_crm_id, branch_ids, with_names)
                return
        else:
            tutors = TutorProfile.objects.filter(is_active=True).exclude(
                tutor_crm_id__isnull=True
            ).exclude(tutor_crm_id="")

        # QuerySet нельзя итерировать из async-контекста — материализуем заранее
        tutors_list = list(tutors)
        async_to_sync(self._process_tutors)(tutors_list, branch_ids, with_names, dry_run, target_end)

    # ------------------------------------------------------------------
    # Синхронные ORM-хелперы (вызываются через sync_to_async изнутри async)
    # ------------------------------------------------------------------

    def _get_active_modules(self, subject_ids):
        return list(Module.objects.filter(subject_crm_id__in=subject_ids, is_active=True))

    def _get_existing_tutor_modules(self, tutor):
        return list(TutorModule.objects.filter(tutor=tutor).select_related("module"))

    def _delete_tutor_modules(self, ids):
        deleted_cnt, _ = TutorModule.objects.filter(id__in=ids).delete()
        return deleted_cnt

    def _upsert_tutor_module(self, tutor, module, expires_at):
        _, created = TutorModule.objects.update_or_create(
            tutor=tutor,
            module=module,
            defaults={"expires_at": expires_at},
        )
        return created

    # ------------------------------------------------------------------
    # Асинхронный пайплайн
    # ------------------------------------------------------------------

    async def _process_tutors(
        self, tutors, branch_ids, with_names: bool, dry_run: bool, target_end
    ):
        async with AlfaCRMClient() as client:
            for tutor in tutors:
                try:
                    crm_id = int(tutor.tutor_crm_id)
                except (TypeError, ValueError):
                    self.stdout.write(
                        self.style.WARNING(
                            f"Тьютор {tutor.pk} ({tutor.tutor_name}): "
                            f"некорректный tutor_crm_id={tutor.tutor_crm_id!r}, пропускаем"
                        )
                    )
                    continue

                self.stdout.write(
                    self.style.HTTP_INFO(
                        f"\n--- Тьютор {tutor.pk}: {tutor.tutor_name} (crm_id={crm_id}) ---"
                    )
                )

                try:
                    subject_ids = await get_tutor_subject_ids(
                        crm_id, branch_ids=branch_ids, client=client
                    )
                except AlfaCRMError as exc:
                    self.stdout.write(
                        self.style.ERROR(
                            f"Ошибка AlfaCRM для тьютора {crm_id}: {exc}"
                        )
                    )
                    continue

                self.stdout.write(f"Найдено ID предметов в CRM: {subject_ids}")

                if with_names and subject_ids:
                    names_map = await resolve_subject_names(client, subject_ids)
                    for sid in subject_ids:
                        self.stdout.write(f"  • {sid}: {names_map.get(sid, '<не найден>')}")

                # ORM — только через sync_to_async
                active_modules = await sync_to_async(self._get_active_modules)(subject_ids)
                active_module_ids = [m.pk for m in active_modules]
                self.stdout.write(
                    f"Соответствующих активных модулей в платформе: {len(active_modules)} "
                    f"({[m.name for m in active_modules]})"
                )

                existing_modules = await sync_to_async(self._get_existing_tutor_modules)(tutor)
                to_delete = [
                    tm for tm in existing_modules if tm.module_id not in active_module_ids
                ]

                if to_delete:
                    self.stdout.write(
                        self.style.WARNING(
                            f"Доступы к удалению ({len(to_delete)}): "
                            f"{[tm.module.name for tm in to_delete]}"
                        )
                    )
                else:
                    self.stdout.write("Нет доступов к удалению.")

                now = timezone.now()
                if not dry_run:
                    if to_delete:
                        delete_ids = [tm.pk for tm in to_delete]
                        deleted_cnt = await sync_to_async(self._delete_tutor_modules)(delete_ids)
                        self.stdout.write(
                            self.style.SUCCESS(f"Удалено устаревших доступов: {deleted_cnt}")
                        )

                    updated_cnt = 0
                    created_cnt = 0
                    for module in active_modules:
                        expires_at = max(
                            now + timedelta(days=module.validity_period),
                            target_end + timedelta(days=module.validity_period),
                        )
                        created = await sync_to_async(self._upsert_tutor_module)(
                            tutor, module, expires_at
                        )
                        if created:
                            created_cnt += 1
                        else:
                            updated_cnt += 1

                    self.stdout.write(
                        self.style.SUCCESS(
                            f"Выдано доступов: новых={created_cnt}, продлено={updated_cnt}"
                        )
                    )
                else:
                    self.stdout.write(
                        self.style.NOTICE(
                            f"[DRY-RUN] Было бы выдано/продлено доступов: {len(active_modules)}"
                        )
                    )

    def _run_crm_only_check(self, crm_id: int, branch_ids, with_names: bool):
        async def _check():
            async with AlfaCRMClient() as client:
                subject_ids = await get_tutor_subject_ids(
                    crm_id, branch_ids=branch_ids, client=client
                )
                self.stdout.write(f"crm_id={crm_id} -> subject_ids={subject_ids}")
                if with_names and subject_ids:
                    names_map = await resolve_subject_names(client, subject_ids)
                    for sid in subject_ids:
                        self.stdout.write(f"  • {sid}: {names_map.get(sid, '<не найден>')}")

        async_to_sync(_check)()
