from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework.exceptions import AuthenticationFailed
from .models import Manager, TutorProfile

class CustomJWTAuthentication(JWTAuthentication):
    def get_user(self, validated_token):
        """
        Attempts to find and return a user using the given validated token.
        Since we have a passwordless custom auth with Manager and TutorProfile
        models instead of the default User model, we use the role from the token
        to fetch the correct model instance.
        """
        try:
            user_id = validated_token['user_id']
        except KeyError:
            raise AuthenticationFailed("Token contained no recognizable user identification", code="token_not_valid")

        role = validated_token.get('role')

        if role == 'manager':
            try:
                user = Manager.objects.get(id=user_id)
            except Manager.DoesNotExist:
                raise AuthenticationFailed("Manager not found", code="user_not_found")
        elif role == 'tutor':
            try:
                user = TutorProfile.objects.get(id=user_id)
            except TutorProfile.DoesNotExist:
                raise AuthenticationFailed("Tutor not found", code="user_not_found")
        else:
            # Fallback to standard Django user model (useful for django superusers or admins using API)
            try:
                return super().get_user(validated_token)
            except Exception:
                raise AuthenticationFailed("Invalid role or user not found in token", code="user_not_found")

        return user

# Register OpenApiAuthenticationExtension for drf-spectacular documentation
try:
    from drf_spectacular.extensions import OpenApiAuthenticationExtension

    class CustomJWTAuthenticationScheme(OpenApiAuthenticationExtension):
        target_class = 'core.authentication.CustomJWTAuthentication'
        name = 'jwtAuth'

        def get_security_definition(self, auto_schema):
            return {
                'type': 'http',
                'scheme': 'bearer',
                'bearerFormat': 'JWT',
            }
except ImportError:
    pass

