from pydantic import BaseModel, Field


class LicensePayloadOut(BaseModel):
    license_id: str
    customer: str
    product: str
    tariff: str
    issued_at: str
    expires_at: str
    features: list[str] = Field(default_factory=list)
    hardware_fingerprint: str | None = None
    max_users: int | None = None
    allowed_domains: list[str] = Field(default_factory=list)


class LicenseStatusOut(BaseModel):
    valid: bool
    reason: str | None = None
    fingerprint: str
    product: str
    file_path: str
    tariff_features: dict[str, list[str]] = Field(default_factory=dict)
    payload: LicensePayloadOut | None = None
