from __future__ import annotations

import argparse
import base64
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PRIVATE_KEY = ROOT / "license_private.pem"
FEATURES_BY_TARIFF = {
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


def canonical_json(payload: dict) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Issue signed license.lic for the lk project.")
    parser.add_argument("--customer", required=True, help="Customer name")
    parser.add_argument("--fingerprint", required=True, help="Server fingerprint from /license/fingerprint")
    parser.add_argument("--expires-at", help="UTC ISO date like 2027-06-24T12:00:00Z")
    parser.add_argument("--days", type=int, default=365, help="License duration in days if --expires-at is omitted")
    parser.add_argument("--license-id", required=True, help="Unique license id, e.g. LIC-2026-000001")
    parser.add_argument("--product", default="lk", help="Product code")
    parser.add_argument("--tariff", choices=["basic", "standard", "premium"], required=True, help="License tariff")
    parser.add_argument("--max-users", type=int, default=500, help="Optional max users limit")
    parser.add_argument("--feature", action="append", dest="features", default=[], help="Additional feature outside tariff; may be passed multiple times")
    parser.add_argument("--domain", action="append", dest="domains", default=[], help="Allowed domain; may be passed multiple times")
    parser.add_argument("--private-key", default=str(DEFAULT_PRIVATE_KEY), help="Path to license_private.pem")
    parser.add_argument("--output", default=str(ROOT / "license.lic"), help="Output path for signed license")
    return parser.parse_args()


def load_private_key(path: Path) -> Ed25519PrivateKey:
    pem = path.read_bytes()
    key = serialization.load_pem_private_key(pem, password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise SystemExit("Only Ed25519 private keys are supported")
    return key


def resolve_expiry(args: argparse.Namespace) -> str:
    if args.expires_at:
        return args.expires_at
    expires_dt = datetime.now(timezone.utc) + timedelta(days=args.days)
    return expires_dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def main() -> None:
    args = parse_args()

    private_key_path = Path(args.private_key).resolve()
    output_path = Path(args.output).resolve()
    private_key = load_private_key(private_key_path)

    payload = {
        "license_id": args.license_id,
        "customer": args.customer,
        "product": args.product,
        "tariff": args.tariff,
        "issued_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "expires_at": resolve_expiry(args),
        "hardware_fingerprint": args.fingerprint,
        "max_users": args.max_users,
        "allowed_domains": args.domains,
    }
    if args.features:
        payload["additional_features"] = args.features
    payload["features"] = list(dict.fromkeys([*FEATURES_BY_TARIFF[args.tariff], *args.features]))

    signature = private_key.sign(canonical_json(payload))
    license_doc = {
        "payload": payload,
        "signature": base64.b64encode(signature).decode("ascii"),
    }

    output_path.write_text(json.dumps(license_doc, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Created license file: {output_path}")
    print("Ship this file to the client as license.lic")


if __name__ == "__main__":
    main()
