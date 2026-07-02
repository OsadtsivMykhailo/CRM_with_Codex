from django.urls import include, path
from rest_framework.routers import DefaultRouter
from .views import (
    AuditLogListView,
    ClientGroupViewSet,
    ClientGroupAdditionRequestViewSet,
    ClientGroupCreationRequestViewSet,
    ClientViewSet,
    DeletionRequestViewSet,
    NotificationViewSet,
    EmailCampaignViewSet,
    EmailServerConfigurationView,
    EmailServerTestView,
    EmailTemplateViewSet,
    SharedSenderViewSet,
    audit_actions,
    register_client,
    unsubscribe_marketing,
)

router = DefaultRouter()
router.register("clients", ClientViewSet, basename="client")
router.register("deletion-requests", DeletionRequestViewSet, basename="deletion-request")
router.register("notifications", NotificationViewSet, basename="notification")
router.register("client-groups", ClientGroupViewSet, basename="client-group")
router.register(
    "client-group-addition-requests",
    ClientGroupAdditionRequestViewSet,
    basename="client-group-addition-request",
)
router.register(
    "client-group-creation-requests",
    ClientGroupCreationRequestViewSet,
    basename="client-group-creation-request",
)
router.register("email-campaigns", EmailCampaignViewSet, basename="email-campaign")
router.register("email-templates", EmailTemplateViewSet, basename="email-template")
router.register("shared-senders", SharedSenderViewSet, basename="shared-sender")

urlpatterns = [
    path("register/", register_client),
    path("audit/", AuditLogListView.as_view()),
    path("audit/actions/", audit_actions),
    path("email-settings/", EmailServerConfigurationView.as_view()),
    path("email-settings/test/", EmailServerTestView.as_view()),
    path("email-unsubscribe/<uuid:token>/", unsubscribe_marketing),
    path("", include(router.urls)),
]
