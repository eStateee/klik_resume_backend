from django.contrib.auth.backends import BaseBackend
from .models import Manager, TutorProfile

class PasswordlessAuthBackend(BaseBackend):
    def authenticate(self, request, phone_number=None, **kwargs):
        if not phone_number:
            return None

        # Сначала ищем менеджера
        try:
            user = Manager.objects.get(phone=phone_number)
            return user
        except Manager.DoesNotExist:
            pass

        # Если не найден, ищем тьютора
        try:
            user = TutorProfile.objects.get(phone_number=phone_number)
            return user
        except TutorProfile.DoesNotExist:
            return None

    def get_user(self, user_id):
        try:
            return Manager.objects.get(pk=user_id)
        except Manager.DoesNotExist:
            pass
        try:
            return TutorProfile.objects.get(pk=user_id)
        except TutorProfile.DoesNotExist:
            return None

