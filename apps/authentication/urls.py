from django.urls import path
from .views import (
    AccountActivationView,
    LandingPageView,
    MFARecoveryCodesView,
    MFASetupView,
    MFAVerificationView,
    PasswordRecoveryView,
    PrivacyNoticeView,
    TermsOfUseView,
    StaffRegistrationView,
    UserLoginView,
    UserLogoutView,
)

app_name = "authentication"

urlpatterns = [
    path("", LandingPageView.as_view(), name="landing"),
    path("login/", UserLoginView.as_view(), name="login"),
    path("register-staff/", StaffRegistrationView.as_view(), name="register_staff"),
    path("logout/", UserLogoutView.as_view(), name="logout"),
    path("activate-account/", AccountActivationView.as_view(), name="activate_account"),
    path("mfa/setup/", MFASetupView.as_view(), name="mfa_setup"),
    path("mfa/verify/", MFAVerificationView.as_view(), name="mfa_verify"),
    path(
        "mfa/recovery-codes/",
        MFARecoveryCodesView.as_view(),
        name="mfa_recovery_codes",
    ),
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
