from __future__ import annotations

import base64
import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from app.core.config import settings

FEATURES_BY_TARIFF: dict[str, list[str]] = {
    "basic": [
        "admin_roles",
        "schedule",
        "grades",
        "attendance",
    ],
    "standard": [
        "admin_roles",
        "schedule",
        "grades",
        "attendance",
        "portfolio",
        "user_page",
        "applications",
        "materials",
        "tests",
    ],
    "premium": [
        "admin_roles",
        "schedule",
        "grades",
        "attendance",
        "portfolio",
        "user_page",
        "applications",
        "materials",
        "tests",
        "domain_email",
        "customization",
    ],
}

FEATURE_LABELS: dict[str, str] = {
    "admin_roles": "Админ-панель + система ролей",
    "schedule": "Расписание занятий",
    "grades": "Ведомости",
    "attendance": "Журнал посещаемости",
    "portfolio": "Портфолио",
    "user_page": "Страница пользователя",
    "applications": "Подача заявлений / заказ справок",
    "materials": "Система размещения учебных материалов с привязкой к группе и предмету",
    "tests": "Система электронных тестов",
    "domain_email": "Доменная электронная почта",
    "customization": "Доработка существующего функционала под нужды уч. заведения",
}


@dataclass
class LicenseStatus:
    valid: bool
    reason: str | None
    fingerprint: str
    product: str
    file_path: str
    payload: dict | None


def get_tariff_features() -> dict[str, list[str]]:
    return FEATURES_BY_TARIFF


def get_feature_labels() -> dict[str, str]:
    return FEATURE_LABELS


def resolve_features(tariff: str, additional_features: list[str] | None = None) -> list[str]:
    base = FEATURES_BY_TARIFF.get(tariff, [])
    merged = list(dict.fromkeys([*base, *(additional_features or [])]))
    return merged


def has_feature(feature: str) -> tuple[bool, str | None]:
    status = read_license_status()
    if not status.valid:
        return False, status.reason or "License is invalid"

    payload = status.payload or {}
    features = payload.get("features") or []
    if feature not in features:
        tariff = payload.get("tariff", "unknown")
        return False, f"Feature '{feature}' is not available for tariff '{tariff}'"

    return True, None


def get_machine_fingerprint() -> str:
    machine_id = os.getenv("LICENSE_MACHINE_ID", "").strip()
    if not machine_id:
        try:
            with open(settings.LICENSE_MACHINE_ID_PATH, "r", encoding="utf-8") as f:
                machine_id = f.read().strip()
        except OSError:
            machine_id = ""

    if not machine_id:
        raise RuntimeError(
            "Stable machine id is unavailable. Set LICENSE_MACHINE_ID or mount "
            "the host /etc/machine-id and set LICENSE_MACHINE_ID_PATH."
        )

    raw = "|".join([settings.LICENSE_PRODUCT, machine_id, settings.LICENSE_FINGERPRINT_SALT])
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _canonical_json(payload: dict) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _load_public_key() -> Ed25519PublicKey:
    if not os.path.exists(settings.LICENSE_PUBLIC_KEY_PATH):
        raise FileNotFoundError(f"License public key not found: {settings.LICENSE_PUBLIC_KEY_PATH}")

    with open(settings.LICENSE_PUBLIC_KEY_PATH, "rb") as f:
        pem = f.read()

    key = serialization.load_pem_public_key(pem)
    if not isinstance(key, Ed25519PublicKey):
        raise ValueError("Only Ed25519 public keys are supported for license verification")
    return key


def _parse_utc(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    dt = datetime.fromisoformat(normalized)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def read_license_status() -> LicenseStatus:
    try:
        fingerprint = get_machine_fingerprint()
    except RuntimeError as exc:
        return LicenseStatus(
            valid=False,
            reason=str(exc),
            fingerprint="unavailable",
            product=settings.LICENSE_PRODUCT,
            file_path=settings.LICENSE_FILE_PATH,
            payload=None,
        )
    file_path = settings.LICENSE_FILE_PATH

    if not os.path.exists(file_path):
        return LicenseStatus(
            valid=False,
            reason="License file not found",
            fingerprint=fingerprint,
            product=settings.LICENSE_PRODUCT,
            file_path=file_path,
            payload=None,
        )

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:
        return LicenseStatus(
            valid=False,
            reason=f"License file is not valid JSON: {exc}",
            fingerprint=fingerprint,
            product=settings.LICENSE_PRODUCT,
            file_path=file_path,
            payload=None,
        )

    payload = data.get("payload")
    signature_b64 = data.get("signature")
    if not isinstance(payload, dict) or not isinstance(signature_b64, str):
        return LicenseStatus(
            valid=False,
            reason="License file must contain 'payload' object and 'signature' string",
            fingerprint=fingerprint,
            product=settings.LICENSE_PRODUCT,
            file_path=file_path,
            payload=None,
        )

    try:
        signature = base64.b64decode(signature_b64)
        public_key = _load_public_key()
        public_key.verify(signature, _canonical_json(payload))
    except FileNotFoundError as exc:
        return LicenseStatus(False, str(exc), fingerprint, settings.LICENSE_PRODUCT, file_path, payload)
    except (ValueError, InvalidSignature) as exc:
        return LicenseStatus(False, f"License signature is invalid: {exc}", fingerprint, settings.LICENSE_PRODUCT, file_path, payload)
    except Exception as exc:
        return LicenseStatus(False, f"License verification failed: {exc}", fingerprint, settings.LICENSE_PRODUCT, file_path, payload)

    if payload.get("product") != settings.LICENSE_PRODUCT:
        return LicenseStatus(False, "License product mismatch", fingerprint, settings.LICENSE_PRODUCT, file_path, payload)

    issued_at = payload.get("issued_at")
    if not isinstance(issued_at, str):
        return LicenseStatus(False, "License issued_at is missing", fingerprint, settings.LICENSE_PRODUCT, file_path, payload)
    try:
        issued_dt = _parse_utc(issued_at)
    except Exception as exc:
        return LicenseStatus(False, f"License issued_at is invalid: {exc}", fingerprint, settings.LICENSE_PRODUCT, file_path, payload)
    if issued_dt > datetime.now(timezone.utc):
        return LicenseStatus(False, "License is not active yet", fingerprint, settings.LICENSE_PRODUCT, file_path, payload)

    tariff = payload.get("tariff")
    if not isinstance(tariff, str) or tariff not in FEATURES_BY_TARIFF:
        return LicenseStatus(False, "License tariff is invalid", fingerprint, settings.LICENSE_PRODUCT, file_path, payload)

    expires_at = payload.get("expires_at")
    if not isinstance(expires_at, str):
        return LicenseStatus(False, "License expires_at is missing", fingerprint, settings.LICENSE_PRODUCT, file_path, payload)

    try:
        expires_dt = _parse_utc(expires_at)
    except Exception as exc:
        return LicenseStatus(False, f"License expires_at is invalid: {exc}", fingerprint, settings.LICENSE_PRODUCT, file_path, payload)

    if datetime.now(timezone.utc) > expires_dt:
        return LicenseStatus(False, "License expired", fingerprint, settings.LICENSE_PRODUCT, file_path, payload)

    licensed_fingerprint = payload.get("hardware_fingerprint")
    if licensed_fingerprint and licensed_fingerprint != fingerprint:
        return LicenseStatus(False, "License is bound to another server", fingerprint, settings.LICENSE_PRODUCT, file_path, payload)

    additional_features = payload.get("additional_features")
    if additional_features is not None and not isinstance(additional_features, list):
        return LicenseStatus(False, "License additional_features must be a list", fingerprint, settings.LICENSE_PRODUCT, file_path, payload)

    payload["features"] = resolve_features(tariff, additional_features)

    return LicenseStatus(
        valid=True,
        reason=None,
        fingerprint=fingerprint,
        product=settings.LICENSE_PRODUCT,
        file_path=file_path,
        payload=payload,
    )
