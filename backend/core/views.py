from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework import viewsets, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from django.db.models import Count, Q
from drf_spectacular.utils import extend_schema

from .serializers import CustomTokenObtainPairSerializer
from .models import Group, Student, Resume, ParentReview, News, Category, Module, Manager, TutorProfile
from .serializers import (
    GroupSerializer, StudentSerializer, ResumeSerializer,
    ParentReviewSerializer, NewsSerializer, CategorySerializer,
    ModuleSerializer
)
from .permissions import IsTutor, IsManager, IsSeniorTutorOrManager
from .pagination import StandardResultsSetPagination


class PasswordlessLoginView(TokenObtainPairView):
    serializer_class = CustomTokenObtainPairSerializer


class ProfileDetailView(APIView):
    """
    Информация о текущем пользователе (зависит от роли — Manager или TutorProfile).
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        
        if isinstance(user, Manager):
            return Response({
                "id": user.id,
                "role": "manager",
                "name": user.name,
                "phone": user.phone,
                "is_senior": user.is_senior,
                "telegram": user.telegram,
                "location_id": user.location_id,
                "branch_id": user.location.branch_id if user.location else None
            })
        elif isinstance(user, TutorProfile):
            return Response({
                "id": user.id,
                "role": "tutor",
                "tutor_name": user.tutor_name,
                "phone_number": user.phone_number,
                "is_senior": user.is_senior,
                "branch_id": user.branch_id,
                "avatar_url": user.avatar_url,
                "dob": user.dob,
                "note": user.note
            })
        
        return Response({"detail": "Unknown profile type"}, status=status.HTTP_400_BAD_REQUEST)


class GroupViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = GroupSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        auth = self.request.auth
        if not auth:
            return Group.objects.none()
            
        role = auth.get('role')
        user_id = auth.get('user_id')
        branch_id = auth.get('branch_id')
        is_senior = auth.get('is_senior')
        
        qs = Group.objects.none()
        
        if is_senior:
            qs = Group.objects.all()
        elif role == 'tutor':
            qs = Group.objects.filter(tutor_id=user_id)
        elif role == 'manager':
            qs = Group.objects.filter(branch_id=branch_id)
        
        return qs.annotate(
            total_students=Count('students', distinct=True),
            resumes_written_count=Count('students', filter=Q(students__is_added=True), distinct=True),
            resumes_verified_count=Count('students', filter=Q(students__resumes__is_verified=True), distinct=True)
        )

    @extend_schema(
        summary="Получить список групп",
        description=(
            "Возвращает список групп с поддержкой пагинации.\n\n"
            "**Правила доступа:**\n"
            "- **Старший тьютор / Старший менеджер:** видит ВСЕ группы.\n"
            "- **Менеджер:** видит группы только своего филиала.\n"
            "- **Тьютор:** видит только свои группы."
        )
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @action(detail=True, methods=['get'])
    def clients(self, request, pk=None):
        group = self.get_object()
        students = group.students.all()
        serializer = StudentSerializer(students, many=True)
        return Response(serializer.data)


class StudentViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = StudentSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        auth = self.request.auth
        if not auth:
            return Student.objects.none()
            
        role = auth.get('role')
        user_id = auth.get('user_id')
        branch_id = auth.get('branch_id')
        is_senior = auth.get('is_senior')
        
        if is_senior:
            return Student.objects.all()
        elif role == 'tutor':
            return Student.objects.filter(group__tutor_id=user_id)
        elif role == 'manager':
            return Student.objects.filter(branch_id=branch_id)
            
        return Student.objects.none()

    @extend_schema(
        summary="Получить список студентов",
        description=(
            "Возвращает список студентов с поддержкой пагинации.\n\n"
            "**Правила доступа:**\n"
            "- **Старший тьютор / Старший менеджер:** видит ВСЕХ студентов.\n"
            "- **Менеджер:** видит студентов только своего филиала.\n"
            "- **Тьютор:** видит только студентов своих групп."
        )
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @action(detail=False, methods=['get'], permission_classes=[IsAuthenticated, IsSeniorTutorOrManager])
    def all(self, request):
        qs = self.get_queryset()
        serializer = self.get_serializer(qs, many=True)
        return Response(serializer.data)


class ResumeViewSet(viewsets.ModelViewSet):
    serializer_class = ResumeSerializer
    pagination_class = StandardResultsSetPagination

    def get_permissions(self):
        if self.action in ['destroy', 'verify']:
            return [IsAuthenticated(), IsSeniorTutorOrManager()]
        return [IsAuthenticated()]

    def get_queryset(self):
        auth = self.request.auth
        if not auth:
            return Resume.objects.none()
            
        role = auth.get('role')
        user_id = auth.get('user_id')
        branch_id = auth.get('branch_id')
        is_senior = auth.get('is_senior')
        
        if is_senior:
            return Resume.objects.all()
        elif role == 'tutor':
            return Resume.objects.filter(student__group__tutor_id=user_id)
        elif role == 'manager':
            return Resume.objects.filter(student__branch_id=branch_id)
            
        return Resume.objects.none()

    @extend_schema(
        summary="Получить список резюме",
        description=(
            "Возвращает список резюме с поддержкой пагинации.\n\n"
            "**Правила доступа:**\n"
            "- **Старший тьютор / Старший менеджер:** видит ВСЕ резюме.\n"
            "- **Менеджер:** видит резюме только студентов своего филиала.\n"
            "- **Тьютор:** видит резюме только студентов своих групп."
        )
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @action(detail=False, methods=['get'], url_path='client')
    def client(self, request):
        student_crm_id = request.query_params.get('student_crm_id')
        if not student_crm_id:
            return Response({"detail": "student_crm_id parameter is required"}, status=status.HTTP_400_BAD_REQUEST)
        qs = self.get_queryset().filter(student__student_crm_id=student_crm_id)
        serializer = self.get_serializer(qs, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def verify(self, request, pk=None):
        resume = self.get_object()
        resume.is_verified = True
        resume.save(update_fields=['is_verified'])
        return Response({"status": "verified"})


class ParentReviewViewSet(viewsets.ModelViewSet):
    serializer_class = ParentReviewSerializer
    pagination_class = StandardResultsSetPagination
    
    def get_permissions(self):
        if self.action == 'create':
            return []
        return [IsAuthenticated()]

    def get_queryset(self):
        qs = ParentReview.objects.none()
        auth = self.request.auth
        
        if auth:
            role = auth.get('role')
            user_id = auth.get('user_id')
            branch_id = auth.get('branch_id')
            is_senior = auth.get('is_senior')
            
            if is_senior:
                qs = ParentReview.objects.all()
            elif role == 'tutor':
                qs = ParentReview.objects.filter(student__group__tutor_id=user_id)
            elif role == 'manager':
                qs = ParentReview.objects.filter(student__branch_id=branch_id)
                
        student_crm_id = self.kwargs.get('student_crm_id')
        if student_crm_id:
            qs = qs.filter(student__student_crm_id=student_crm_id)
            
        return qs

    @extend_schema(
        summary="Получить список отзывов родителей",
        description=(
            "Возвращает список отзывов с поддержкой пагинации.\n\n"
            "**Правила доступа:**\n"
            "- **Старший тьютор / Старший менеджер:** видит ВСЕ отзывы.\n"
            "- **Менеджер:** видит отзывы только студентов своего филиала.\n"
            "- **Тьютор:** видит отзывы только студентов своих групп."
        )
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)


class NewsViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = News.objects.all()  # Ordering in Meta
    serializer_class = NewsSerializer
    permission_classes = [IsAuthenticated]


class CategoryViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Category.objects.filter(is_active=True)
    serializer_class = CategorySerializer
    permission_classes = [IsAuthenticated]


class ModuleViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Module.objects.filter(is_active=True)
    serializer_class = ModuleSerializer
    permission_classes = [IsAuthenticated]
