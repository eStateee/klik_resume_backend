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
        # Поскольку у нас кастомная аутентификация без стандартной модели User,
        # get_user может быть сложно реализовать для сессий.
        # Но мы используем JWT, поэтому этот метод может и не понадобиться,
        # либо мы можем возвращать нужный объект в зависимости от типа.
        # В данном случае, мы полагаемся на JWT токены.
        pass
