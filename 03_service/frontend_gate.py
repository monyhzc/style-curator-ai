# frontend_gate.py (A: ASGI)
import asyncio
import hashlib
import hmac
import os
import time
from pathlib import Path
from urllib.parse import parse_qs

TOKEN = os.environ.get("APP_AUTH_TOKEN", "")
if not TOKEN:
    try:
        from dotenv import load_dotenv
        _env = Path(__file__).resolve().parent.parent / ".env"
        if _env.exists():
            load_dotenv(_env)
        TOKEN = os.environ.get("APP_AUTH_TOKEN", "")
    except Exception:
        pass

if not TOKEN:
    raise RuntimeError("没有设置环境变量 APP_AUTH_TOKEN")

PAGES = Path(__file__).resolve().parent / "frontend"
INDEX_HTML = (PAGES / "index.html").read_bytes()
LOGIN_HTML = (PAGES / "login.html").read_bytes()
if b"{%" in LOGIN_HTML:
    raise RuntimeError("login.html 还没按第 2 步修改")

COOKIE = "gs_session"
SESSION_SECONDS = 8 * 3600


def _sign(expires):
    return hmac.new(TOKEN.encode(), ("session:" + expires).encode(), hashlib.sha256).hexdigest()


def new_session():
    expires = str(int(time.time()) + SESSION_SECONDS)
    return expires + "." + _sign(expires)


def session_ok(cookie_header):
    for part in cookie_header.split(";"):
        name, _, value = part.strip().partition("=")
        if name != COOKIE:
            continue
        expires, _, signature = value.partition(".")
        if not (expires.isascii() and expires.isdigit() and len(expires) < 12):
            continue
        if hmac.compare_digest(signature.encode(), _sign(expires).encode()) and int(expires) > time.time():
            return True
    return False


def is_protected(path):
    return path.startswith(("/api/", "/action/", "/image/")) or path == "/undo_global"


class FrontendGate:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        path, root = scope["path"], scope.get("root_path", "")
        if root and path.startswith(root):
            path = path[len(root):] or "/"
        method = scope["method"]
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        logged_in = session_ok(headers.get("cookie", ""))

        if path == "/" and method in ("GET", "HEAD"):
            if logged_in:
                return await self._reply(send, 200, INDEX_HTML)
            return await self._redirect(send, "login")
        if path == "/login" and method in ("GET", "HEAD"):
            return await self._reply(send, 200, LOGIN_HTML)
        if path == "/login" and method == "POST":
            return await self._login(receive, send)
        if path == "/logout":
            return await self._redirect(send, "login", COOKIE + "=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax")

        if is_protected(path) and "authorization" not in headers:
            if not logged_in:
                return await self._reply(send, 401, b'{"error": "Unauthorized"}', "application/json")
            scope = dict(scope)
            scope["headers"] = list(scope["headers"]) + [(b"authorization", ("Bearer " + TOKEN).encode())]
        await self.app(scope, receive, send)

    async def _login(self, receive, send):
        body = b""
        while True:
            message = await receive()
            if message["type"] != "http.request":
                return
            body += message.get("body", b"")
            if len(body) > 4096 or not message.get("more_body"):
                break
        password = parse_qs(body.decode("utf-8", "replace")).get("password", [""])[0]
        if hmac.compare_digest(password.encode(), TOKEN.encode()):
            cookie = "%s=%s; Path=/; Max-Age=%d; HttpOnly; SameSite=Lax" % (COOKIE, new_session(), SESSION_SECONDS)
            return await self._redirect(send, "./", cookie)
        await asyncio.sleep(1)
        await self._redirect(send, "login?error=wrong")

    async def _redirect(self, send, location, cookie=None):
        extra = [(b"location", location.encode())]
        if cookie:
            extra.append((b"set-cookie", cookie.encode()))
        await self._reply(send, 303, b"", extra=extra)

    async def _reply(self, send, status, body, content_type="text/html; charset=utf-8", extra=()):
        await send({"type": "http.response.start", "status": status, "headers": [
            (b"content-type", content_type.encode()),
            (b"content-length", str(len(body)).encode()),
            (b"cache-control", b"no-store"),
            *extra,
        ]})
        await send({"type": "http.response.body", "body": body})
