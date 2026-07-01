from datetime import timedelta

from django.utils import timezone
from rest_framework import generics, permissions, status
from rest_framework.authtoken.models import Token
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import EmployeeProfile, LoginAttempt, User
from .permissions import IsAdmin
from .serializers import EmployeeSerializer, LoginSerializer, UserSerializer
from crm.services import audit, deactivate_employee, security_audit


MAX_LOGIN_FAILURES = 5
LOGIN_WINDOW = timedelta(minutes=15)


def request_ip(request):
    return request.META.get("REMOTE_ADDR") or None


def consecutive_failures(username, ip_address):
    cutoff = timezone.now() - LOGIN_WINDOW

    user_events = LoginAttempt.objects.filter(username__iexact=username, created_at__gte=cutoff)
    latest_user_success = user_events.filter(successful=True).order_by("-created_at").first()
    if latest_user_success:
        user_events = user_events.filter(created_at__gt=latest_user_success.created_at)
    user_failures = user_events.filter(successful=False).count()

    ip_failures = 0
    if ip_address:
        ip_events = LoginAttempt.objects.filter(ip_address=ip_address, created_at__gte=cutoff)
        latest_ip_success = ip_events.filter(successful=True).order_by("-created_at").first()
        if latest_ip_success:
            ip_events = ip_events.filter(created_at__gt=latest_ip_success.created_at)
        ip_failures = ip_events.filter(successful=False).count()
    return max(user_failures, ip_failures)


class LoginView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        username = str(request.data.get("username", "")).strip()
        ip_address = request_ip(request)
        if consecutive_failures(username, ip_address) >= MAX_LOGIN_FAILURES:
            security_audit(None, "auth.login_blocked", username, {"ip_address": ip_address})
            return Response(
                {"detail": "Забагато невдалих спроб. Повторіть вхід через 15 хвилин."},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
        serializer = LoginSerializer(data=request.data)
        if not serializer.is_valid():
            LoginAttempt.objects.create(username=username, ip_address=ip_address, successful=False)
            user = User.objects.filter(username__iexact=username).first()
            security_audit(user, "auth.login_failed", username, {"ip_address": ip_address})
            if consecutive_failures(username, ip_address) >= MAX_LOGIN_FAILURES:
                return Response(
                    {"detail": "Забагато невдалих спроб. Вхід заблоковано на 15 хвилин."},
                    status=status.HTTP_429_TOO_MANY_REQUESTS,
                )
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        user = serializer.validated_data["user"]
        LoginAttempt.objects.create(username=username, ip_address=ip_address, successful=True)
        security_audit(user, "auth.login_succeeded", username, {"ip_address": ip_address})
        token, _ = Token.objects.get_or_create(user=user)
        return Response({"token": token.key, "user": UserSerializer(user).data})


class LogoutView(APIView):
    def post(self, request):
        security_audit(request.user, "auth.logout", request.user.username)
        Token.objects.filter(user=request.user).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(APIView):
    def get(self, request):
        return Response(UserSerializer(request.user).data)


class EmployeeListCreateView(generics.ListCreateAPIView):
    queryset = EmployeeProfile.objects.select_related("user").order_by("user__last_name")
    serializer_class = EmployeeSerializer
    permission_classes = [IsAdmin]

    def perform_create(self, serializer):
        employee = serializer.save()
        audit(self.request.user, "employee.created", employee, {"fields": list(serializer.validated_data)})


class EmployeeDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = EmployeeProfile.objects.select_related("user")
    serializer_class = EmployeeSerializer
    permission_classes = [IsAdmin]

    def perform_update(self, serializer):
        was_active = serializer.instance.user.is_active
        employee = serializer.save()
        deactivation_result = None
        if was_active and not employee.user.is_active:
            deactivation_result = deactivate_employee(employee.user, self.request.user)
            Token.objects.filter(user=employee.user).delete()
        audit(self.request.user, "employee.updated", employee, {"fields": list(serializer.validated_data)})
        if deactivation_result:
            audit(self.request.user, "employee.deactivated", employee, deactivation_result)

    def destroy(self, request, *args, **kwargs):
        employee = self.get_object()
        result = deactivate_employee(employee.user, request.user)
        Token.objects.filter(user=employee.user).delete()
        audit(request.user, "employee.deactivated", employee, result)
        return Response(status=status.HTTP_204_NO_CONTENT)
