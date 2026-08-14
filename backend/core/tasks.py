import logging
from datetime import timedelta

from asgiref.sync import async_to_sync
from celery import shared_task
from django.utils import timezone

from core.models import Branch, Module, TutorModule, TutorProfile
from core.services.alfa_crm_async import AlfaCRMError, get_tutor_subject_ids

logger = logging.getLogger("app_resume")


@shared_task
def sync_all_tutors_access():
    """
    Еженедельная синхронизация доступов тьюторов к модулям на основе их
    расписания в AlfaCRM на предстоящую учебную неделю (ПН-ВС).

    Для каждого активного тьютора:
    - доступы к модулям, предметы которых он больше не ведёт, удаляются немедленно;
    - доступы к модулям по предметам, которые он ведёт на этой неделе, продлеваются
      (expires_at = сейчас + Module.validity_period).

    Предметы CRM, для которых в БД нет активного Module, игнорируются.
    """
    branch_ids = list(Branch.objects.values_list("branch_crm_id", flat=True))
    tutors = TutorProfile.objects.filter(is_active=True).exclude(
        tutor_crm_id__isnull=True
    ).exclude(tutor_crm_id="")

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

        TutorModule.objects.filter(tutor=tutor).exclude(
            module__in=active_modules
        ).delete()

        now = timezone.now()
        for module in active_modules:
            TutorModule.objects.update_or_create(
                tutor=tutor,
                module=module,
                defaults={"expires_at": now + timedelta(days=module.validity_period)},
            )

    logger.info("sync_all_tutors_access: обработано тьюторов=%s", tutors.count())


@shared_task
def revoke_expired_accesses():
    """Удалить доступы тьюторов к модулям, у которых истёк expires_at."""
    deleted, _ = TutorModule.objects.filter(expires_at__lt=timezone.now()).delete()
    if deleted:
        logger.info("revoke_expired_accesses: удалено доступов=%s", deleted)
