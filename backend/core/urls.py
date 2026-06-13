from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView
from .views import PasswordlessLoginView

urlpatterns = [
    path('auth/login/', PasswordlessLoginView.as_view(), name='login'),
    path('auth/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
]
