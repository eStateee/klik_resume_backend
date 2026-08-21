from datetime import timedelta
from unittest.mock import patch
from django.test import TestCase
from django.core.cache import cache
from django.core.management import call_command
from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.auth import authenticate
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework import status
from core.models import (
    Branch, Location, Manager, TutorProfile, Group, Employee,
    Student, Resume, ParentReview, normalize_phone,
)
from core.serializers import CustomTokenObtainPairSerializer
from rest_framework_simplejwt.tokens import AccessToken

class AuthenticationTestCase(TestCase):
    def setUp(self):
        # Create Branch
        self.branch = Branch.objects.create(name="Minsk Test", branch_crm_id=99)
        
        # Create Location
        self.location = Location.objects.create(name="Center Test", branch=self.branch)
        
        # Create Manager
        self.manager = Manager.objects.create(
            name="Test Manager",
            phone="375291112233",
            location=self.location,
            is_senior=True
        )
        
        # Create Tutor
        self.tutor = TutorProfile.objects.create(
            tutor_name="Test Tutor",
            phone_number="375294445566",
            branch=self.branch,
            is_senior=False
        )

        # Create Group for the Tutor
        self.group = Group.objects.create(
            crm_group_id="crm_group_test_1",
            branch=self.branch,
            tutor=self.tutor,
            name="Test Group"
        )

        self.client = APIClient()

    def test_passwordless_backend_manager(self):
        # Test authenticating a manager via clean phone number
        user = authenticate(phone_number="375291112233")
        self.assertIsNotNone(user)
        self.assertEqual(user.name, "Test Manager")
        self.assertTrue(isinstance(user, Manager))
        self.assertTrue(user.is_authenticated)
        self.assertFalse(user.is_anonymous)
        self.assertTrue(user.is_active)

    def test_passwordless_backend_tutor(self):
        # Test authenticating a tutor via formatted phone number (should clean it up)
        # Note: auth backend receives the phone number from serializer where it is already cleaned.
        # But we can test it directly:
        user = authenticate(phone_number="375294445566")
        self.assertIsNotNone(user)
        self.assertEqual(user.tutor_name, "Test Tutor")
        self.assertTrue(isinstance(user, TutorProfile))
        self.assertTrue(user.is_authenticated)
        self.assertFalse(user.is_anonymous)
        self.assertTrue(user.is_active)

    def test_passwordless_backend_invalid_phone(self):
        user = authenticate(phone_number="375299999999")
        self.assertIsNone(user)

    def test_jwt_token_generation_and_authentication(self):
        # Test manager token generation
        serializer = CustomTokenObtainPairSerializer()
        manager_data = serializer.validate({"phone_number": "375291112233"})
        self.assertIn("access", manager_data)
        
        # Authenticate request with manager access token
        access_token = manager_data["access"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access_token}")
        response = self.client.get("/api/groups/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Test tutor token generation
        tutor_data = serializer.validate({"phone_number": "375-29-444-55-66"})
        self.assertIn("access", tutor_data)
        
        # Authenticate request with tutor access token
        access_token = tutor_data["access"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access_token}")
        response = self.client.get("/api/groups/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Tutor should see their group
        results = response.data.get("results", response.data)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["name"], "Test Group")

    def test_unauthorized_access(self):
        # Without token, should return 401
        self.client.credentials()
        response = self.client.get("/api/groups/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class InactiveTutorTestCase(TestCase):
    """Тесты блокировки деактивированных тьюторов."""

    def setUp(self):
        self.branch = Branch.objects.create(name="Minsk Inactive", branch_crm_id=100)
        self.tutor = TutorProfile.objects.create(
            tutor_name="Inactive Tutor",
            phone_number="375297778899",
            branch=self.branch,
            is_senior=False,
            is_active=True,
        )
        self.client = APIClient()

    def test_inactive_tutor_authenticate_returns_none(self):
        """authenticate() не возвращает деактивированного тьютора."""
        self.tutor.is_active = False
        self.tutor.save()

        user = authenticate(phone_number="375297778899")
        self.assertIsNone(user)

    def test_inactive_tutor_login_rejected(self):
        """POST /api/auth/login/ возвращает 400 для деактивированного тьютора."""
        self.tutor.is_active = False
        self.tutor.save()

        response = self.client.post("/api/auth/login/", {"phone_number": "375297778899"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_inactive_tutor_existing_token_rejected(self):
        """Токен, выданный до деактивации, перестаёт работать после is_active=False."""
        # Получаем токен пока тьютор ещё активен
        response = self.client.post("/api/auth/login/", {"phone_number": "375297778899"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        access_token = response.data["access"]

        # Деактивируем тьютора
        self.tutor.is_active = False
        self.tutor.save()

        # Токен должен перестать работать
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access_token}")
        response = self.client.get("/api/groups/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_reactivated_tutor_can_login(self):
        """После реактивации тьютор снова может авторизоваться."""
        self.tutor.is_active = False
        self.tutor.save()
        self.assertIsNone(authenticate(phone_number="375297778899"))

        # Реактивация
        self.tutor.is_active = True
        self.tutor.save()

        user = authenticate(phone_number="375297778899")
        self.assertIsNotNone(user)
        self.assertTrue(user.is_active)


class SyncLocationsTestCase(TestCase):
    """Тесты команды синхронизации локаций из CRM."""

    def setUp(self):
        self.branch = Branch.objects.create(name="Минск", branch_crm_id=1)

    @patch("core.management.commands.sync_locations.get_all_locations_from_crm")
    def test_sync_locations_creates_and_preserves_custom_name(self, mock_crm):
        """Новая локация получает имя из CRM, а при повторном запуске вручную измененное имя в БД не перезаписывается."""
        # 1. Первый запуск: локации нет в БД, CRM возвращает name='CRM Name 1'
        mock_crm.return_value = [
            {"id": 501, "name": "CRM Name 1", "branch_id": 1, "is_active": 1}
        ]
        call_command("sync_locations")

        loc = Location.objects.get(location_crm_id=501)
        self.assertEqual(loc.name, "CRM Name 1")

        # 2. Пользователь меняет название локации в БД
        loc.name = "Кастомное название локации"
        loc.save()

        # 3. Повторный запуск синхронизации: CRM передает исходное имя 'CRM Name 1'
        call_command("sync_locations")

        loc.refresh_from_db()
        # Проверяем, что имя в БД НЕ перезаписалось значением из CRM
        self.assertEqual(loc.name, "Кастомное название локации")


class SyncGroupsTestCase(TestCase):
    """Тесты команды синхронизации групп и привязки к локациям."""

    def setUp(self):
        self.branch = Branch.objects.create(name="Минск", branch_crm_id=1)
        self.location = Location.objects.create(
            name="Локация Аэродромная", location_crm_id=501, branch=self.branch
        )

    @patch("core.management.commands.sync_groups.get_all_groups")
    def test_sync_groups_links_location_correctly(self, mock_get_groups):
        mock_get_groups.return_value = [
            {
                "id": "1001",
                "name": "Группа 1001",
                "branch_ids": [1],
                "custom_location": "501",
            },
            {
                "id": "1002",
                "name": "Группа 1002",
                "branch_ids": [1],
                "custom_location": 999,  # Несуществующая локация
            },
            {
                "id": "1003",
                "name": "Группа 1003",
                "branch_ids": [1],
                "custom_location": None,
            },
        ]

        call_command("sync_groups")

        group1 = Group.objects.get(crm_group_id="1001")
        self.assertEqual(group1.location, self.location)

        group2 = Group.objects.get(crm_group_id="1002")
        self.assertIsNone(group2.location)

        group3 = Group.objects.get(crm_group_id="1003")
        self.assertIsNone(group3.location)


class StudentFieldsTestCase(TestCase):
    """Тесты полей is_review_exist и group_name в StudentSerializer."""

    def setUp(self):
        from core.models import Student, ParentReview
        from core.serializers import StudentSerializer

        self.branch = Branch.objects.create(name="Field Test Branch", branch_crm_id=200)
        self.group = Group.objects.create(
            crm_group_id="field_test_group",
            branch=self.branch,
            name="Алгоритмы Python",
        )
        self.student = Student.objects.create(
            student_crm_id="field_student_1",
            student_name="Иванов Иван",
            branch=self.branch,
            group=self.group,
        )
        self.StudentSerializer = StudentSerializer
        self.ParentReview = ParentReview

    def test_is_review_exist_false_no_reviews(self):
        """Без отзывов — is_review_exist = False."""
        data = self.StudentSerializer(self.student).data
        self.assertFalse(data["is_review_exist"])

    def test_is_review_exist_true_recent_review(self):
        """Отзыв свежее 60 дней — is_review_exist = True."""
        self.ParentReview.objects.create(
            student=self.student, content="Отличная школа!"
        )
        data = self.StudentSerializer(self.student).data
        self.assertTrue(data["is_review_exist"])

    def test_is_review_exist_false_old_review(self):
        """Отзыв старше 60 дней — is_review_exist = False."""
        from datetime import timedelta
        from django.utils import timezone

        review = self.ParentReview.objects.create(
            student=self.student, content="Старый отзыв"
        )
        # Принудительно сдвигаем дату создания в прошлое
        old_date = timezone.now() - timedelta(days=61)
        self.ParentReview.objects.filter(pk=review.pk).update(created_at=old_date)
        # Обновляем объект из БД
        self.student.refresh_from_db()
        data = self.StudentSerializer(self.student).data
        self.assertFalse(data["is_review_exist"])

    def test_group_name_returns_group_name(self):
        """group_name возвращает название группы."""
        data = self.StudentSerializer(self.student).data
        self.assertEqual(data["group_name"], "Алгоритмы Python")

    def test_group_name_none_when_no_group(self):
        """group_name = None, когда студент не привязан к группе."""
        from core.models import Student

        student_no_group = Student.objects.create(
            student_crm_id="field_student_no_group",
            student_name="Петров Пётр",
            branch=self.branch,
            group=None,
        )
        data = self.StudentSerializer(student_no_group).data
        self.assertIsNone(data["group_name"])


class LessonAndSeniorTutorTestCase(TestCase):
    """Тесты поля lesson_number в Lesson и автоматического доступа старшего тьютора ко всем модулям."""

    def setUp(self):
        from core.models import Category, Subcategory, Module, Lesson, TutorModule
        from core.serializers import ModuleSerializer, LessonSerializer

        self.branch = Branch.objects.create(name="Test Branch", branch_crm_id=300)
        self.category = Category.objects.create(name="Программирование")
        self.subcategory = Subcategory.objects.create(name="Python", category=self.category)
        self.module = Module.objects.create(name="Основы Python", subcategory=self.subcategory)
        
        self.lesson1 = Lesson.objects.create(module=self.module, lesson_number=1)
        self.lesson2 = Lesson.objects.create(module=self.module, lesson_number=2)

        self.regular_tutor = TutorProfile.objects.create(
            tutor_name="Обычный Тьютор",
            phone_number="375291234567",
            branch=self.branch,
            is_senior=False,
        )
        self.senior_tutor = TutorProfile.objects.create(
            tutor_name="Старший Тьютор",
            phone_number="375297654321",
            branch=self.branch,
            is_senior=True,
        )
        self.client = APIClient()

    def test_lesson_serializer_includes_lesson_number(self):
        from core.serializers import LessonSerializer

        data = LessonSerializer(self.lesson1).data
        self.assertIn("lesson_number", data)
        self.assertEqual(data["lesson_number"], 1)

    def test_senior_tutor_sees_all_modules_and_lessons_without_tutor_module(self):
        """Старший тьютор видит все модули и уроки без записи TutorModule."""
        self._authenticate("375297654321")
        response = self.client.get("/api/modules/tutor/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        modules = response.data
        self.assertEqual(len(modules), 1)
        module_data = modules[0]
        self.assertTrue(module_data["is_accessible"])
        self.assertEqual(len(module_data["lessons"]), 2)
        self.assertEqual(module_data["lessons"][0]["lesson_number"], 1)
        self.assertEqual(module_data["lessons"][1]["lesson_number"], 2)

    def _token_for(self, phone_number):
        token_data = CustomTokenObtainPairSerializer().validate({"phone_number": phone_number})
        return token_data["access"]

    def _authenticate(self, phone_number):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self._token_for(phone_number)}")

    def _grant_access(self, tutor, module, days=1):
        from core.models import TutorModule

        return TutorModule.objects.create(
            tutor=tutor, module=module, expires_at=timezone.now() + timedelta(days=days)
        )

    def test_modules_list_has_no_lessons(self):
        """GET /modules/ отдаёт все активные модули и НЕ содержит уроков."""
        from core.models import Module

        Module.objects.create(name="Второй модуль", subcategory=self.subcategory)

        self._authenticate("375291234567")
        response = self.client.get("/api/modules/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)
        for module_data in response.data:
            self.assertNotIn("lessons", module_data)
        self.assertFalse(response.data[0]["is_accessible"])

    def test_module_detail_available_without_access(self):
        """GET /modules/<id>/ доступен тьютору без TutorModule (уроки при этом пустые)."""
        self._authenticate("375291234567")
        response = self.client.get(f"/api/modules/{self.module.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["id"], self.module.id)
        self.assertFalse(response.data["is_accessible"])
        self.assertEqual(response.data["lessons"], [])

    def test_module_detail_includes_lessons_when_accessible(self):
        """GET /modules/<id>/ отдаёт уроки, если доступ есть."""
        self._grant_access(self.regular_tutor, self.module)

        self._authenticate("375291234567")
        response = self.client.get(f"/api/modules/{self.module.id}/")
        self.assertTrue(response.data["is_accessible"])
        self.assertEqual(len(response.data["lessons"]), 2)

    def test_my_modules_regular_tutor_returns_only_accessible(self):
        """GET /modules/tutor/ — обычный тьютор получает только свои доступные модули."""
        from core.models import Module

        Module.objects.create(name="Недоступный модуль", subcategory=self.subcategory)
        self._grant_access(self.regular_tutor, self.module)

        self._authenticate("375291234567")
        response = self.client.get("/api/modules/tutor/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["id"], self.module.id)
        self.assertTrue(response.data[0]["is_accessible"])
        self.assertEqual(len(response.data[0]["lessons"]), 2)

    def test_my_modules_without_access_returns_empty_list(self):
        """GET /modules/tutor/ без доступов — пустой список вместо сообщения."""
        self._authenticate("375291234567")
        response = self.client.get("/api/modules/tutor/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, [])

    def test_public_module_accessible_without_tutor_module(self):
        """Модуль с is_public=True доступен обычному тьютору без TutorModule."""
        self.module.is_public = True
        self.module.save()

        self._authenticate("375291234567")
        response = self.client.get(f"/api/modules/{self.module.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["is_accessible"])
        self.assertEqual(len(response.data["lessons"]), 2)

    def test_public_module_appears_in_my_modules_for_regular_tutor(self):
        """GET /modules/tutor/ включает публичные модули для обычного тьютора без выданного доступа."""
        self.module.is_public = True
        self.module.save()

        self._authenticate("375291234567")
        response = self.client.get("/api/modules/tutor/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["id"], self.module.id)
        self.assertTrue(response.data[0]["is_accessible"])
        self.assertEqual(len(response.data[0]["lessons"]), 2)

    def test_non_public_module_not_accessible_without_tutor_module(self):
        """Модуль без is_public по-прежнему недоступен обычному тьютору без TutorModule."""
        from core.models import Module

        Module.objects.create(name="Приватный модуль", subcategory=self.subcategory, is_public=False)

        self._authenticate("375291234567")
        response = self.client.get("/api/modules/tutor/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, [])

    def test_my_modules_ignores_expired_access(self):
        """Просроченный TutorModule не считается доступом."""
        from core.models import TutorModule

        TutorModule.objects.create(
            tutor=self.regular_tutor,
            module=self.module,
            expires_at=timezone.now() - timedelta(days=1),
        )

        self._authenticate("375291234567")
        response = self.client.get("/api/modules/tutor/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, [])

    def test_my_modules_senior_tutor_returns_all(self):
        """GET /modules/tutor/ — старший тьютор получает все активные модули без TutorModule."""
        from core.models import Module

        Module.objects.create(name="Второй модуль", subcategory=self.subcategory)

        self._authenticate("375297654321")
        response = self.client.get("/api/modules/tutor/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)
        self.assertTrue(all(m["is_accessible"] for m in response.data))

    def _create_manager(self, phone="375293334455", is_senior=False):
        location = Location.objects.create(name="Локация", branch=self.branch)
        return Manager.objects.create(
            name="Менеджер", phone=phone, location=location, is_senior=is_senior
        )

    def test_my_modules_manager_returns_all_with_lessons(self):
        """GET /modules/tutor/ — менеджер имеет полный доступ ко всем модулям и урокам."""
        from core.models import Module

        self._create_manager()
        Module.objects.create(name="Второй модуль", subcategory=self.subcategory)

        self._authenticate("375293334455")
        response = self.client.get("/api/modules/tutor/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)
        self.assertTrue(all(m["is_accessible"] for m in response.data))

        with_lessons = next(m for m in response.data if m["id"] == self.module.id)
        self.assertEqual(len(with_lessons["lessons"]), 2)

    def test_manager_is_accessible_true_in_module_detail(self):
        """Менеджер видит is_accessible=true и уроки в /modules/<id>/."""
        self._create_manager()

        self._authenticate("375293334455")
        response = self.client.get(f"/api/modules/{self.module.id}/")
        self.assertTrue(response.data["is_accessible"])
        self.assertEqual(len(response.data["lessons"]), 2)

    def test_category_detail_shows_all_modules(self):
        """В /categories/<id>/ модули не фильтруются по ролям."""
        self._authenticate("375291234567")
        response = self.client.get(f"/api/categories/{self.category.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        modules = response.data["subcategories"][0]["modules"]
        self.assertEqual(len(modules), 1)
        self.assertFalse(modules[0]["is_accessible"])

    def test_category_detail_gives_manager_full_access(self):
        """Менеджер видит уроки модулей в /categories/<id>/."""
        self._create_manager()

        self._authenticate("375293334455")
        response = self.client.get(f"/api/categories/{self.category.id}/")
        modules = response.data["subcategories"][0]["modules"]
        self.assertTrue(modules[0]["is_accessible"])
        self.assertEqual(len(modules[0]["lessons"]), 2)


class TokenRefreshTestCase(TestCase):
    """Обновление access-токена по refresh-токену для обеих ролей."""

    def setUp(self):
        self.branch = Branch.objects.create(name="Minsk Refresh", branch_crm_id=77)
        self.location = Location.objects.create(name="Center Refresh", branch=self.branch)
        self.manager = Manager.objects.create(
            name="Refresh Manager",
            phone="375291110001",
            location=self.location,
            is_senior=False,
        )
        self.tutor = TutorProfile.objects.create(
            tutor_name="Refresh Tutor",
            phone_number="375291110002",
            branch=self.branch,
            is_senior=False,
        )
        self.senior_tutor = TutorProfile.objects.create(
            tutor_name="Refresh Senior Tutor",
            phone_number="375291110003",
            branch=self.branch,
            is_senior=True,
        )
        self.client = APIClient()

    def _refresh_token_for(self, phone_number):
        response = self.client.post(
            "/api/auth/login/", {"phone_number": phone_number}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return response.data["refresh"]

    def _refresh(self, phone_number):
        return self.client.post(
            "/api/auth/token/refresh/",
            {"refresh": self._refresh_token_for(phone_number)},
            format="json",
        )

    def test_refresh_regular_tutor(self):
        """Обычный тьютор обновляет токен и получает свои клеймы."""
        response = self._refresh("375291110002")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        access = AccessToken(response.data["access"])
        self.assertEqual(access["role"], "tutor")
        self.assertEqual(access["user_id"], self.tutor.id)
        self.assertFalse(access["is_senior"])
        self.assertEqual(access["branch_id"], self.branch.id)

    def test_refresh_senior_tutor(self):
        """Старший тьютор обновляет токен."""
        response = self._refresh("375291110003")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(AccessToken(response.data["access"])["is_senior"])

    def test_refresh_manager(self):
        """Менеджер обновляет токен и получает клеймы своей локации."""
        response = self._refresh("375291110001")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        access = AccessToken(response.data["access"])
        self.assertEqual(access["role"], "manager")
        self.assertEqual(access["user_id"], self.manager.id)
        self.assertEqual(access["location_id"], self.location.id)

    def test_refreshed_access_token_authenticates(self):
        """Полученным access-токеном можно ходить в защищённые эндпоинты."""
        response = self._refresh("375291110002")
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.data['access']}")
        profile = self.client.get("/api/profile/detail/")
        self.assertEqual(profile.status_code, status.HTTP_200_OK)

    def test_refresh_rejected_for_deactivated_tutor(self):
        """Тьютор, деактивированный после логина, не может обновить токен."""
        refresh = self._refresh_token_for("375291110002")
        self.tutor.is_active = False
        self.tutor.save()

        response = self.client.post(
            "/api/auth/token/refresh/", {"refresh": refresh}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_refresh_rejected_for_deleted_user(self):
        """Удалённый пользователь не может обновить токен."""
        refresh = self._refresh_token_for("375291110002")
        self.tutor.delete()

        response = self.client.post(
            "/api/auth/token/refresh/", {"refresh": refresh}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_refresh_claims_reflect_current_db_state(self):
        """Клеймы в новом access-токене берутся из БД, а не из старого refresh."""
        refresh = self._refresh_token_for("375291110002")
        self.tutor.is_senior = True
        self.tutor.save()

        response = self.client.post(
            "/api/auth/token/refresh/", {"refresh": refresh}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(AccessToken(response.data["access"])["is_senior"])


class EmployeeTestCase(TestCase):
    def setUp(self):
        self.branch = Branch.objects.create(name="Минск", branch_crm_id=1)
        self.location = Location.objects.create(name="Аэродромная", branch=self.branch)
        self.tutor = TutorProfile.objects.create(
            tutor_name="Тестовый Тьютор",
            phone_number="375299990001",
            branch=self.branch,
            is_senior=False,
        )
        self.employee1 = Employee.objects.create(
            full_name="Иванов Иван Иванович",
            category=Employee.Category.MANAGEMENT,
            position="Директор",
            branch=self.branch,
            location=self.location,
            telegram_url="https://t.me/ivanov",
        )
        self.employee2 = Employee.objects.create(
            full_name="Петров Петр Петрович",
            category=Employee.Category.TECHNICAL,
            position="Ведущий разработчик",
            branch=self.branch,
            location=None,
            telegram_url="https://t.me/petrov",
        )
        self.client = APIClient()

    def _auth(self):
        s = CustomTokenObtainPairSerializer()
        access = s.get_token(self.tutor).access_token
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")

    def test_employee_str(self):
        self.assertEqual(
            str(self.employee1),
            "Иванов Иван Иванович (Руководство)"
        )

    def test_employees_list_unauthenticated(self):
        response = self.client.get("/api/employees/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_employees_list_authenticated_no_pagination(self):
        self._auth()
        response = self.client.get("/api/employees/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Проверяем, что ответ — это прямой список без пагинации (не словарь с 'results')
        self.assertIsInstance(response.data, list)
        self.assertEqual(len(response.data), 2)
        names = [item["full_name"] for item in response.data]
        self.assertIn("Иванов Иван Иванович", names)
        self.assertIn("Петров Петр Петрович", names)
        # Проверяем поля
        first = next(item for item in response.data if item["id"] == self.employee1.id)
        self.assertEqual(first["category_display"], "Руководство")
        self.assertEqual(first["branch"], self.branch.id)
        self.assertEqual(first["branch_name"], "Минск")
        self.assertEqual(first["location"], self.location.id)
        self.assertEqual(first["location_name"], "Аэродромная")
        self.assertEqual(first["telegram_url"], "https://t.me/ivanov")
        self.assertIsNone(first["photo_url"])

    def test_employee_retrieve(self):
        self._auth()
        response = self.client.get(f"/api/employees/{self.employee1.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["full_name"], "Иванов Иван Иванович")
        self.assertEqual(response.data["position"], "Директор")
        self.assertEqual(response.data["branch_name"], "Минск")
        self.assertEqual(response.data["location_name"], "Аэродромная")

    def test_employee_mutations_not_allowed(self):
        self._auth()
        post_res = self.client.post("/api/employees/", {"full_name": "Новый"})
        self.assertEqual(post_res.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        put_res = self.client.put(f"/api/employees/{self.employee1.id}/", {"full_name": "Измененный"})
        self.assertEqual(put_res.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        del_res = self.client.delete(f"/api/employees/{self.employee1.id}/")
        self.assertEqual(del_res.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_employee_with_photo(self):
        self._auth()
        photo = SimpleUploadedFile("avatar.jpg", b"dummy_content", content_type="image/jpeg")
        emp = Employee.objects.create(
            full_name="Сидоров Сидор",
            category=Employee.Category.MARKETING,
            position="Маркетолог",
            branch=self.branch,
            photo=photo,
        )
        response = self.client.get(f"/api/employees/{emp.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        photo_url = response.data["photo_url"]
        # photo_url — постоянная ссылка на эндпоинт фотографии, без срока жизни
        # и без подписи, поэтому её можно кэшировать и подставлять в <img src>.
        self.assertIsNotNone(photo_url)
        self.assertTrue(photo_url.endswith(f"/api/employees/{emp.id}/photo/"), photo_url)
        self.assertNotIn("X-Amz-", photo_url)

        # По ссылке действительно отдаётся файл
        photo_response = self.client.get(f"/api/employees/{emp.id}/photo/")
        self.assertEqual(photo_response.status_code, status.HTTP_200_OK)
        self.assertEqual(b"".join(photo_response.streaming_content), b"dummy_content")

        # Очистка
        emp.delete()

    def test_employee_photo_available_without_authorization(self):
        """Ссылка на фото не требует токена — её открывает браузер напрямую."""
        photo = SimpleUploadedFile("avatar2.jpg", b"dummy_content_2", content_type="image/jpeg")
        emp = Employee.objects.create(
            full_name="Петров Пётр",
            category=Employee.Category.TECHNICAL,
            position="Инженер",
            branch=self.branch,
            photo=photo,
        )
        anon = APIClient()
        response = anon.get(f"/api/employees/{emp.id}/photo/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(b"".join(response.streaming_content), b"dummy_content_2")

        emp.delete()

    def test_employee_photo_missing_returns_404(self):
        self._auth()
        response = self.client.get(f"/api/employees/{self.employee2.id}/photo/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_employee_without_photo_has_no_photo_url(self):
        self._auth()
        response = self.client.get(f"/api/employees/{self.employee2.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(response.data["photo_url"])


class ResumeScopeTestCase(TestCase):
    """
    Резюме можно писать только доступному студенту.

    Раньше student_crm_id не проверялся на область видимости: любой
    авторизованный тьютор мог создать резюме студенту чужой группы и чужого
    филиала и заодно выставить ему is_added=True.
    """

    def setUp(self):
        self.branch1 = Branch.objects.create(name="Минск", branch_crm_id=1)
        self.branch2 = Branch.objects.create(name="Гомель", branch_crm_id=2)
        self.location1 = Location.objects.create(name="Центр", branch=self.branch1)

        self.tutor1 = TutorProfile.objects.create(
            tutor_name="Тьютор 1", phone_number="375291111111", branch=self.branch1
        )
        self.tutor2 = TutorProfile.objects.create(
            tutor_name="Тьютор 2", phone_number="375292222222", branch=self.branch2
        )
        self.manager = Manager.objects.create(
            name="Менеджер", phone="375293333333", location=self.location1
        )
        self.senior = Manager.objects.create(
            name="Старший", phone="375294444444", location=self.location1, is_senior=True
        )

        self.group1 = Group.objects.create(
            crm_group_id="g1", branch=self.branch1, tutor=self.tutor1, name="Группа 1"
        )
        self.group2 = Group.objects.create(
            crm_group_id="g2", branch=self.branch2, tutor=self.tutor2, name="Группа 2"
        )
        self.own_student = Student.objects.create(
            student_crm_id="own", group=self.group1, student_name="Свой", branch=self.branch1
        )
        self.foreign_student = Student.objects.create(
            student_crm_id="foreign", group=self.group2, student_name="Чужой", branch=self.branch2
        )
        self.client = APIClient()

    def _auth(self, phone):
        token = CustomTokenObtainPairSerializer().validate({"phone_number": phone})["access"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    def test_tutor_can_create_resume_for_own_student(self):
        self._auth("375291111111")
        response = self.client.post(
            "/api/resumes/", {"student_crm_id": "own", "content": "Текст"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.own_student.refresh_from_db()
        self.assertTrue(self.own_student.is_added)

    def test_tutor_cannot_create_resume_for_foreign_student(self):
        self._auth("375291111111")
        response = self.client.post(
            "/api/resumes/", {"student_crm_id": "foreign", "content": "Текст"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(Resume.objects.filter(student=self.foreign_student).count(), 0)
        self.foreign_student.refresh_from_db()
        self.assertFalse(self.foreign_student.is_added)

    def test_manager_cannot_create_resume_outside_branch(self):
        self._auth("375293333333")
        response = self.client.post(
            "/api/resumes/", {"student_crm_id": "foreign", "content": "Текст"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_senior_can_create_resume_for_any_student(self):
        self._auth("375294444444")
        response = self.client.post(
            "/api/resumes/", {"student_crm_id": "foreign", "content": "Текст"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_unknown_and_foreign_student_give_same_error(self):
        """Ответ не должен подсказывать, существует ли student_crm_id."""
        self._auth("375291111111")
        foreign = self.client.post(
            "/api/resumes/", {"student_crm_id": "foreign", "content": "x"}, format="json"
        )
        unknown = self.client.post(
            "/api/resumes/", {"student_crm_id": "no-such-id", "content": "x"}, format="json"
        )
        self.assertEqual(foreign.status_code, unknown.status_code)
        self.assertEqual(foreign.data["student_crm_id"], unknown.data["student_crm_id"])

    def test_update_keeps_student_and_does_not_require_crm_id(self):
        resume = Resume.objects.create(student=self.own_student, content="Старый")
        self._auth("375291111111")
        response = self.client.put(
            f"/api/resumes/{resume.id}/", {"content": "Новый"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        resume.refresh_from_db()
        self.assertEqual(resume.content, "Новый")
        self.assertEqual(resume.student_id, self.own_student.id)

    def test_resume_requires_authentication(self):
        response = self.client.post(
            "/api/resumes/", {"student_crm_id": "own", "content": "x"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class GroupCountersTestCase(TestCase):
    """Счётчики группы должны совпадать с полем is_verified у студентов."""

    def setUp(self):
        self.branch = Branch.objects.create(name="Минск", branch_crm_id=1)
        self.tutor = TutorProfile.objects.create(
            tutor_name="Тьютор", phone_number="375291111111", branch=self.branch
        )
        self.group = Group.objects.create(
            crm_group_id="g1", branch=self.branch, tutor=self.tutor, name="Группа"
        )
        self.client = APIClient()
        token = CustomTokenObtainPairSerializer().validate(
            {"phone_number": "375291111111"}
        )["access"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    def _group_row(self):
        response = self.client.get("/api/groups/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return response.data["results"][0]

    def test_student_marked_added_without_resumes_is_not_verified(self):
        Student.objects.create(
            student_crm_id="s1", group=self.group, student_name="Студент",
            branch=self.branch, is_added=True,
        )
        row = self._group_row()
        self.assertEqual(row["total_students"], 1)
        self.assertEqual(row["resumes_written_count"], 1)
        self.assertEqual(row["resumes_verified_count"], 0)

    def test_verified_counter_matches_student_flag(self):
        verified = Student.objects.create(
            student_crm_id="s1", group=self.group, student_name="Проверенный",
            branch=self.branch, is_added=True,
        )
        Resume.objects.create(student=verified, content="a", is_verified=True)
        Resume.objects.create(student=verified, content="b", is_verified=True)

        partial = Student.objects.create(
            student_crm_id="s2", group=self.group, student_name="Частично",
            branch=self.branch, is_added=True,
        )
        Resume.objects.create(student=partial, content="a", is_verified=True)
        Resume.objects.create(student=partial, content="b", is_verified=False)

        row = self._group_row()
        self.assertEqual(row["total_students"], 2)
        self.assertEqual(row["resumes_written_count"], 2)
        self.assertEqual(row["resumes_verified_count"], 1)

        clients = self.client.get(f"/api/groups/{self.group.id}/clients/")
        flags = {item["student_crm_id"]: item["is_verified"] for item in clients.data}
        self.assertEqual(flags, {"s1": True, "s2": False})


class StudentQueryCountTestCase(TestCase):
    """Список студентов не должен делать по запросу на каждого студента."""

    def setUp(self):
        self.branch = Branch.objects.create(name="Минск", branch_crm_id=1)
        self.tutor = TutorProfile.objects.create(
            tutor_name="Тьютор", phone_number="375291111111", branch=self.branch
        )
        self.group = Group.objects.create(
            crm_group_id="g1", branch=self.branch, tutor=self.tutor, name="Группа"
        )
        for i in range(10):
            student = Student.objects.create(
                student_crm_id=f"s{i}", group=self.group,
                student_name=f"Студент {i}", branch=self.branch, is_added=True,
            )
            Resume.objects.create(student=student, content="x", is_verified=i % 2 == 0)
            ParentReview.objects.create(student=student, content="отзыв")

        self.client = APIClient()
        token = CustomTokenObtainPairSerializer().validate(
            {"phone_number": "375291111111"}
        )["access"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    def test_student_list_query_count_does_not_grow_with_rows(self):
        with self.assertNumQueries(3):
            response = self.client.get("/api/clients/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 10)

    def test_student_list_stays_ordered_for_pagination(self):
        """Агрегаты не должны сбрасывать сортировку — иначе страницы поедут."""
        from core.models import Student as StudentModel
        from core.serializers import annotate_student_flags

        self.assertTrue(annotate_student_flags(StudentModel.objects.all()).ordered)

        first = self.client.get("/api/clients/?size=5").data["results"]
        second = self.client.get("/api/clients/?size=5&page=2").data["results"]
        names = [item["student_name"] for item in first + second]
        self.assertEqual(names, sorted(names))
        self.assertEqual(len(set(names)), 10)

    def test_annotated_flags_match_relations(self):
        response = self.client.get("/api/clients/")
        by_id = {item["student_crm_id"]: item for item in response.data["results"]}
        self.assertTrue(by_id["s0"]["is_verified"])
        self.assertFalse(by_id["s1"]["is_verified"])
        self.assertTrue(by_id["s0"]["is_review_exist"])

    def test_stale_review_does_not_count(self):
        student = Student.objects.create(
            student_crm_id="old", group=self.group,
            student_name="Со старым отзывом", branch=self.branch,
        )
        review = ParentReview.objects.create(student=student, content="давний")
        ParentReview.objects.filter(pk=review.pk).update(
            created_at=timezone.now() - timedelta(days=61)
        )
        response = self.client.get("/api/clients/")
        by_id = {item["student_crm_id"]: item for item in response.data["results"]}
        self.assertFalse(by_id["old"]["is_review_exist"])


class ModuleAccessQueryCountTestCase(TestCase):
    """Проверка доступа к модулям — один запрос на всю выдачу, а не на модуль."""

    def setUp(self):
        from core.models import Category, Subcategory, Module, TutorModule

        self.branch = Branch.objects.create(name="Минск", branch_crm_id=1)
        self.tutor = TutorProfile.objects.create(
            tutor_name="Тьютор", phone_number="375291111111", branch=self.branch
        )
        self.senior = TutorProfile.objects.create(
            tutor_name="Старший", phone_number="375292222222",
            branch=self.branch, is_senior=True,
        )
        category = Category.objects.create(name="Категория")
        subcategory = Subcategory.objects.create(name="Подкатегория", category=category)
        self.modules = [
            Module.objects.create(name=f"Модуль {i}", subcategory=subcategory)
            for i in range(6)
        ]
        # Доступ только к первым двум модулям
        for module in self.modules[:2]:
            TutorModule.objects.create(
                tutor=self.tutor, module=module,
                expires_at=timezone.now() + timedelta(days=3),
            )
        # Просроченный доступ к третьему — не должен учитываться
        TutorModule.objects.create(
            tutor=self.tutor, module=self.modules[2],
            expires_at=timezone.now() - timedelta(days=1),
        )
        self.client = APIClient()

    def _auth(self, phone):
        token = CustomTokenObtainPairSerializer().validate({"phone_number": phone})["access"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    def test_module_list_accessibility_flags(self):
        self._auth("375291111111")
        response = self.client.get("/api/modules/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        flags = {item["name"]: item["is_accessible"] for item in response.data}
        self.assertTrue(flags["Модуль 0"])
        self.assertTrue(flags["Модуль 1"])
        self.assertFalse(flags["Модуль 2"])
        self.assertFalse(flags["Модуль 5"])

    def test_module_list_query_count_does_not_grow_with_modules(self):
        """Число запросов не должно зависеть от количества модулей."""
        from django.test.utils import CaptureQueriesContext
        from django.db import connection
        from core.models import Module

        self._auth("375291111111")

        with CaptureQueriesContext(connection) as few:
            self.client.get("/api/modules/")

        subcategory = self.modules[0].subcategory
        for i in range(20):
            Module.objects.create(name=f"Ещё модуль {i}", subcategory=subcategory)

        with CaptureQueriesContext(connection) as many:
            response = self.client.get("/api/modules/")

        self.assertEqual(len(response.data), 26)
        self.assertEqual(len(many), len(few))

    def test_senior_tutor_sees_all_modules_accessible(self):
        self._auth("375292222222")
        response = self.client.get("/api/modules/")
        self.assertTrue(all(item["is_accessible"] for item in response.data))


class LocationFilterTestCase(TestCase):
    """Нечисловой branch_id должен давать 400, а не 500."""

    def setUp(self):
        self.branch = Branch.objects.create(name="Минск", branch_crm_id=1)
        self.location = Location.objects.create(name="Центр", branch=self.branch)
        self.manager = Manager.objects.create(
            name="Менеджер", phone="375291111111", location=self.location
        )
        self.client = APIClient()
        token = CustomTokenObtainPairSerializer().validate(
            {"phone_number": "375291111111"}
        )["access"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    def test_invalid_branch_id_returns_400(self):
        response = self.client.get("/api/locations/?branch_id=abc")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_valid_branch_id_filters(self):
        response = self.client.get(f"/api/locations/?branch_id={self.branch.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)

    def test_unknown_branch_id_returns_empty(self):
        response = self.client.get("/api/locations/?branch_id=999999")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, [])


class ThrottlingTestCase(TestCase):
    """
    Вход беспарольный, а отправка отзыва вообще не требует авторизации,
    поэтому оба эндпоинта должны ограничивать частоту запросов.
    """

    def setUp(self):
        cache.clear()
        self.branch = Branch.objects.create(name="Минск", branch_crm_id=1)
        self.tutor = TutorProfile.objects.create(
            tutor_name="Тьютор", phone_number="375291111111", branch=self.branch
        )
        self.group = Group.objects.create(
            crm_group_id="g1", branch=self.branch, tutor=self.tutor, name="Группа"
        )
        self.student = Student.objects.create(
            student_crm_id="s1", group=self.group, student_name="Студент", branch=self.branch
        )
        self.client = APIClient()

    def tearDown(self):
        cache.clear()

    def test_login_attempts_are_throttled(self):
        statuses = [
            self.client.post(
                "/api/auth/login/", {"phone_number": f"37529000{i:04d}"}, format="json"
            ).status_code
            for i in range(15)
        ]
        self.assertIn(status.HTTP_429_TOO_MANY_REQUESTS, statuses)

    def test_successful_login_still_works_within_limit(self):
        response = self.client.post(
            "/api/auth/login/", {"phone_number": "375291111111"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("access", response.data)

    def test_public_review_creation_is_throttled(self):
        statuses = [
            self.client.post(
                "/api/reviews/", {"student_crm_id": "s1", "content": "отзыв"}, format="json"
            ).status_code
            for i in range(25)
        ]
        self.assertIn(status.HTTP_201_CREATED, statuses)
        self.assertIn(status.HTTP_429_TOO_MANY_REQUESTS, statuses)

    def test_review_content_length_is_limited(self):
        response = self.client.post(
            "/api/reviews/",
            {"student_crm_id": "s1", "content": "я" * 5001},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class PhoneNormalizationTestCase(TestCase):
    """
    Телефон хранится только цифрами. Иначе менеджер, заведённый в админке
    как '+375 (29) 123-45-67', не смог бы войти по своему номеру.
    """

    def setUp(self):
        self.branch = Branch.objects.create(name="Минск", branch_crm_id=1)
        self.location = Location.objects.create(name="Центр", branch=self.branch)
        self.client = APIClient()

    def test_normalize_phone_helper(self):
        self.assertEqual(normalize_phone("+375 (29) 123-45-67"), "375291234567")
        self.assertEqual(normalize_phone("375291234567"), "375291234567")
        self.assertIsNone(normalize_phone(None))
        # Без цифр значение не затирается
        self.assertEqual(normalize_phone("нет цифр"), "нет цифр")

    def test_manager_phone_normalized_on_save(self):
        manager = Manager.objects.create(
            name="Менеджер", phone="+375 (29) 123-45-67", location=self.location
        )
        manager.refresh_from_db()
        self.assertEqual(manager.phone, "375291234567")

    def test_tutor_phone_normalized_on_save(self):
        tutor = TutorProfile.objects.create(
            tutor_name="Тьютор", phone_number="+375 33 765-43-21", branch=self.branch
        )
        tutor.refresh_from_db()
        self.assertEqual(tutor.phone_number, "375337654321")

    def test_login_with_formatted_phone(self):
        Manager.objects.create(
            name="Менеджер", phone="+375 (29) 123-45-67", location=self.location
        )
        cache.clear()
        response = self.client.post(
            "/api/auth/login/", {"phone_number": "+375 (29) 123-45-67"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        cache.clear()


class DefaultPermissionTestCase(TestCase):
    """Эндпоинты закрыты по умолчанию — кроме сознательно публичных."""

    def setUp(self):
        cache.clear()
        self.branch = Branch.objects.create(name="Минск", branch_crm_id=1)
        self.tutor = TutorProfile.objects.create(
            tutor_name="Тьютор", phone_number="375291111111", branch=self.branch
        )
        self.group = Group.objects.create(
            crm_group_id="g1", branch=self.branch, tutor=self.tutor, name="Группа"
        )
        self.student = Student.objects.create(
            student_crm_id="s1", group=self.group, student_name="Студент", branch=self.branch
        )
        self.client = APIClient()

    def tearDown(self):
        cache.clear()

    def test_data_endpoints_require_token(self):
        for url in (
            "/api/groups/",
            "/api/clients/",
            "/api/resumes/",
            "/api/news/",
            "/api/categories/",
            "/api/modules/",
            "/api/branches/",
            "/api/locations/",
            "/api/employees/",
            "/api/profile/detail/",
            f"/api/reviews/{self.student.student_crm_id}/",
        ):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_public_endpoints_stay_public(self):
        login = self.client.post(
            "/api/auth/login/", {"phone_number": "375291111111"}, format="json"
        )
        self.assertEqual(login.status_code, status.HTTP_200_OK)

        review = self.client.post(
            "/api/reviews/", {"student_crm_id": "s1", "content": "отзыв"}, format="json"
        )
        self.assertEqual(review.status_code, status.HTTP_201_CREATED)

        schema = self.client.get("/api/schema/")
        self.assertEqual(schema.status_code, status.HTTP_200_OK)
