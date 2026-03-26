import json
import logging
from datetime import datetime, timezone
from typing import Any

from bson import ObjectId

from app.db.mongo import db
from app.services.admin_settings import get_admin_settings

logger = logging.getLogger(__name__)

try:
    from pywebpush import webpush, WebPushException  # type: ignore
except Exception:  # pragma: no cover
    webpush = None
    WebPushException = Exception

try:
    import firebase_admin  # type: ignore
    from firebase_admin import credentials, messaging  # type: ignore
except Exception:  # pragma: no cover
    firebase_admin = None
    credentials = None
    messaging = None

_firebase_app_cache: dict[str, Any] = {}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_subscription(subscription: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(subscription, dict):
        return None
    endpoint = str(subscription.get("endpoint") or "").strip()
    keys = subscription.get("keys") or {}
    p256dh = str((keys or {}).get("p256dh") or "").strip()
    auth = str((keys or {}).get("auth") or "").strip()
    if not endpoint or not p256dh or not auth:
        return None
    return {
        "endpoint": endpoint,
        "keys": {"p256dh": p256dh, "auth": auth},
    }


def _sanitize_firebase_public(firebase_cfg: dict[str, Any]) -> dict[str, str]:
    return {
        "apiKey": str(firebase_cfg.get("apiKey") or "").strip(),
        "authDomain": str(firebase_cfg.get("authDomain") or "").strip(),
        "projectId": str(firebase_cfg.get("projectId") or "").strip(),
        "storageBucket": str(firebase_cfg.get("storageBucket") or "").strip(),
        "messagingSenderId": str(firebase_cfg.get("messagingSenderId") or "").strip(),
        "appId": str(firebase_cfg.get("appId") or "").strip(),
        "measurementId": str(firebase_cfg.get("measurementId") or "").strip(),
    }


def _is_firebase_public_config_valid(firebase_public: dict[str, str]) -> bool:
    required = ["apiKey", "projectId", "messagingSenderId", "appId"]
    return all(bool(firebase_public.get(k)) for k in required)


async def get_push_public_config() -> dict[str, Any]:
    cfg = await get_admin_settings()
    push_cfg = (cfg.get("push_notifications") or {}) if isinstance(cfg, dict) else {}
    enabled = bool(push_cfg.get("enabled"))
    public_key = str(push_cfg.get("vapid_public_key") or "").strip()
    firebase_cfg = dict(push_cfg.get("firebase_config") or {})
    firebase_public = _sanitize_firebase_public(firebase_cfg)
    runtime_enabled = bool(enabled and _is_firebase_public_config_valid(firebase_public) and public_key)

    return {
        "enabled": runtime_enabled,
        "provider": "firebase",
        "vapid_public_key": public_key,
        "firebase_config": firebase_public,
        "library_ready": firebase_admin is not None and messaging is not None,
    }


async def save_push_subscription(
    *,
    user_id: ObjectId | str,
    subscription: dict[str, Any],
    user_agent: str = "",
) -> bool:
    normalized = _normalize_subscription(subscription)
    if not normalized:
        return False
    uid = ObjectId(user_id) if not isinstance(user_id, ObjectId) else user_id
    now = _now()
    await db.push_subscriptions.update_one(
        {"endpoint": normalized["endpoint"]},
        {
            "$set": {
                "user_id": uid,
                "provider": "webpush",
                "endpoint": normalized["endpoint"],
                "subscription": normalized,
                "is_active": True,
                "updated_at": now,
                "last_error": None,
                "user_agent": user_agent[:300],
            },
            "$setOnInsert": {"created_at": now},
        },
        upsert=True,
    )
    return True


async def save_fcm_token(
    *,
    user_id: ObjectId | str,
    token: str,
    user_agent: str = "",
) -> bool:
    fcm_token = str(token or "").strip()
    if not fcm_token:
        return False
    uid = ObjectId(user_id) if not isinstance(user_id, ObjectId) else user_id
    now = _now()
    await db.push_subscriptions.update_one(
        {"fcm_token": fcm_token},
        {
            "$set": {
                "user_id": uid,
                "provider": "firebase",
                "fcm_token": fcm_token,
                "is_active": True,
                "updated_at": now,
                "last_error": None,
                "user_agent": user_agent[:300],
            },
            "$setOnInsert": {"created_at": now},
        },
        upsert=True,
    )
    return True


async def deactivate_push_subscription(
    *,
    user_id: ObjectId | str,
    endpoint: str,
) -> None:
    uid = ObjectId(user_id) if not isinstance(user_id, ObjectId) else user_id
    await db.push_subscriptions.update_one(
        {"user_id": uid, "endpoint": str(endpoint or "").strip()},
        {
            "$set": {
                "is_active": False,
                "updated_at": _now(),
            }
        },
    )


async def deactivate_fcm_token(
    *,
    user_id: ObjectId | str,
    token: str,
) -> None:
    uid = ObjectId(user_id) if not isinstance(user_id, ObjectId) else user_id
    await db.push_subscriptions.update_one(
        {"user_id": uid, "fcm_token": str(token or "").strip()},
        {
            "$set": {
                "is_active": False,
                "updated_at": _now(),
            }
        },
    )


def _get_firebase_app(service_account_json: str) -> Any:
    if firebase_admin is None or credentials is None:
        return None
    raw = str(service_account_json or "").strip()
    if not raw:
        return None
    cache_key = str(hash(raw))
    if cache_key in _firebase_app_cache:
        return _firebase_app_cache[cache_key]

    info = json.loads(raw)
    app_name = f"ft-fcm-{cache_key}"
    cred = credentials.Certificate(info)
    app = firebase_admin.initialize_app(cred, name=app_name)
    _firebase_app_cache[cache_key] = app
    return app


async def _send_via_webpush(
    *,
    user_id: ObjectId,
    key: str,
    notif_type: str,
    title: str,
    message: str,
) -> dict[str, Any]:
    if webpush is None:
        return {
            "status": "failed",
            "sent": 0,
            "failed": 0,
            "error": "pywebpush_not_installed",
        }

    cfg = await get_admin_settings()
    push_cfg = (cfg.get("push_notifications") or {}) if isinstance(cfg, dict) else {}
    app_cfg = (cfg.get("application") or {}) if isinstance(cfg, dict) else {}
    vapid_private_key = str(push_cfg.get("vapid_private_key") or "").strip()
    if not vapid_private_key:
        return {
            "status": "skipped_disabled",
            "sent": 0,
            "failed": 0,
            "error": "missing_vapid_private_key",
        }

    support_email = str(app_cfg.get("support_email") or "support@example.com").strip() or "support@example.com"
    vapid_claims = {"sub": f"mailto:{support_email}"}

    cursor = db.push_subscriptions.find(
        {"user_id": user_id, "is_active": True, "provider": "webpush"},
        {"endpoint": 1, "subscription": 1},
    )
    subscriptions = [row async for row in cursor]
    if not subscriptions:
        return {
            "status": "skipped_no_subscription",
            "sent": 0,
            "failed": 0,
            "error": "no_active_subscription",
        }

    sent = 0
    failed = 0
    last_error = None
    payload = {
        "title": title,
        "body": message,
        "tag": f"ft:{key}",
        "data": {
            "url": "/",
            "key": key,
            "type": notif_type,
        },
    }

    for row in subscriptions:
        endpoint = str(row.get("endpoint") or "")
        subscription = row.get("subscription") or {}
        try:
            webpush(
                subscription_info=subscription,
                data=json.dumps(payload),
                vapid_private_key=vapid_private_key,
                vapid_claims=vapid_claims,
                ttl=120,
            )
            sent += 1
            await db.push_subscriptions.update_one(
                {"endpoint": endpoint},
                {"$set": {"last_sent_at": _now(), "last_error": None, "updated_at": _now()}},
            )
        except WebPushException as exc:
            failed += 1
            last_error = str(exc)
            status_code = getattr(getattr(exc, "response", None), "status_code", None)
            should_disable = status_code in (404, 410)
            await db.push_subscriptions.update_one(
                {"endpoint": endpoint},
                {
                    "$set": {
                        "last_error": last_error[:500],
                        "updated_at": _now(),
                        "is_active": False if should_disable else True,
                    }
                },
            )
            logger.warning("Web push failed for endpoint=%s status=%s: %s", endpoint, status_code, exc)
        except Exception as exc:  # pragma: no cover
            failed += 1
            last_error = str(exc)
            await db.push_subscriptions.update_one(
                {"endpoint": endpoint},
                {"$set": {"last_error": last_error[:500], "updated_at": _now()}},
            )
            logger.warning("Web push error for endpoint=%s: %s", endpoint, exc)

    return {
        "status": "sent" if sent > 0 else "failed",
        "sent": sent,
        "failed": failed,
        "error": last_error,
    }


async def _send_via_fcm(
    *,
    user_id: ObjectId,
    key: str,
    notif_type: str,
    title: str,
    message: str,
) -> dict[str, Any]:
    if firebase_admin is None or messaging is None:
        return {
            "status": "failed",
            "sent": 0,
            "failed": 0,
            "error": "firebase_admin_not_installed",
        }

    cfg = await get_admin_settings()
    push_cfg = (cfg.get("push_notifications") or {}) if isinstance(cfg, dict) else {}
    service_account_json = str(push_cfg.get("firebase_service_account_json") or "").strip()
    if not service_account_json:
        return {
            "status": "failed",
            "sent": 0,
            "failed": 0,
            "error": "missing_firebase_service_account_json",
        }

    try:
        app = _get_firebase_app(service_account_json)
    except Exception as exc:
        return {
            "status": "failed",
            "sent": 0,
            "failed": 0,
            "error": f"firebase_init_failed:{exc}",
        }

    cursor = db.push_subscriptions.find(
        {"user_id": user_id, "is_active": True, "provider": "firebase", "fcm_token": {"$exists": True, "$ne": ""}},
        {"fcm_token": 1},
    )
    rows = [row async for row in cursor]
    tokens = [str(r.get("fcm_token") or "").strip() for r in rows if str(r.get("fcm_token") or "").strip()]
    if not tokens:
        return {
            "status": "skipped_no_subscription",
            "sent": 0,
            "failed": 0,
            "error": "no_active_fcm_token",
        }

    try:
        multicast = messaging.MulticastMessage(
            tokens=tokens,
            notification=messaging.Notification(title=title, body=message),
            data={"url": "/", "key": key, "type": notif_type},
        )
        response = messaging.send_each_for_multicast(multicast, app=app)
    except Exception as exc:
        return {
            "status": "failed",
            "sent": 0,
            "failed": len(tokens),
            "error": f"fcm_send_failed:{exc}",
        }

    sent = int(response.success_count)
    failed = int(response.failure_count)
    last_error = None

    for idx, resp in enumerate(response.responses):
        token = tokens[idx]
        if resp.success:
            await db.push_subscriptions.update_one(
                {"fcm_token": token},
                {"$set": {"last_sent_at": _now(), "last_error": None, "updated_at": _now()}},
            )
            continue

        err_msg = str(resp.exception)
        last_error = err_msg
        deactivate = "unregistered" in err_msg.lower() or "invalid" in err_msg.lower()
        await db.push_subscriptions.update_one(
            {"fcm_token": token},
            {
                "$set": {
                    "last_error": err_msg[:500],
                    "updated_at": _now(),
                    "is_active": False if deactivate else True,
                }
            },
        )

    return {
        "status": "sent" if sent > 0 else "failed",
        "sent": sent,
        "failed": failed,
        "error": last_error,
    }


async def send_push_notification_alert(
    *,
    user_id: ObjectId,
    key: str,
    notif_type: str,
    title: str,
    message: str,
) -> dict[str, Any]:
    config = await get_push_public_config()
    if not config.get("enabled"):
        return {
            "status": "skipped_disabled",
            "sent": 0,
            "failed": 0,
            "error": "push_disabled_or_unconfigured",
        }

    return await _send_via_fcm(
        user_id=user_id,
        key=key,
        notif_type=notif_type,
        title=title,
        message=message,
    )
