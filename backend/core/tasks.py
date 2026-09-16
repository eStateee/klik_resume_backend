import logging
from datetime import datetime, time, timedelta

from asgiref.sync import async_to_sync
from celery import shared_task
from django.utils import timezone

from core.models import Branch, Module, TutorModule, TutorProfile
from core.services.alfa_crm_async import AlfaCRMError, get_tutor_subject_ids, get_week_range

logger = logging.getLogger("app_resume")


@shared_task
def sync_all_tutors_access():
    """
    Еженедельная синхронизация доступов тьюторов к модулям на основе их
    расписания в AlfaCRM за целевой период (с запасом LOOKAHEAD_WEEKS недель
    и окном WINDOW_WEEKS недель).

    Для каждого активного тьютора:
    - если доступа к модулю ещё нет — создаёт с expires_at = now + validity_period;
    - если доступ есть, но expires_at наступает раньше начала целевой недели —
      продлевает (expires_at = now + validity_period);
    - если доступ и так покрывает целевую неделю — не трогает.

    Отзыв просроченных доступов выполняется отдельной задачей
    revoke_expired_accesses (по условию expires_at < now).

    Предметы CRM, для которых в БД нет активного Module, игнорируются.
    """
    branch_ids = list(Branch.objects.values_list("branch_crm_id", flat=True))
    tutors = TutorProfile.objects.filter(is_active=True).exclude(
        tutor_crm_id__isnull=True
    ).exclude(tutor_crm_id="")

    date_from, date_to = get_week_range()
    target_start = timezone.make_aware(datetime.combine(date_from, time.min))

    for tutor in tutors:
        try:
            crm_id = int(tutor.tutor_crm_id)
        except (TypeError, ValueError):
            logger.warning(
                "Тьютор %s: некорректный tutor_crm_id=%r, пропускаем",
                tutor.pk,
                tutor.tutor_crm_id,
            )
            continue

        try:
            subject_ids = async_to_sync(get_tutor_subject_ids)(
                crm_id, branch_ids=branch_ids
            )
        except AlfaCRMError:
            logger.exception(
                "Тьютор %s (crm_id=%s): ошибка получения предметов из CRM, пропускаем",
                tutor.pk,
                crm_id,
            )
            continue

        active_modules = Module.objects.filter(
            subject_crm_id__in=subject_ids, is_active=True
        )

        now = timezone.now()
        for module in active_modules:
            expires_at = now + timedelta(days=module.validity_period)

            existing = TutorModule.objects.filter(
                tutor=tutor, module=module
            ).first()

            if existing is None:
                TutorModule.objects.create(
                    tutor=tutor, module=module, expires_at=expires_at
                )
            elif existing.expires_at < target_start:
                existing.expires_at = expires_at
                existing.save(update_fields=["expires_at"])

    logger.info("sync_all_tutors_access: обработано тьюторов=%s", tutors.count())


@shared_task
def revoke_expired_accesses():
    """Удалить доступы тьюторов к модулям, у которых истёк expires_at."""
    deleted, _ = TutorModule.objects.filter(expires_at__lt=timezone.now()).delete()
    if deleted:
        logger.info("revoke_expired_accesses: удалено доступов=%s", deleted)
