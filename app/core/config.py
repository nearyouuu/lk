import os
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = os.path.dirname(BASE_DIR)

class Settings(BaseModel):
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg2://cabinet:cabinet@localhost:5432/cabinet"
    )
    JWT_SECRET: str = os.getenv("JWT_SECRET", "devsecret")
    JWT_ALG: str = os.getenv("JWT_ALG", "HS256")
    ACCESS_TOKEN_EXPIRES_MIN: int = int(os.getenv("ACCESS_TOKEN_EXPIRES_MIN", "15"))
    REFRESH_TOKEN_EXPIRES_DAYS: int = int(os.getenv("REFRESH_TOKEN_EXPIRES_DAYS", "30"))
    EXPORT_LINK_SECRET: str = os.getenv(
        "EXPORT_LINK_SECRET",
        os.getenv("JWT_SECRET", "devsecret"),
    )

    MEDIA_ROOT: str = os.getenv("MEDIA_ROOT", os.path.join(BASE_DIR, "media"))
    MEDIA_URL: str = os.getenv("MEDIA_URL", "/media/")
    LICENSE_PRODUCT: str = os.getenv("LICENSE_PRODUCT", "lk")
    LICENSE_FILE_PATH: str = os.getenv("LICENSE_FILE_PATH", os.path.join(PROJECT_ROOT, "license.lic"))
    LICENSE_PUBLIC_KEY_PATH: str = os.getenv("LICENSE_PUBLIC_KEY_PATH", os.path.join(PROJECT_ROOT, "license_public.pem"))
    LICENSE_FINGERPRINT_SALT: str = os.getenv("LICENSE_FINGERPRINT_SALT", "lk-license-salt")
    # In Docker mount the host's /etc/machine-id read-only to this path.
    LICENSE_MACHINE_ID_PATH: str = os.getenv("LICENSE_MACHINE_ID_PATH", "/etc/machine-id")

settings = Settings()
