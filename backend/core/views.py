from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework import viewsets, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import CustomTokenObtainPairSerializer
from .models import Group, Student, Resume, ParentReview, News, Category, Module, Manager, TutorProfile
from .serializers import (
    GroupSerializer, StudentSerializer, ResumeSerializer,
    ParentReviewSerializer, NewsSerializer, CategorySerializer,
    ModuleSerializer
)
from .permissions import IsTutor, IsManager, IsSeniorTutorOrManager


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

    def get_queryset(self):
        auth = self.request.auth
        if not auth:
            return Group.objects.none()
            
        role = auth.get('role')
        user_id = auth.get('user_id')
        branch_id = auth.get('branch_id')
        is_senior = auth.get('is_senior')
        
        if role == 'tutor':
            if is_senior:
                return Group.objects.filter(branch_id=branch_id)
            else:
                return Group.objects.filter(tutor_id=user_id)
        elif role == 'manager':
            # Менеджеры могут видеть группы в рамках своего филиала
            return Group.objects.filter(branch_id=branch_id)
        
        return Group.objects.none()

    @action(detail=True, methods=['get'])
    def clients(self, request, pk=None):
        group = self.get_object()
        students = group.students.all()
        serializer = StudentSerializer(students, many=True)
        return Response(serializer.data)


class StudentViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = StudentSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        auth = self.request.auth
        if not auth:
            return Student.objects.none()
            
        role = auth.get('role')
        user_id = auth.get('user_id')
        branch_id = auth.get('branch_id')
        is_senior = auth.get('is_senior')
        
        if role == 'tutor':
            if is_senior:
                return Student.objects.filter(branch_id=branch_id)
            else:
                return Student.objects.filter(group__tutor_id=user_id)
        elif role == 'manager':
            return Student.objects.filter(branch_id=branch_id)
            
        return Student.objects.none()

    @action(detail=False, methods=['get'], permission_classes=[IsAuthenticated, IsSeniorTutorOrManager])
    def all(self, request):
        qs = self.get_queryset()
        serializer = self.get_serializer(qs, many=True)
        return Response(serializer.data)


class ResumeViewSet(viewsets.ModelViewSet):
    serializer_class = ResumeSerializer

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
        
        if role == 'tutor':
            if is_senior:
                return Resume.objects.filter(student__branch_id=branch_id)
            else:
                return Resume.objects.filter(student__group__tutor_id=user_id)
        elif role == 'manager':
            return Resume.objects.filter(student__branch_id=branch_id)
            
        return Resume.objects.none()

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
            
            if role == 'tutor':
                if is_senior:
                    qs = ParentReview.objects.filter(student__branch_id=branch_id)
                else:
                    qs = ParentReview.objects.filter(student__group__tutor_id=user_id)
            elif role == 'manager':
                qs = ParentReview.objects.filter(student__branch_id=branch_id)
                
        student_crm_id = self.kwargs.get('student_crm_id')
        if student_crm_id:
            qs = qs.filter(student__student_crm_id=student_crm_id)
            
        return qs


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
