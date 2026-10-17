import hmac

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse


class BearerKeyMiddleware(BaseHTTPMiddleware):
    """Service-to-service auth: require `Authorization: Bearer <key>` on every request
    except `public_paths` (e.g. an A2A Agent Card, which is meant to be discoverable)."""

    def __init__(self, app, key: str, public_paths: frozenset[str] = frozenset()):
        super().__init__(app)
        self._key = key
        self._public = public_paths

    async def dispatch(self, request, call_next):
        if request.url.path in self._public:
            return await call_next(request)
        token = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
        # Constant-time comparison so the key can't be guessed via response timing.
        if not hmac.compare_digest(token, self._key):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return await call_next(request)
