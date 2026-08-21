from __future__ import annotations

import json

from starlette.datastructures import Headers
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.services.license_service import read_license_status


class LicenseMiddleware:
    """Block the entire product when the locally signed license is not valid."""

    def __init__(self, app: ASGIApp, exempt_paths: tuple[str, ...] = ()) -> None:
        self.app = app
        self.exempt_paths = exempt_paths

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if any(path == item or path.startswith(f"{item}/") for item in self.exempt_paths):
            await self.app(scope, receive, send)
            return

        status = read_license_status()
        if status.valid:
            await self.app(scope, receive, send)
            return

        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 4402, "reason": status.reason or "License invalid"})
            return

        body = json.dumps(
            {"detail": "License is not active", "reason": status.reason},
            ensure_ascii=False,
        ).encode("utf-8")
        headers = Headers(
            {
                "content-type": "application/json; charset=utf-8",
                "content-length": str(len(body)),
                "cache-control": "no-store",
            }
        ).raw
        await send({"type": "http.response.start", "status": 402, "headers": headers})
        await send({"type": "http.response.body", "body": body})
