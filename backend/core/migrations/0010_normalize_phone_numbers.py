from django.db import migrations

from core.models import normalize_phone


def forwards(apps, schema_editor):
    """
    Приводит уже сохранённые телефоны к формату хранения (только цифры),
    чтобы логин по номеру срабатывал для записей, заведённых вручную
    в формате '+375 (29) 123-45-67'.

    Запись пропускается, если нормализованный номер занят другой записью —
    поля уникальные, и падать миграцией из-за дубля в данных не нужно;
    такие пары видны в выводе миграции и разбираются вручную.
    """
    TutorProfile = apps.get_model("core", "TutorProfile")
    Manager = apps.get_model("core", "Manager")

    for model, field in ((TutorProfile, "phone_number"), (Manager, "phone")):
        for obj in model.objects.all():
            current = getattr(obj, field)
            normalized = normalize_phone(current)
            if normalized == current:
                continue
            if model.objects.filter(**{field: normalized}).exclude(pk=obj.pk).exists():
                print(
                    f"  Пропущен {model.__name__} pk={obj.pk}: "
                    f"номер {normalized} уже занят другой записью."
                )
                continue
            setattr(obj, field, normalized)
            obj.save(update_fields=[field])


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0009_employee"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
