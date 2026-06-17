from rest_framework.permissions import BasePermission

class IsTutor(BasePermission):
    def has_permission(self, request, view):
        return bool(request.auth and request.auth.get('role') == 'tutor')

class IsManager(BasePermission):
    def has_permission(self, request, view):
        return bool(request.auth and request.auth.get('role') == 'manager')

class IsSeniorTutorOrManager(BasePermission):
    def has_permission(self, request, view):
        if not request.auth:
            return False
        role = request.auth.get('role')
        is_senior = request.auth.get('is_senior')
        
        if role == 'manager':
            return True
        if role == 'tutor' and is_senior:
            return True
        return False
