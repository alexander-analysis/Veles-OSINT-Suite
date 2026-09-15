"""Optional API token protection.

Set ``VELES_API_TOKEN`` in ``.env`` and every ``/api/*`` request (except
``/api/health``) must carry it as ``X-API-Key: <token>``,
``Authorization: Bearer <token>`` or ``?access_token=<token>`` (WebSocket).
Unset, the API is open - appropriate only on a trusted network or behind
Cloudflare Access.  The frontend stores the token in the browser and adds
the header itself (Settings page).
"""

import hmac

from fastapi import HTTPException, Request, WebSocket
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.config import settings

PUBLIC_PATHS = {"/api/health"}


def configured_token() -> str:
    return settings.key("VELES_API_TOKEN")


def _presented(request: Request | WebSocket) -> str | None:
    header = request.headers.get("x-api-key")
    if header:
        return header
    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return request.query_params.get("access_token")


def is_authorised(request: Request | WebSocket) -> bool:
    token = configured_token()
    if not token:
        return True
    presented = _presented(request)
    return bool(presented) and hmac.compare_digest(presented, token)


class APITokenMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path.startswith("/api/") and path not in PUBLIC_PATHS and not is_authorised(request):
            return JSONResponse({"detail": "API token required (X-API-Key or Authorization: Bearer)"}, status_code=401)
        return await call_next(request)


async def require_websocket_token(websocket: WebSocket) -> None:
    """Close the socket with 4401 when a token is configured and missing/wrong."""
    if not is_authorised(websocket):
        await websocket.close(code=4401)
        raise HTTPException(status_code=401, detail="API token required")


def auth_status() -> dict[str, bool]:
    return {"token_required": bool(configured_token())}
