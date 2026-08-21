from __future__ import annotations

from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


ROOT = Path(__file__).resolve().parent.parent
PRIVATE_KEY_PATH = ROOT / "license_private.pem"
PUBLIC_KEY_PATH = ROOT / "license_public.pem"


def main() -> None:
    if PRIVATE_KEY_PATH.exists() or PUBLIC_KEY_PATH.exists():
        raise SystemExit(
            "license_private.pem or license_public.pem already exists. "
            "Move them away first if you want to regenerate keys."
        )

    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()

    PRIVATE_KEY_PATH.write_bytes(
        private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )

    PUBLIC_KEY_PATH.write_bytes(
        public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )

    print(f"Created: {PRIVATE_KEY_PATH}")
    print(f"Created: {PUBLIC_KEY_PATH}")
    print("Keep license_private.pem only on your side. Never ship it to the client.")


if __name__ == "__main__":
    main()
