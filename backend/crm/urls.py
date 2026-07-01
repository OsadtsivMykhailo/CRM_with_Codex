from django.urls import include, path
from rest_framework.routers import DefaultRouter
from .views import (
    AuditLogListView,
    ClientViewSet,
    DeletionRequestViewSet,
    NotificationViewSet,
    audit_actions,
    register_client,
)

router = DefaultRouter()
router.register("clients", ClientViewSet, basename="client")
router.register("deletion-requests", DeletionRequestViewSet, basename="deletion-request")
router.register("notifications", NotificationViewSet, basename="notification")

urlpatterns = [
    path("register/", register_client),
    path("audit/", AuditLogListView.as_view()),
    path("audit/actions/", audit_actions),
    path("", include(router.urls)),
]
