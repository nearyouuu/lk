from fastapi import APIRouter, HTTPException

from app.schemas.license import LicensePayloadOut, LicenseStatusOut
from app.services.license_service import get_machine_fingerprint, get_tariff_features, read_license_status

router = APIRouter(prefix="/license", tags=["license"])


@router.get("/fingerprint", response_model=dict[str, str])
def get_license_fingerprint():
    try:
        return {"fingerprint": get_machine_fingerprint()}
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/status", response_model=LicenseStatusOut)
def get_license_status():
    status = read_license_status()
    payload = LicensePayloadOut(**status.payload) if status.payload else None
    return LicenseStatusOut(
        valid=status.valid,
        reason=status.reason,
        fingerprint=status.fingerprint,
        product=status.product,
        file_path=status.file_path,
        tariff_features=get_tariff_features(),
        payload=payload,
    )
