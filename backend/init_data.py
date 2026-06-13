import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', '_settings.settings')
django.setup()

from django.contrib.auth import get_user_model
from core.models import Branch, Location, TutorProfile, Manager

User = get_user_model()

# 1. Создание суперпользователя admin:admin
if not User.objects.filter(username='admin').exists():
    User.objects.create_superuser('admin', 'admin@example.com', 'admin')
    print("Суперпользователь admin:admin успешно создан.")
else:
    print("Суперпользователь admin уже существует.")

# 2. Создание тестовых данных
b, _ = Branch.objects.get_or_create(name="Minsk", branch_crm_id=1)
loc, _ = Location.objects.get_or_create(name="Aero", branch=b)

tutor, created_tutor = TutorProfile.objects.get_or_create(
    phone_number="375291234567", 
    defaults={"tutor_name": "Test", "branch": b, "is_senior": True}
)
if created_tutor:
    print("Тестовый тьютор создан (375291234567).")

manager, created_manager = Manager.objects.get_or_create(
    phone="375297654321", 
    defaults={"name": "Manager", "location": loc}
)
if created_manager:
    print("Тестовый менеджер создан (375297654321).")
