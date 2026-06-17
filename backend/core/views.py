from rest_framework_simplejwt.views import TokenObtainPairView
from .serializers import CustomTokenObtainPairSerializer
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from .models import Group, Student, Resume, ParentReview, News, Category, Module
from .serializers import GroupSerializer, StudentSerializer, ResumeSerializer, ParentReviewSerializer, NewsSerializer, CategorySerializer, ModuleSerializer
from .permissions import IsTutor, IsManager, IsSeniorTutorOrManager
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework import status

class PasswordlessLoginView(TokenObtainPairView):
    serializer_class = CustomTokenObtainPairSerializer

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

    @action(detail=False, methods=['get'])
    def all(self, request):
        if not (IsManager().has_permission(request, self) or (IsTutor().has_permission(request, self) and request.auth.get('is_senior'))):
            return Response(status=status.HTTP_403_FORBIDDEN)
        qs = self.get_queryset()
        serializer = self.get_serializer(qs, many=True)
        return Response(serializer.data)

class ResumeViewSet(viewsets.ModelViewSet):
    serializer_class = ResumeSerializer
    permission_classes = [IsAuthenticated]

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

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated, IsSeniorTutorOrManager])
    def verify(self, request, pk=None):
        resume = self.get_object()
        resume.is_verified = True
        resume.save()
        return Response({"status": "verified"})

    def destroy(self, request, *args, **kwargs):
        if not IsSeniorTutorOrManager().has_permission(request, self):
            return Response(status=status.HTTP_403_FORBIDDEN)
        return super().destroy(request, *args, **kwargs)

class ParentReviewViewSet(viewsets.ModelViewSet):
    serializer_class = ParentReviewSerializer
    
    def get_permissions(self):
        if self.action == 'create':
            return []
        return [IsAuthenticated()]

    def get_queryset(self):
        auth = self.request.auth
        if not auth:
            qs = ParentReview.objects.none()
        else:
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
            else:
                qs = ParentReview.objects.none()
                
        student_crm_id = self.kwargs.get('student_crm_id')
        if student_crm_id:
            qs = qs.filter(student__student_crm_id=student_crm_id)
        return qs

class NewsViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = News.objects.all().order_by('-created_at')
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
