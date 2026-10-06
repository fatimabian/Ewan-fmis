import secrets

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.core.cache import cache
from django.core.mail import EmailMultiAlternatives

RECOVERY_SESSION_KEY = "fmis_password_recovery_challenge"
RECOVERY_TIMEOUT_SECONDS = 10 * 60
RECOVERY_MAX_ATTEMPTS = 5


def _cache_key(nonce):
    return f"fmis-password-recovery:{nonce}"


def start_recovery_challenge(request, user=None):
    """Create a session-bound OTP challenge without revealing account existence."""
    code = f"{secrets.randbelow(1_000_000):06d}"
    nonce = secrets.token_urlsafe(24)
    challenge = {
        "user_id": user.pk if user else None,
        "code_hash": make_password(code),
        "attempts": 0,
        "verified": False,
    }
    cache.set(_cache_key(nonce), challenge, timeout=RECOVERY_TIMEOUT_SECONDS)
    request.session[RECOVERY_SESSION_KEY] = nonce

    if user and user.email:
        body = (
            f"Hello {user.display_name},\n\n"
            f"Your FMIS password recovery code is: {code}\n\n"
            "This code expires in 10 minutes. If you did not request a password "
            "reset, contact your FMIS administrator.\n\n"
            "Office for Agricultural Services\nRosario, Batangas"
        )
        EmailMultiAlternatives(
            "Your FMIS password recovery code",
            body,
            settings.DEFAULT_FROM_EMAIL,
            [user.email],
        ).send()
    return nonce


def get_recovery_challenge(request):
    nonce = request.session.get(RECOVERY_SESSION_KEY)
    return (nonce, cache.get(_cache_key(nonce))) if nonce else (None, None)


def verify_recovery_code(nonce, challenge, code):
    if not challenge or challenge["attempts"] >= RECOVERY_MAX_ATTEMPTS:
        return False
    if not challenge.get("user_id") or not check_password(code, challenge["code_hash"]):
        challenge["attempts"] += 1
        cache.set(_cache_key(nonce), challenge, timeout=RECOVERY_TIMEOUT_SECONDS)
        return False
    challenge["verified"] = True
    cache.set(_cache_key(nonce), challenge, timeout=RECOVERY_TIMEOUT_SECONDS)
    return True


def clear_recovery_challenge(request, nonce=None):
    nonce = nonce or request.session.get(RECOVERY_SESSION_KEY)
    if nonce:
        cache.delete(_cache_key(nonce))
    request.session.pop(RECOVERY_SESSION_KEY, None)


def recovery_destination(_user):
    # Keep the response identical for known and unknown identifiers so the
    # recovery form cannot be used to discover staff accounts.
    return "the registered email address"
