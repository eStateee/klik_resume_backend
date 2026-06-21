import logging

from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.authentication import JWTAuthentication

from .models import Manager, TutorProfile

logger = logging.getLogger("core")


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

        role = validated_token.get("role")

        if role == "manager":
            try:
                return Manager.objects.get(id=user_id)
            except Manager.DoesNotExist:
                logger.error("CustomJWTAuthentication: Manager id=%s не найден", user_id)
                raise AuthenticationFailed(
                    "Менеджер не найден", code="user_not_found"
                )

        if role == "tutor":
            try:
                return TutorProfile.objects.get(id=user_id)
            except TutorProfile.DoesNotExist:
                logger.error("CustomJWTAuthentication: TutorProfile id=%s не найден", user_id)
                raise AuthenticationFailed(
                    "Тьютор не найден", code="user_not_found"
                )

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
