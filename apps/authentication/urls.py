from django.urls import path
from .views import (
    AccountActivationView,
    LandingPageView,
    PasswordRecoveryView,
    PrivacyNoticeView,
    TermsOfUseView,
    UserLoginView,
    UserLogoutView,
)

app_name = "authentication"

urlpatterns = [
    path("", LandingPageView.as_view(), name="landing"),
    path("login/", UserLoginView.as_view(), name="login"),
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
