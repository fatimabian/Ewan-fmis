from django.contrib.auth import views as auth_views
from django.urls import path, reverse_lazy

from .views import GoogleLoginView, LandingPageView, PasswordRecoveryView, PrivacyNoticeView, TermsOfUseView, UserLoginView, UserLogoutView

app_name = "authentication"

urlpatterns = [
    path("", LandingPageView.as_view(), name="landing"),
    path("login/", UserLoginView.as_view(), name="login"),
    path("login/google/", GoogleLoginView.as_view(), name="google_login"),
    path("logout/", UserLogoutView.as_view(), name="logout"),
    path("privacy/", PrivacyNoticeView.as_view(), name="privacy"),
    path("terms/", TermsOfUseView.as_view(), name="terms"),
    path("password-reset/", PasswordRecoveryView.as_view(), name="password_reset"),
    path("password-reset/done/", auth_views.PasswordResetDoneView.as_view(template_name="authentication/password_reset_done.html"), name="password_reset_done"),
    path("reset/<uidb64>/<token>/", auth_views.PasswordResetConfirmView.as_view(template_name="authentication/password_reset_confirm.html", success_url=reverse_lazy("authentication:password_reset_complete")), name="password_reset_confirm"),
    path("reset/complete/", auth_views.PasswordResetCompleteView.as_view(template_name="authentication/password_reset_complete.html"), name="password_reset_complete"),
]
