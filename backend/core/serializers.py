from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from .models import Manager, TutorProfile

class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Удаляем поля username и password, так как они нам не нужны
        self.fields.pop('username', None)
        self.fields.pop('password', None)
        from rest_framework import serializers
        self.fields['phone_number'] = serializers.CharField()

    def validate(self, attrs):
        phone_number = attrs.get("phone_number")
        
        # Очищаем телефон (оставляем только цифры)
        if phone_number:
            phone_number = ''.join(filter(str.isdigit, phone_number))
            
        from django.contrib.auth import authenticate
        user = authenticate(request=self.context.get('request'), phone_number=phone_number)

        if user is None:
            from rest_framework.exceptions import AuthenticationFailed
            raise AuthenticationFailed("Пользователь не найден")

        # Так как SimpleJWT ожидает модель с полем id, а наши модели имеют id
        refresh = self.get_token(user)

        return {
            'refresh': str(refresh),
            'access': str(refresh.access_token),
        }

    @classmethod
    def get_token(cls, user):
        from rest_framework_simplejwt.tokens import RefreshToken
        # Чтобы кастомные поля работали, нам нужно создать RefreshToken вручную 
        # и добавить клеймы, так как user не является стандартной моделью Django.
        token = RefreshToken()
        
        # Устанавливаем id и другие клеймы
        token['user_id'] = user.id

        if isinstance(user, Manager):
            token['role'] = 'manager'
            token['is_senior'] = user.is_senior
            token['branch_id'] = user.location.branch.id if user.location and user.location.branch else None
            token['location_id'] = user.location.id if user.location else None
        elif isinstance(user, TutorProfile):
            token['role'] = 'tutor'
            token['is_senior'] = user.is_senior
            token['branch_id'] = user.branch.id if user.branch else None

        return token
