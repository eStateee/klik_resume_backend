from django.urls import path, include
from django.views.generic import RedirectView
from rest_framework.routers import SimpleRouter
from .views import (
    PasswordlessLoginView, CustomTokenRefreshView, ProfileDetailView, GroupViewSet, StudentViewSet,
    ResumeViewSet, ParentReviewViewSet, NewsViewSet, 
    CategoryViewSet, ModuleViewSet, BranchViewSet, LocationViewSet, EmployeeViewSet
)

router = SimpleRouter()
router.register(r'groups', GroupViewSet, basename='group')
router.register(r'clients', StudentViewSet, basename='client')
router.register(r'resumes', ResumeViewSet, basename='resume')
router.register(r'news', NewsViewSet, basename='news')
router.register(r'categories', CategoryViewSet, basename='category')
router.register(r'modules', ModuleViewSet, basename='module')
router.register(r'branches', BranchViewSet, basename='branch')
router.register(r'locations', LocationViewSet, basename='location')
router.register(r'employees', EmployeeViewSet, basename='employee')

urlpatterns = [
    path('', RedirectView.as_view(url='/api/docs/swagger/', permanent=False), name='api-root-redirect'),
    path('auth/login/', PasswordlessLoginView.as_view(), name='login'),
    path('auth/token/refresh/', CustomTokenRefreshView.as_view(), name='token_refresh'),
    path('profile/detail/', ProfileDetailView.as_view(), name='profile_detail'),
    path('reviews/<str:student_crm_id>/', ParentReviewViewSet.as_view({'get': 'list'}), name='review-list'),
    path('reviews/', ParentReviewViewSet.as_view({'post': 'create'}), name='review-create'),
    path('', include(router.urls)),
]
