import logging

from django.contrib.auth.backends import BaseBackend

from .models import Manager, TutorProfile

logger = logging.getLogger("core")

# Префиксы для различения типов пользователей в get_user
_MANAGER_PREFIX = "m_"
_TUTOR_PREFIX = "t_"


def _encode_user_pk(prefix: str, pk: int) -> str:
    """Кодирует PK пользователя с префиксом типа."""
    return f"{prefix}{pk}"


def decode_user_pk(encoded_pk: str):
    """Декодирует PK и тип пользователя. Возвращает (model_class, pk) или (None, None)."""
    if encoded_pk.startswith(_MANAGER_PREFIX):
        return Manager, int(encoded_pk[len(_MANAGER_PREFIX):])
    if encoded_pk.startswith(_TUTOR_PREFIX):
        return TutorProfile, int(encoded_pk[len(_TUTOR_PREFIX):])
    return None, None


class PasswordlessAuthBackend(BaseBackend):
    """
    Кастомный бэкенд аутентификации без пароля.
    Принимает phone_number и ищет сначала Manager, затем TutorProfile.
    """

    def authenticate(self, request, phone_number=None, **kwargs):
        if not phone_number:
            return None

        # Сначала ищем менеджера
        try:
            return Manager.objects.get(phone=phone_number)
        except Manager.DoesNotExist:
            pass

        # Если не найден — ищем тьютора
        try:
            return TutorProfile.objects.get(phone_number=phone_number)
        except TutorProfile.DoesNotExist:
            return None

    def get_user(self, user_id):
        """
        Восстанавливает пользователя по закодированному user_id.
        user_id может быть строкой вида 'm_<pk>' или 't_<pk>' или просто int (legacy).
        """
        encoded = str(user_id)
        model_class, pk = decode_user_pk(encoded)

        if model_class is not None:
            try:
                return model_class.objects.get(pk=pk)
            except model_class.DoesNotExist:
                logger.error(
                    "get_user: %s с pk=%s не найден", model_class.__name__, pk
                )
                return None

        # Fallback для старых токенов без префикса (целочисленный user_id)
        # Порядок: сначала Manager, потом TutorProfile
        try:
            pk_int = int(encoded)
        except (ValueError, TypeError):
            logger.error("get_user: невалидный user_id=%s", encoded)
            return None

        try:
            return Manager.objects.get(pk=pk_int)
        except Manager.DoesNotExist:
            pass
        try:
            return TutorProfile.objects.get(pk=pk_int)
        except TutorProfile.DoesNotExist:
            logger.warning("get_user: пользователь с pk=%s не найден ни в одной модели", pk_int)
            return None
