import base64
import json
from urllib.parse import urlparse

from fastapi import Request
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    verify_authentication_response,
    verify_registration_response,
    options_to_json,
)
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from app.core.config import settings


def b64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def b64url_decode(value: str) -> bytes:
    raw = str(value or "").strip().encode("ascii")
    padding = b"=" * ((4 - (len(raw) % 4)) % 4)
    return base64.urlsafe_b64decode(raw + padding)


def _effective_base_url(request: Request) -> str:
    configured = str(settings.FT_BASE_URL or "").strip().rstrip("/")
    if configured:
        return configured

    forwarded_proto = request.headers.get("x-forwarded-proto")
    forwarded_host = request.headers.get("x-forwarded-host")
    scheme = forwarded_proto or request.url.scheme
    host = forwarded_host or request.headers.get("host") or request.url.netloc
    return f"{scheme}://{host}"


def get_rp_id(request: Request) -> str:
    base = _effective_base_url(request)
    parsed = urlparse(base)
    host = (parsed.hostname or request.url.hostname or "").strip()
    return host


def get_expected_origin(request: Request) -> str:
    base = _effective_base_url(request)
    parsed = urlparse(base)
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}"
    return base


def build_registration_options(
    *,
    request: Request,
    user_id: str,
    username: str,
    display_name: str,
    exclude_credential_ids: list[str],
) -> dict:
    rp_id = get_rp_id(request)
    exclude_credentials = [
        PublicKeyCredentialDescriptor(id=b64url_decode(cred_id))
        for cred_id in exclude_credential_ids
        if cred_id
    ]

    options = generate_registration_options(
        rp_id=rp_id,
        rp_name=settings.FT_APP_NAME,
        user_id=user_id.encode("utf-8"),
        user_name=username,
        user_display_name=display_name,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.REQUIRED,
            user_verification=UserVerificationRequirement.PREFERRED,
        ),
        exclude_credentials=exclude_credentials,
    )
    return json.loads(options_to_json(options))


def verify_registration(
    *,
    request: Request,
    credential: dict,
    expected_challenge_b64url: str,
) -> dict:
    verification = verify_registration_response(
        credential=credential,
        expected_challenge=b64url_decode(expected_challenge_b64url),
        expected_origin=get_expected_origin(request),
        expected_rp_id=get_rp_id(request),
        require_user_verification=False,
    )

    return {
        "credential_id": b64url_encode(verification.credential_id),
        "public_key": b64url_encode(verification.credential_public_key),
        "sign_count": int(verification.sign_count or 0),
    }


def build_authentication_options(
    *,
    request: Request,
    allow_credential_ids: list[str],
) -> dict:
    rp_id = get_rp_id(request)
    allow_credentials = [
        PublicKeyCredentialDescriptor(id=b64url_decode(cred_id))
        for cred_id in allow_credential_ids
        if cred_id
    ]

    options_kwargs = {
        "rp_id": rp_id,
        "user_verification": UserVerificationRequirement.PREFERRED,
    }
    if allow_credentials:
        options_kwargs["allow_credentials"] = allow_credentials

    options = generate_authentication_options(**options_kwargs)
    return json.loads(options_to_json(options))


def verify_authentication(
    *,
    request: Request,
    credential: dict,
    expected_challenge_b64url: str,
    credential_public_key_b64url: str,
    credential_sign_count: int,
) -> int:
    verification = verify_authentication_response(
        credential=credential,
        expected_challenge=b64url_decode(expected_challenge_b64url),
        expected_origin=get_expected_origin(request),
        expected_rp_id=get_rp_id(request),
        credential_public_key=b64url_decode(credential_public_key_b64url),
        credential_current_sign_count=int(credential_sign_count or 0),
        require_user_verification=False,
    )
    return int(verification.new_sign_count or 0)
