from datetime import datetime, timezone
from starlette.middleware.base import BaseHTTPMiddleware
from app.db.session import SessionLocal
from app.models.audit import AuditLog
from app.models.user import User
from app.core.security import decode_token

class AuditMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        user_id = None
        try:
            auth = request.headers.get("authorization")
            if auth and auth.startswith("Bearer "):
                token = auth.split(" ", 1)[1]
                payload = decode_token(token, expected_type="access")
                subject = payload.get("sub")
                if subject:
                    with SessionLocal() as db:
                        u = db.get(User, int(subject))
                        user_id = u.id if u else None
        except Exception:
            user_id = None

        response = await call_next(request)

        try:
            with SessionLocal() as db:
                db.add(AuditLog(
                    user_id=user_id,
                    method=request.method,
                    path=request.url.path,
                    query=request.url.query[:1024] if request.url.query else None,
                    status_code=response.status_code,
                    ip=(request.client.host if request.client else None),
                    user_agent=(request.headers.get("user-agent") or "")[:255],
                    created_at=datetime.now(timezone.utc),
                ))
                db.commit()
        except Exception:
            pass

        return response
