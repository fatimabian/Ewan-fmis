import base64
import hashlib
import hmac
import io
import secrets
import struct
import time
from urllib.parse import quote, urlencode

import qrcode
from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.core import signing


MFA_SESSION_KEY = "fmis_mfa_challenge"
MFA_RECOVERY_SESSION_KEY = "fmis_mfa_recovery_codes"
TRUSTED_DEVICE_COOKIE = "fmis_trusted_device"
TRUSTED_DEVICE_SALT = "authentication.trusted-device.v1"
MFA_CHALLENGE_SECONDS = 10 * 60
MFA_MAX_ATTEMPTS = 5
TOTP_PERIOD_SECONDS = 30
TOTP_DIGITS = 6
TOTP_ISSUER = "Rosario FMIS"
RECOVERY_CODE_COUNT = 10
RECOVERY_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"


def _trusted_device_seconds():
    return int(settings.FMIS_TRUSTED_DEVICE_DAYS) * 24 * 60 * 60


def _trusted_entries(request):
    signed_value = request.COOKIES.get(TRUSTED_DEVICE_COOKIE, "")
    if not signed_value:
        return {}
    try:
        payload = signing.loads(signed_value, salt=TRUSTED_DEVICE_SALT)
    except (signing.BadSignature, TypeError, ValueError):
        return {}
    entries = payload.get("accounts", {}) if isinstance(payload, dict) else {}
    return entries if isinstance(entries, dict) else {}


def trusted_device_is_valid(request, user, *, now=None):
    if not user.mfa_enabled:
        return False
    current_time = int(time.time() if now is None else now)
    entry = _trusted_entries(request).get(str(user.pk), {})
    try:
        trusted_at = int(entry["trusted_at"])
        version = int(entry["mfa_version"])
    except (KeyError, TypeError, ValueError):
        return False
    age = current_time - trusted_at
    return 0 <= age <= _trusted_device_seconds() and version == user.mfa_version


def remember_trusted_device(request, response, user):
    now = int(time.time())
    lifetime = _trusted_device_seconds()
    entries = {}
    for user_id, entry in _trusted_entries(request).items():
        try:
            if 0 <= now - int(entry["trusted_at"]) <= lifetime:
                entries[str(user_id)] = entry
        except (KeyError, TypeError, ValueError):
            continue
    entries[str(user.pk)] = {
        "mfa_version": user.mfa_version,
        "trusted_at": now,
    }
    # The office has fewer than ten accounts; this also bounds cookie growth.
    newest = sorted(
        entries.items(), key=lambda item: int(item[1]["trusted_at"]), reverse=True
    )[:20]
    response.set_cookie(
        TRUSTED_DEVICE_COOKIE,
        signing.dumps({"accounts": dict(newest)}, salt=TRUSTED_DEVICE_SALT, compress=True),
        max_age=lifetime,
        secure=not settings.DEBUG,
        httponly=True,
        samesite="Lax",
        path="/",
    )


def forget_trusted_devices(response):
    response.delete_cookie(
        TRUSTED_DEVICE_COOKIE,
        path="/",
        samesite="Lax",
    )


def _fernet():
    material = hashlib.sha256(f"fmis-mfa:{settings.SECRET_KEY}".encode()).digest()
    return Fernet(base64.urlsafe_b64encode(material))


def encrypt_secret(secret):
    return _fernet().encrypt(secret.encode("ascii")).decode("ascii")


def decrypt_secret(encrypted):
    try:
        return _fernet().decrypt(encrypted.encode("ascii")).decode("ascii")
    except (InvalidToken, ValueError, TypeError):
        return None


def generate_secret():
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def _decode_secret(secret):
    padded = secret.upper() + "=" * ((8 - len(secret) % 8) % 8)
    return base64.b32decode(padded, casefold=True)


def totp_at(secret, counter):
    digest = hmac.new(
        _decode_secret(secret), struct.pack(">Q", counter), hashlib.sha1
    ).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(value % (10**TOTP_DIGITS)).zfill(TOTP_DIGITS)


def verify_totp(secret, code, *, now=None, last_counter=None):
    if not code or not code.isdigit() or len(code) != TOTP_DIGITS:
        return None
    current = int((time.time() if now is None else now) // TOTP_PERIOD_SECONDS)
    for counter in range(current - 1, current + 2):
        if last_counter is not None and counter <= last_counter:
            continue
        if hmac.compare_digest(totp_at(secret, counter), code):
            return counter
    return None


def provisioning_uri(secret, user):
    account = user.email or user.username
    label = quote(f"{TOTP_ISSUER}:{account}", safe="")
    query = urlencode(
        {
            "secret": secret,
            "issuer": TOTP_ISSUER,
            "algorithm": "SHA1",
            "digits": TOTP_DIGITS,
            "period": TOTP_PERIOD_SECONDS,
        }
    )
    return f"otpauth://totp/{label}?{query}"


def provisioning_qr_data_uri(secret, user):
    image = qrcode.make(provisioning_uri(secret, user), box_size=6, border=3)
    output = io.BytesIO()
    image.save(output, format="PNG")
    encoded = base64.b64encode(output.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def generate_recovery_codes():
    codes = []
    for _ in range(RECOVERY_CODE_COUNT):
        raw = "".join(secrets.choice(RECOVERY_ALPHABET) for _ in range(10))
        codes.append(f"{raw[:5]}-{raw[5:]}")
    return codes


def hash_recovery_codes(codes):
    return [make_password(normalize_recovery_code(code)) for code in codes]


def normalize_recovery_code(code):
    return "".join(character for character in (code or "").upper() if character.isalnum())


def consume_recovery_code(user, candidate):
    normalized = normalize_recovery_code(candidate)
    if not normalized:
        return False
    for index, encoded in enumerate(user.mfa_recovery_codes or []):
        if check_password(normalized, encoded):
            remaining = list(user.mfa_recovery_codes)
            remaining.pop(index)
            user.mfa_recovery_codes = remaining
            user.save(update_fields=["mfa_recovery_codes"])
            return True
    return False


def start_mfa_challenge(request, user, *, remember_me=False, next_url=""):
    request.session.cycle_key()
    request.session[MFA_SESSION_KEY] = {
        "user_id": user.pk,
        "remember_me": bool(remember_me),
        "next_url": next_url or "",
        "started_at": int(time.time()),
    }
    request.session.modified = True


def get_mfa_challenge(request):
    challenge = request.session.get(MFA_SESSION_KEY)
    if not challenge:
        return None
    if int(time.time()) - int(challenge.get("started_at", 0)) > MFA_CHALLENGE_SECONDS:
        clear_mfa_challenge(request)
        return None
    return challenge


def clear_mfa_challenge(request):
    request.session.pop(MFA_SESSION_KEY, None)
    request.session.pop("fmis_mfa_setup_secret", None)
