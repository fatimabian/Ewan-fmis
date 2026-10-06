from django.urls import path
from django.views.generic import RedirectView

from .views import (
    AccountActivationView,
    LandingPageView,
    PasswordRecoveryView,
    PrivacyNoticeView,
    TermsOfUseView,
    UserLogoutView,
)

app_name = "authentication"

urlpatterns = [
    path("", LandingPageView.as_view(), name="landing"),
    path(
        "login/",
        RedirectView.as_view(
            pattern_name="authentication:landing",
            permanent=False,
            query_string=True,
        ),
        name="login",
    ),
    path("logout/", UserLogoutView.as_view(), name="logout"),
    path("activate-account/", AccountActivationView.as_view(), name="activate_account"),
    path("privacy/", PrivacyNoticeView.as_view(), name="privacy"),
    path("terms/", TermsOfUseView.as_view(), name="terms"),
    path("password-reset/", PasswordRecoveryView.as_view(), name="password_reset"),
    path(
        "password-reset/done/",
        PasswordRecoveryView.as_view(),
        name="password_reset_done",
    ),
    path(
        "reset/<uidb64>/<token>/",
        PasswordRecoveryView.as_view(),
        name="password_reset_confirm",
    ),
    path(
        "reset/complete/",
        PasswordRecoveryView.as_view(),
        name="password_reset_complete",
    ),
]
