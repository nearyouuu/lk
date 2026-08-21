import os
import uuid
import shutil
from typing import Optional
from fastapi import UploadFile, HTTPException
from app.core.config import settings

ALLOWED_IMAGE_CT = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
MAX_BYTES = 5 * 1024 * 1024

def ensure_media_dirs():
    os.makedirs(settings.MEDIA_ROOT, exist_ok=True)
    os.makedirs(os.path.join(settings.MEDIA_ROOT, "avatars"), exist_ok=True)

def _ext_from_upload(file: UploadFile) -> str:
    if file.content_type in ALLOWED_IMAGE_CT:
        return ALLOWED_IMAGE_CT[file.content_type]
    _, ext = os.path.splitext(file.filename or "")
    ext = ext.lower()
    if ext in {".jpg", ".jpeg", ".png", ".webp"}:
        return ".jpg" if ext == ".jpeg" else ext
    raise HTTPException(status_code=400, detail="Unsupported image type")

def save_avatar_file(user_id: int, file: UploadFile) -> str:
    """Сохраняет файл аватара и возвращает относительный путь (от MEDIA_ROOT), напр. 'avatars/123/5c2... .png'."""
    ensure_media_dirs()

    tmp_dir = os.path.join(settings.MEDIA_ROOT, "tmp")
    os.makedirs(tmp_dir, exist_ok=True)
    tmp_path = os.path.join(tmp_dir, f"{uuid.uuid4().hex}.upload")
    total = 0
    with open(tmp_path, "wb") as out:
        while True:
            chunk = file.file.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_BYTES:
                out.close()
                os.remove(tmp_path)
                raise HTTPException(status_code=413, detail="Avatar too large (limit 5 MB)")
            out.write(chunk)

    ext = _ext_from_upload(file)
    dest_dir = os.path.join(settings.MEDIA_ROOT, "avatars", str(user_id))
    os.makedirs(dest_dir, exist_ok=True)
    dest_name = f"{uuid.uuid4().hex}{ext}"
    dest_path = os.path.join(dest_dir, dest_name)

    shutil.move(tmp_path, dest_path)

    rel_path = os.path.relpath(dest_path, settings.MEDIA_ROOT).replace("\\", "/")
    return rel_path

def delete_file_if_local(rel_path: Optional[str]):
    """Удаляет предыдущий файл, если он внутри MEDIA_ROOT."""
    if not rel_path:
        return
    abs_path = os.path.join(settings.MEDIA_ROOT, rel_path.replace("/", os.sep))
    try:
        if os.path.commonpath([settings.MEDIA_ROOT, os.path.abspath(abs_path)]) != os.path.abspath(settings.MEDIA_ROOT):
            return
    except Exception:
        return
    if os.path.exists(abs_path) and os.path.isfile(abs_path):
        try:
            os.remove(abs_path)
        except Exception:
            pass
