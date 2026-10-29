import secrets

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.core.cache import cache
from django.core.mail import EmailMultiAlternatives

RECOVERY_SESSION_KEY = "fmis_password_recovery_challenge"
RECOVERY_TIMEOUT_SECONDS = 10 * 60
RECOVERY_MAX_ATTEMPTS = 5
RECOVERY_ISSUE_LOCK_SECONDS = 15


class RecoveryIssuanceInProgress(RuntimeError):
    pass


def _cache_key(nonce):
    return f"fmis-password-recovery:{nonce}"


def _active_key(user_id):
    return f"fmis-password-recovery-active:{user_id}"


def _issue_lock_key(user_id):
    return f"fmis-password-recovery-issue-lock:{user_id}"


def _active_challenge(user_id):
    nonce = cache.get(_active_key(user_id))
    challenge = cache.get(_cache_key(nonce)) if nonce else None
    if challenge and challenge.get("user_id") == user_id:
        return nonce, challenge
    cache.delete(_active_key(user_id))
    return None, None


def start_recovery_challenge(request, user=None):
    """Create a session-bound OTP challenge without revealing account existence."""
    lock_key = None
    lock_token = None
    if user:
        active_nonce, active_challenge = _active_challenge(user.pk)
        if active_challenge:
            request.session[RECOVERY_SESSION_KEY] = active_nonce
            return active_nonce
        lock_key = _issue_lock_key(user.pk)
        lock_token = secrets.token_urlsafe(18)
        if not cache.add(lock_key, lock_token, timeout=RECOVERY_ISSUE_LOCK_SECONDS):
            active_nonce, active_challenge = _active_challenge(user.pk)
            if active_challenge:
                request.session[RECOVERY_SESSION_KEY] = active_nonce
                return active_nonce
            raise RecoveryIssuanceInProgress

    try:
        return _create_recovery_challenge(request, user)
    finally:
        if lock_key and cache.get(lock_key) == lock_token:
            cache.delete(lock_key)


def _create_recovery_challenge(request, user=None):
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
            "Your verification code is:\n\n"
            f"{code}\n\n"
            "This code expires in 10 minutes. If you did not request this code, "
            "you may ignore this email.\n\n"
            "Office for Agricultural Services\nRosario, Batangas"
        )
        try:
            sent_count = EmailMultiAlternatives(
                "FMIS — Your Verification Code",
                body,
                settings.DEFAULT_FROM_EMAIL,
                [user.email],
            ).send(fail_silently=False)
            if sent_count != 1:
                raise RuntimeError("The recovery email provider did not accept the message.")
        except Exception:
            cache.delete(_cache_key(nonce))
            request.session.pop(RECOVERY_SESSION_KEY, None)
            raise
        cache.set(_active_key(user.pk), nonce, timeout=RECOVERY_TIMEOUT_SECONDS)
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
        challenge = cache.get(_cache_key(nonce))
        if challenge and challenge.get("user_id") and cache.get(
            _active_key(challenge["user_id"])
        ) == nonce:
            cache.delete(_active_key(challenge["user_id"]))
        cache.delete(_cache_key(nonce))
    request.session.pop(RECOVERY_SESSION_KEY, None)


def recovery_destination(_user):
    # Keep the response identical for known and unknown identifiers so the
    # recovery form cannot be used to discover staff accounts.
    return "the registered email address"
