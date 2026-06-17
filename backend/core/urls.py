from django.urls import path, include
from django.views.generic import RedirectView
from rest_framework_simplejwt.views import TokenRefreshView
from rest_framework.routers import SimpleRouter
from .views import (
    PasswordlessLoginView, GroupViewSet, StudentViewSet, 
    ResumeViewSet, ParentReviewViewSet, NewsViewSet, 
    CategoryViewSet, ModuleViewSet
)

router = SimpleRouter()
router.register(r'groups', GroupViewSet, basename='group')
router.register(r'clients', StudentViewSet, basename='client')
router.register(r'resumes', ResumeViewSet, basename='resume')
router.register(r'news', NewsViewSet, basename='news')
router.register(r'categories', CategoryViewSet, basename='category')
router.register(r'modules', ModuleViewSet, basename='module')

urlpatterns = [
    path('', RedirectView.as_view(url='/api/docs/swagger/', permanent=False), name='api-root-redirect'),
    path('auth/login/', PasswordlessLoginView.as_view(), name='login'),
    path('auth/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('reviews/<str:student_crm_id>/', ParentReviewViewSet.as_view({'get': 'list'}), name='review-list'),
    path('reviews/', ParentReviewViewSet.as_view({'post': 'create'}), name='review-create'),
    path('', include(router.urls)),
]
