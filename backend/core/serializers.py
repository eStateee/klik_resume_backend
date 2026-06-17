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

from rest_framework import serializers
from .models import Group, Student, Resume, ParentReview, News, Category, Subcategory, Module, Lesson, TutorModule
from django.utils import timezone
class GroupSerializer(serializers.ModelSerializer):
    class Meta:
        model = Group
        fields = ['id', 'crm_group_id', 'name', 'custom_aerodromnaya', 'branch', 'tutor']

class StudentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Student
        fields = ['id', 'student_crm_id', 'student_name', 'study_start_date', 'branch', 'group']

class ResumeSerializer(serializers.ModelSerializer):
    student_crm_id = serializers.CharField(write_only=True)
    student = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = Resume
        fields = ['id', 'student', 'student_crm_id', 'content', 'is_verified', 'created_at', 'updated_at']
        read_only_fields = ['is_verified', 'created_at', 'updated_at', 'student']

    def create(self, validated_data):
        student_crm_id = validated_data.pop('student_crm_id')
        from django.shortcuts import get_object_or_404
        from .models import Student
        student = get_object_or_404(Student, student_crm_id=student_crm_id)
        validated_data['student'] = student
        return super().create(validated_data)

class ParentReviewSerializer(serializers.ModelSerializer):
    student_crm_id = serializers.CharField(write_only=True)
    student = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = ParentReview
        fields = ['id', 'student', 'student_crm_id', 'content', 'created_at', 'updated_at']
        read_only_fields = ['created_at', 'updated_at', 'student']

    def create(self, validated_data):
        student_crm_id = validated_data.pop('student_crm_id')
        from django.shortcuts import get_object_or_404
        from .models import Student
        student = get_object_or_404(Student, student_crm_id=student_crm_id)
        validated_data['student'] = student
        return super().create(validated_data)

class NewsSerializer(serializers.ModelSerializer):
    class Meta:
        model = News
        fields = ['id', 'title', 'content', 'created_at']

class LessonSerializer(serializers.ModelSerializer):
    file_url = serializers.SerializerMethodField()
    archive_url = serializers.SerializerMethodField()

    class Meta:
        model = Lesson
        fields = ['id', 'file_url', 'archive_url']

    def _generate_presigned_url(self, file_field):
        if not file_field:
            return None
        try:
            import boto3
            from django.conf import settings
            s3_client = boto3.client('s3',
                endpoint_url=getattr(settings, 'AWS_S3_ENDPOINT_URL', None),
                aws_access_key_id=getattr(settings, 'AWS_ACCESS_KEY_ID', None),
                aws_secret_access_key=getattr(settings, 'AWS_SECRET_ACCESS_KEY', None),
                region_name=getattr(settings, 'AWS_S3_REGION_NAME', None)
            )
            url = s3_client.generate_presigned_url(
                'get_object',
                Params={'Bucket': getattr(settings, 'AWS_STORAGE_BUCKET_NAME', ''), 'Key': str(file_field)},
                ExpiresIn=900
            )
            return url
        except Exception:
            return getattr(file_field, 'url', None)

    def get_file_url(self, obj):
        return self._generate_presigned_url(obj.file)

    def get_archive_url(self, obj):
        return self._generate_presigned_url(obj.archive)

class ModuleSerializer(serializers.ModelSerializer):
    is_accessible = serializers.SerializerMethodField()
    lessons = serializers.SerializerMethodField()

    class Meta:
        model = Module
        fields = ['id', 'name', 'validity_period', 'is_active', 'is_accessible', 'lessons']

    def get_is_accessible(self, obj):
        request = self.context.get('request')
        if not request or not request.auth:
            return False
        
        user_id = request.auth.get('user_id')
        role = request.auth.get('role')

        if role == 'tutor':
            now = timezone.now()
            return TutorModule.objects.filter(
                tutor_id=user_id,
                module=obj,
                expires_at__gt=now
            ).exists()
        return False

    def get_lessons(self, obj):
        if self.get_is_accessible(obj):
            lessons = obj.lessons.all()
            return LessonSerializer(lessons, many=True, context=self.context).data
        return []

class SubcategorySerializer(serializers.ModelSerializer):
    modules = ModuleSerializer(many=True, read_only=True)

    class Meta:
        model = Subcategory
        fields = ['id', 'name', 'is_active', 'modules']

class CategorySerializer(serializers.ModelSerializer):
    subcategories = SubcategorySerializer(many=True, read_only=True)

    class Meta:
        model = Category
        fields = ['id', 'name', 'is_active', 'subcategories']
