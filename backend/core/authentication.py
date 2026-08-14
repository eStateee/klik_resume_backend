import logging

from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.authentication import JWTAuthentication

from .models import Manager, TutorProfile

logger = logging.getLogger("core")


def resolve_user_by_role(role, user_id):
    """
    Находит пользователя по паре (role, user_id) из payload токена.

    Менеджеры и тьюторы хранятся в разных таблицах, поэтому стандартный поиск
    через User не подходит. Возвращает None, если роль не кастомная
    (например, суперпользователь Django Admin) — вызывающий код решает,
    что делать дальше.
    """
    if role == "manager":
        try:
            return Manager.objects.get(id=user_id)
        except Manager.DoesNotExist:
            logger.error("resolve_user_by_role: Manager id=%s не найден", user_id)
            raise AuthenticationFailed("Менеджер не найден", code="user_not_found")

    if role == "tutor":
        try:
            tutor = TutorProfile.objects.get(id=user_id)
        except TutorProfile.DoesNotExist:
            logger.error("resolve_user_by_role: TutorProfile id=%s не найден", user_id)
            raise AuthenticationFailed("Тьютор не найден", code="user_not_found")
        if not tutor.is_active:
            logger.warning("resolve_user_by_role: тьютор id=%s деактивирован", user_id)
            raise AuthenticationFailed(
                "Ваш аккаунт деактивирован", code="user_inactive"
            )
        return tutor

    return None


class CustomJWTAuthentication(JWTAuthentication):
    """
    Кастомный JWT-аутентификатор.
    Использует поле 'role' из payload токена для выборки нужной модели.
    """

    def get_user(self, validated_token):
        """
        Находит пользователя по user_id и role из токена.
        Менеджеры и тьюторы хранятся в разных таблицах,
        поэтому стандартный механизм поиска через User не подходит.
        """
        try:
            user_id = validated_token["user_id"]
        except KeyError:
            raise AuthenticationFailed(
                "Токен не содержит идентификатора пользователя",
                code="token_not_valid",
            )

        user = resolve_user_by_role(validated_token.get("role"), user_id)
        if user is not None:
            return user

        # Fallback для суперпользователей Django Admin (без кастомной роли)
        try:
            return super().get_user(validated_token)
        except AuthenticationFailed:
            raise
        except Exception as exc:
            logger.error(
                "CustomJWTAuthentication: ошибка при поиске пользователя без роли: %s", exc
            )
            raise AuthenticationFailed(
                "Невалидная роль или пользователь не найден", code="user_not_found"
            )


# Регистрация OpenApiAuthenticationExtension для drf-spectacular
try:
    from drf_spectacular.extensions import OpenApiAuthenticationExtension

    class CustomJWTAuthenticationScheme(OpenApiAuthenticationExtension):
        target_class = "core.authentication.CustomJWTAuthentication"
        name = "jwtAuth"

        def get_security_definition(self, auto_schema):
            return {
                "type": "http",
                "scheme": "bearer",
                "bearerFormat": "JWT",
            }

except ImportError:
    pass
