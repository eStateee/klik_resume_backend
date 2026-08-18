import logging
from django.conf import settings
from django.http import HttpResponseRedirect, FileResponse
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from rest_framework import viewsets, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from django.db.models import Count, Q, Subquery, OuterRef
from django.db.models.functions import Coalesce
from drf_spectacular.utils import extend_schema, OpenApiParameter
from drf_spectacular.types import OpenApiTypes

from .serializers import CustomTokenObtainPairSerializer, CustomTokenRefreshSerializer
from .models import Group, Student, Resume, ParentReview, News, Category, Module, Manager, TutorProfile, Branch, Location, Employee
from .serializers import (
    GroupSerializer, StudentSerializer, ResumeSerializer,
    ParentReviewSerializer, NewsSerializer, CategorySerializer,
    CategoryListSerializer, ModuleSerializer, ModuleListSerializer,
    BranchSerializer, LocationSerializer, EmployeeSerializer,
    NO_MODULE_ACCESS_MESSAGE, accessible_module_ids, is_privileged_viewer, resolve_viewer,
    generate_presigned_url
)
from .permissions import IsTutor, IsManager, IsSeniorTutorOrManager
from .pagination import StandardResultsSetPagination


class PasswordlessLoginView(TokenObtainPairView):
    serializer_class = CustomTokenObtainPairSerializer


@extend_schema(
    summary="Обновление access-токена",
    description=(
        "Выдаёт новый access-токен по refresh-токену. Владелец токена ищется "
        "по клейму `role` в таблице Manager или TutorProfile. Клеймы "
        "(`is_senior`, `branch_id`, `location_id`) перечитываются из БД, "
        "поэтому изменения прав применяются сразу после обновления токена. "
        "Деактивированный или удалённый пользователь получает 401."
    ),
)
class CustomTokenRefreshView(TokenRefreshView):
    serializer_class = CustomTokenRefreshSerializer


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
        
        # Подзапрос: кол-во студентов, у которых ВСЕ резюме проверены
        verified_subq = (
            Student.objects.filter(
                group=OuterRef('pk'),
                is_added=True,
            )
            .exclude(resumes__is_verified=False)
            .order_by()
            .values('group')
            .annotate(cnt=Count('id'))
            .values('cnt')
        )

        return qs.annotate(
            total_students=Count('students', distinct=True),
            resumes_written_count=Count('students', filter=Q(students__is_added=True), distinct=True),
            resumes_verified_count=Coalesce(Subquery(verified_subq), 0),
        ).order_by('name')

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

    @extend_schema(
        summary="Получить список студентов группы",
        description="Возвращает список всех студентов, привязанных к указанной группе.",
        responses={200: StudentSerializer(many=True)},
    )
    @action(detail=True, methods=['get'])
    def clients(self, request, pk=None):
        group = self.get_object()
        students = group.students.select_related('group').all()
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
            return Student.objects.select_related('group').all()
        elif role == 'tutor':
            return Student.objects.select_related('group').filter(group__tutor_id=user_id)
        elif role == 'manager':
            return Student.objects.select_related('group').filter(branch_id=branch_id)
            
        return Student.objects.select_related('group').none()

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
    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        if self.action == 'list':
            return CategoryListSerializer
        return CategorySerializer

    @extend_schema(
        summary="Получить список категорий",
        description="Возвращает категории вместе с подкатегориями, БЕЗ модулей и уроков.",
        responses={200: CategoryListSerializer(many=True)},
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(
        summary="Получить категорию по ID",
        description="Возвращает категорию вместе с подкатегориями, модулями и уроками.",
        responses={200: CategorySerializer},
    )
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)


class ModuleViewSet(viewsets.ReadOnlyModelViewSet):
    """
    GET /api/modules/          — все активные модули, без уроков и без разделения по ролям.
    GET /api/modules/<id>/     — модуль вместе с уроками.
    GET /api/modules/tutor/    — модули, доступные владельцу access-токена.
    """
    queryset = Module.objects.filter(is_active=True)
    serializer_class = ModuleSerializer
    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        # В списке уроки не отдаём — только сами модули
        if self.action == 'list':
            return ModuleListSerializer
        return ModuleSerializer

    @extend_schema(
        summary="Получить список модулей",
        description=(
            "Возвращает ВСЕ активные модули без разделения по ролям.\n\n"
            "Уроки в этом эндпоинте **не отдаются** — только сами модули. "
            "Чтобы получить уроки, используйте `GET /api/modules/{id}/` "
            "или `GET /api/modules/tutor/`.\n\n"
            "Поле `is_accessible` показывает, есть ли доступ к модулю у текущего "
            "пользователя: у менеджера и старшего тьютора — всегда `true`, "
            "у обычного тьютора — по наличию активного `TutorModule`."
        ),
        responses={200: ModuleListSerializer(many=True)},
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(
        summary="Получить модуль по ID",
        description=(
            "Возвращает модуль вместе с уроками. Доступен всем авторизованным "
            "пользователям без разделения по ролям.\n\n"
            "Уроки отдаются, только если `is_accessible` = `true`, иначе `lessons` пуст."
        ),
        responses={200: ModuleSerializer},
    )
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)

    @extend_schema(
        summary="Получить доступные модули текущего пользователя",
        description=(
            "Пользователь определяется по access-токену, параметры не передаются.\n\n"
            "**Правила выдачи:**\n"
            "- **Менеджер / Старший тьютор:** все активные модули (полный доступ).\n"
            "- **Обычный тьютор:** только модули с активным (непросроченным) "
            "доступом `TutorModule`; остальные в ответ не попадают.\n\n"
            "Модули возвращаются вместе с уроками.\n\n"
            f"Если доступных модулей нет, возвращается "
            f"`{{\"detail\": \"{NO_MODULE_ACCESS_MESSAGE}\"}}`."
        ),
        responses={200: ModuleSerializer(many=True)},
    )
    @action(detail=False, methods=['get'], url_path='tutor')
    def my(self, request):
        role, user_id, is_senior = resolve_viewer(request)

        qs = Module.objects.filter(is_active=True)
        if not is_privileged_viewer(role, is_senior):
            qs = qs.filter(id__in=accessible_module_ids(user_id))

        if not qs.exists():
            return Response({"detail": NO_MODULE_ACCESS_MESSAGE})

        serializer = self.get_serializer(qs, many=True)
        return Response(serializer.data)


class BranchViewSet(viewsets.ReadOnlyModelViewSet):
    """GET /api/branches/ — список всех филиалов"""
    queryset = Branch.objects.all()
    serializer_class = BranchSerializer
    permission_classes = [IsAuthenticated]


class LocationViewSet(viewsets.ReadOnlyModelViewSet):
    """
    GET /api/locations/ — все локации.
    GET /api/locations/?branch_id=<id> — локации конкретного филиала.
    """
    queryset = Location.objects.filter(is_active=True)
    serializer_class = LocationSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        branch_id = self.request.query_params.get("branch_id")
        if branch_id is not None:
            return Location.objects.filter(is_active=True, branch_id=branch_id)
        return Location.objects.filter(is_active=True)

    @extend_schema(
        summary="Получить весь список локаций или список локаций конкретного филиала",
        description=(
            "Возвращает список всех локаций. "
            "Если передан `branch_id` — возвращаются только локации этого филиала."
        ),
        parameters=[
            OpenApiParameter(
                name="branch_id",
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                required=False,
                description="ID филиала для фильтрации локаций.",
            )
        ],
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(
        summary="Получить локацию по ID",
        parameters=[
            OpenApiParameter(
                name="id",
                type=OpenApiTypes.INT,
                location=OpenApiParameter.PATH,
                description="ID локации (location_id)",
            )
        ],
    )
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)


class EmployeeViewSet(viewsets.ReadOnlyModelViewSet):
    """
    GET /api/employees/ — список всех сотрудников
    GET /api/employees/{id}/ — получение сотрудника по ID
    """
    queryset = Employee.objects.select_related("branch", "location").all()
    serializer_class = EmployeeSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = None

    @extend_schema(
        summary="Получить список всех сотрудников",
        description="Возвращает список всех сотрудников.",
        responses={200: EmployeeSerializer(many=True)},
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(
        summary="Получить сотрудника по ID",
        description="Возвращает детальную информацию о сотруднике по ID.",
        parameters=[
            OpenApiParameter(
                name="id",
                type=OpenApiTypes.INT,
                location=OpenApiParameter.PATH,
                description="ID сотрудника",
            )
        ],
        responses={200: EmployeeSerializer},
    )
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)

    # Временно скрыто: эндпоинт получения фото сотрудника
    # @extend_schema(
    #     summary="Получить фотографию сотрудника",
    #     description="Возвращает файл фотографии сотрудника или перенаправляет на актуальный файл в хранилище.",
    #     parameters=[
    #         OpenApiParameter(
    #             name="id",
    #             type=OpenApiTypes.INT,
    #             location=OpenApiParameter.PATH,
    #             description="ID сотрудника",
    #         )
    #     ],
    #     responses={200: bytes, 404: dict},
    # )
    # @action(detail=True, methods=["get"], permission_classes=[])
    # def photo(self, request, pk=None):
    #     employee = self.get_object()
    #     if not employee.photo or not employee.photo.name:
    #         return Response(
    #             {"detail": "У сотрудника нет фотографии."},
    #             status=status.HTTP_404_NOT_FOUND,
    #         )
    #
    #     if getattr(settings, "AWS_ACCESS_KEY_ID", None) and getattr(
    #         settings, "AWS_SECRET_ACCESS_KEY", None
    #     ):
    #         try:
    #             s3_url = generate_presigned_url(employee.photo, expires_in=900)
    #             if s3_url:
    #                 return HttpResponseRedirect(s3_url)
    #         except Exception as exc:
    #             logging.getLogger("core").error(
    #                 "Ошибка получения photo S3 URL для Employee id=%s: %s",
    #                 employee.pk,
    #                 exc,
    #             )
    #
    #     try:
    #         return FileResponse(employee.photo.open("rb"))
    #     except FileNotFoundError:
    #         return Response(
    #             {"detail": "Файл фотографии не найден."},
    #             status=status.HTTP_404_NOT_FOUND,
    #         )



