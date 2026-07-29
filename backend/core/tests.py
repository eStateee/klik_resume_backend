from unittest.mock import patch
from django.test import TestCase
from django.core.management import call_command
from django.contrib.auth import authenticate
from rest_framework.test import APIClient
from rest_framework import status
from core.models import Branch, Location, Manager, TutorProfile, Group
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
        token_serializer = CustomTokenObtainPairSerializer()
        token_data = token_serializer.validate({"phone_number": "375297654321"})
        access_token = token_data["access"]

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access_token}")
        response = self.client.get("/api/modules/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        modules = response.data.get("results") if isinstance(response.data, dict) else response.data
        self.assertEqual(len(modules), 1)
        module_data = modules[0]
        self.assertTrue(module_data["is_accessible"])
        self.assertEqual(len(module_data["lessons"]), 2)
        self.assertEqual(module_data["lessons"][0]["lesson_number"], 1)
        self.assertEqual(module_data["lessons"][1]["lesson_number"], 2)

    def test_regular_tutor_cannot_see_lessons_without_tutor_module(self):
        """Обычный тьютор не видит уроки без записи TutorModule."""
        token_serializer = CustomTokenObtainPairSerializer()
        token_data = token_serializer.validate({"phone_number": "375291234567"})
        access_token = token_data["access"]

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access_token}")
        response = self.client.get("/api/modules/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        modules = response.data.get("results") if isinstance(response.data, dict) else response.data
        self.assertEqual(len(modules), 1)
        module_data = modules[0]
        self.assertFalse(module_data["is_accessible"])
        self.assertEqual(len(module_data["lessons"]), 0)
