import secrets

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.core.cache import cache
from django.core.mail import EmailMultiAlternatives

ACTIVATION_SESSION_KEY = "fmis_activation_challenge"
ACTIVATION_TIMEOUT_SECONDS = 10 * 60
ACTIVATION_MAX_ATTEMPTS = 5


def _cache_key(nonce):
    return f"fmis-account-activation:{nonce}"


def masked_email(email):
    local, separator, domain = (email or "").partition("@")
    if not separator:
        return "the registered email address"
    visible = local[:2] if len(local) > 2 else local[:1]
    return f"{visible}{'*' * max(2, len(local) - len(visible))}@{domain}"


def send_activation_code(request, user, remember_me=False):
    code = f"{secrets.randbelow(1_000_000):06d}"
    nonce = secrets.token_urlsafe(24)
    cache.set(
        _cache_key(nonce),
        {
            "user_id": user.pk,
            "code_hash": make_password(code),
            "attempts": 0,
            "remember_me": bool(remember_me),
        },
        timeout=ACTIVATION_TIMEOUT_SECONDS,
    )
    request.session[ACTIVATION_SESSION_KEY] = nonce
    body = (
        f"Hello {user.display_name},\n\n"
        f"Your FMIS account activation code is: {code}\n\n"
        "This code expires in 10 minutes. If you did not try to sign in, "
        "contact your FMIS administrator.\n\n"
        "Office for Agricultural Services\nRosario, Batangas"
    )
    EmailMultiAlternatives(
        "Your FMIS account activation code",
        body,
        settings.DEFAULT_FROM_EMAIL,
        [user.email],
    ).send()
    return nonce


def get_activation_challenge(request):
    nonce = request.session.get(ACTIVATION_SESSION_KEY)
    if not nonce:
        return None, None
    return nonce, cache.get(_cache_key(nonce))


def verify_activation_code(nonce, challenge, code):
    if not challenge or challenge["attempts"] >= ACTIVATION_MAX_ATTEMPTS:
        return False
    if not check_password(code, challenge["code_hash"]):
        challenge["attempts"] += 1
        cache.set(
            _cache_key(nonce),
            challenge,
            timeout=ACTIVATION_TIMEOUT_SECONDS,
        )
        return False
    return True


def clear_activation_challenge(request, nonce):
    cache.delete(_cache_key(nonce))
    request.session.pop(ACTIVATION_SESSION_KEY, None)
