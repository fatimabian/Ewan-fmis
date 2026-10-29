import secrets

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.core.cache import cache
from django.core.mail import EmailMultiAlternatives

ACTIVATION_SESSION_KEY = "fmis_activation_challenge"
ACTIVATION_TIMEOUT_SECONDS = 10 * 60
ACTIVATION_MAX_ATTEMPTS = 5
ACTIVATION_RESEND_COOLDOWN_SECONDS = 60
ACTIVATION_ISSUE_LOCK_SECONDS = 15


class ActivationIssuanceInProgress(RuntimeError):
    pass


class ActivationResendCooldown(RuntimeError):
    pass


def _cache_key(nonce):
    return f"fmis-account-activation:{nonce}"


def _active_key(user_id):
    return f"fmis-account-activation-active:{user_id}"


def _issue_lock_key(user_id):
    return f"fmis-account-activation-issue-lock:{user_id}"


def _resend_key(user_id):
    return f"fmis-account-activation-resend:{user_id}"


def _active_challenge(user_id):
    nonce = cache.get(_active_key(user_id))
    challenge = cache.get(_cache_key(nonce)) if nonce else None
    if challenge and challenge.get("user_id") == user_id:
        return nonce, challenge
    cache.delete(_active_key(user_id))
    return None, None


def masked_email(email):
    local, separator, domain = (email or "").partition("@")
    if not separator:
        return "the registered email address"
    visible = local[:2] if len(local) > 2 else local[:1]
    return f"{visible}{'*' * max(2, len(local) - len(visible))}@{domain}"


def send_activation_code(request, user, remember_me=False, *, force_new=False):
    """Issue at most one active activation OTP per user.

    The random nonce may be shared between browser sessions, but the OTP itself
    is only ever present in the one outbound email and its password hash is all
    that is retained server-side.
    """
    active_nonce, active_challenge = _active_challenge(user.pk)
    if active_challenge and not force_new:
        request.session[ACTIVATION_SESSION_KEY] = active_nonce
        return active_nonce, False
    if force_new and cache.get(_resend_key(user.pk)):
        raise ActivationResendCooldown

    lock_key = _issue_lock_key(user.pk)
    lock_token = secrets.token_urlsafe(18)
    if not cache.add(lock_key, lock_token, timeout=ACTIVATION_ISSUE_LOCK_SECONDS):
        active_nonce, active_challenge = _active_challenge(user.pk)
        if active_challenge and not force_new:
            request.session[ACTIVATION_SESSION_KEY] = active_nonce
            return active_nonce, False
        raise ActivationIssuanceInProgress

    old_nonce = active_nonce
    try:
        # A request may have finished between the first check and lock acquisition.
        active_nonce, active_challenge = _active_challenge(user.pk)
        if active_challenge and not force_new:
            request.session[ACTIVATION_SESSION_KEY] = active_nonce
            return active_nonce, False

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
                raise RuntimeError("The activation email provider did not accept the message.")
        except Exception:
            cache.delete(_cache_key(nonce))
            raise

        cache.set(_active_key(user.pk), nonce, timeout=ACTIVATION_TIMEOUT_SECONDS)
        cache.set(_resend_key(user.pk), True, timeout=ACTIVATION_RESEND_COOLDOWN_SECONDS)
        request.session[ACTIVATION_SESSION_KEY] = nonce
        if old_nonce and old_nonce != nonce:
            cache.delete(_cache_key(old_nonce))
        return nonce, True
    finally:
        if cache.get(lock_key) == lock_token:
            cache.delete(lock_key)


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
    challenge = cache.get(_cache_key(nonce)) if nonce else None
    if challenge and cache.get(_active_key(challenge.get("user_id"))) == nonce:
        cache.delete(_active_key(challenge.get("user_id")))
    cache.delete(_cache_key(nonce))
    request.session.pop(ACTIVATION_SESSION_KEY, None)
