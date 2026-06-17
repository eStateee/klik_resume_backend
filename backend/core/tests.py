from django.test import TestCase
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
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["name"], "Test Group")

    def test_unauthorized_access(self):
        # Without token, should return 401
        self.client.credentials()
        response = self.client.get("/api/groups/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
