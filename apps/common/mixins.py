from django.contrib.auth.mixins import LoginRequiredMixin


class FMISLoginRequiredMixin(LoginRequiredMixin):
    login_url = "authentication:login"
