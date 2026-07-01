import logging
from datetime import datetime
from django.core.management.base import BaseCommand
from core.models import TutorProfile, Branch
from core.crm_integration import get_all_tutors_from_crm

logger = logging.getLogger("app_resume")

# Белорусский номер: 375 + 2 цифры оператора + 7 цифр = 12 цифр всего
PHONE_LENGTH = 12


def parse_date(date_str):
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str, "%d.%m.%Y").date()
    except ValueError:
        try:
            return datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            return None


def clean_phone(raw_phone_value):
    """
    Извлекает первый телефон из значения CRM (строка или массив),
    оставляет только цифры и обрезает до 12 символов (формат 375XXXXXXXXX).
    """
    raw = ""
    if isinstance(raw_phone_value, list):
        if len(raw_phone_value) > 0:
            raw = str(raw_phone_value[0])
    elif isinstance(raw_phone_value, str):
        raw = raw_phone_value.split(',')[0].strip()

    digits = "".join(filter(str.isdigit, raw))
    if not digits:
        return None

    # Обрезаем до 12 цифр (375 + 9 цифр)
    if len(digits) > PHONE_LENGTH:
        digits = digits[:PHONE_LENGTH]
    return digits


def is_junk_tutor(item):
    """Проверяет, является ли запись мусорной (например, 'Штраф')."""
    name = item.get("name", "")
    if not name:
        return True
    junk_keywords = ["штраф"]
    return any(kw in name.lower() for kw in junk_keywords)


def deduplicate_crm_tutors(tutors_data):
    """
    CRM возвращает одного тьютора из каждого филиала, к которому он привязан.
    Дедуплицируем по CRM ID, сохраняя первое вхождение.
    """
    seen = {}
    for item in tutors_data:
        crm_id = str(item.get("id"))
        if crm_id not in seen:
            seen[crm_id] = item
    return list(seen.values())


class Command(BaseCommand):
    help = "Синхронизация тьюторов из CRM с базой данных"

    def handle(self, *args, **options):
        try:
            branches = list(Branch.objects.all())
            if not branches:
                self.stdout.write(self.style.WARNING("Нет филиалов в базе данных."))
                return

            branches_dict = {b.branch_crm_id: b for b in branches}

            # 1. Получаем всех тьюторов из CRM
            self.stdout.write("Получение тьюторов из CRM...")
            tutors_data = get_all_tutors_from_crm(branches)
            if tutors_data is None:
                self.stdout.write(self.style.ERROR("Не удалось получить тьюторов из CRM."))
                return

            # 2. Фильтрация мусора и дедупликация
            tutors_data = [t for t in tutors_data if not is_junk_tutor(t)]
            tutors_data = deduplicate_crm_tutors(tutors_data)
            self.stdout.write(f"Получено {len(tutors_data)} уникальных тьюторов из CRM (после фильтрации).")

            # 3. Строим индекс существующих тьюторов по phone_number для сопоставления
            existing_by_phone = {
                t.phone_number: t for t in TutorProfile.objects.all()
            }
            existing_by_crm_id = {
                t.tutor_crm_id: t for t in TutorProfile.objects.filter(tutor_crm_id__isnull=False)
            }

            synced_crm_ids = set()
            synced_db_pks = set()
            created_count = 0
            updated_count = 0
            skipped_count = 0

            for item in tutors_data:
                crm_id = str(item.get("id"))
                name = item.get("name")
                phone_raw = item.get("phone")
                phone = clean_phone(phone_raw)

                if not phone:
                    self.stdout.write(self.style.WARNING(
                        f"  Пропущен тьютор '{name}' (CRM ID: {crm_id}): нет телефона."
                    ))
                    skipped_count += 1
                    continue

                # Определяем филиал
                fetched_branch_id = item.get('fetched_branch_crm_id')
                tutor_branch = branches_dict.get(fetched_branch_id)
                branch_ids = item.get("branch_ids", [])
                if branch_ids and len(branch_ids) > 0:
                    try:
                        crm_b_id = int(branch_ids[0])
                        if crm_b_id in branches_dict:
                            tutor_branch = branches_dict[crm_b_id]
                    except (ValueError, TypeError):
                        pass
                if not tutor_branch:
                    tutor_branch = branches[0]

                dob = parse_date(item.get("dob"))
                note = item.get("note", "")

                # Сопоставление: сначала по CRM ID, потом по телефону
                existing_tutor = existing_by_crm_id.get(crm_id)
                if not existing_tutor:
                    existing_tutor = existing_by_phone.get(phone)

                if existing_tutor:
                    # Обновляем существующую запись
                    existing_tutor.tutor_crm_id = crm_id
                    existing_tutor.tutor_name = name
                    existing_tutor.branch = tutor_branch
                    existing_tutor.phone_number = phone
                    existing_tutor.dob = dob
                    existing_tutor.note = note
                    existing_tutor.is_active = True
                    existing_tutor.save()
                    synced_db_pks.add(existing_tutor.pk)
                    updated_count += 1
                else:
                    # Проверяем, не занят ли телефон другим тьютором (дубль в CRM)
                    if TutorProfile.objects.filter(phone_number=phone).exists():
                        self.stdout.write(self.style.WARNING(
                            f"  Пропущен тьютор '{name}' (CRM ID: {crm_id}): телефон {phone} уже занят."
                        ))
                        skipped_count += 1
                        continue

                    new_tutor = TutorProfile.objects.create(
                        tutor_crm_id=crm_id,
                        tutor_name=name,
                        branch=tutor_branch,
                        phone_number=phone,
                        dob=dob,
                        note=note,
                        is_active=True,
                    )
                    synced_db_pks.add(new_tutor.pk)
                    created_count += 1

                synced_crm_ids.add(crm_id)

                # Обновляем индекс
                existing_by_crm_id[crm_id] = existing_tutor or new_tutor
                existing_by_phone[phone] = existing_tutor or new_tutor

            self.stdout.write(self.style.SUCCESS(
                f"Синхронизация завершена. Создано: {created_count}, Обновлено: {updated_count}, "
                f"Пропущено: {skipped_count}"
            ))

            # 4. Мягкое удаление тьюторов, которых нет в CRM
            tutors_to_deactivate = TutorProfile.objects.filter(
                is_active=True
            ).exclude(pk__in=synced_db_pks)
            deactivate_count = tutors_to_deactivate.count()

            if deactivate_count > 0:
                for t in tutors_to_deactivate:
                    self.stdout.write(self.style.WARNING(
                        f"  Деактивирован: {t.tutor_name} (ID: {t.pk}, CRM ID: {t.tutor_crm_id})"
                    ))
                tutors_to_deactivate.update(is_active=False)
                self.stdout.write(self.style.WARNING(
                    f"Деактивировано {deactivate_count} тьюторов, отсутствующих в CRM."
                ))
            else:
                self.stdout.write("Нет тьюторов для деактивации.")

        except Exception as e:
            self.stdout.write(self.style.ERROR(
                f"Ошибка при синхронизации тьюторов: {str(e)}"
            ))
            logger.exception("sync_tutors error")
