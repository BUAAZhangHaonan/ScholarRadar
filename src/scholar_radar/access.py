import hashlib
import hmac
import secrets
import time

from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from .db import database
from .settings import deployment


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def token_for(expiry):
    secret = deployment()["site_token"].encode()
    return hmac.new(secret, str(expiry).encode(), hashlib.sha256).hexdigest()


def issue_link(days=3):
    token = secrets.token_urlsafe(28)
    with database(write=True) as db:
        db.execute(
            "INSERT INTO login_links VALUES(?,?,0)",
            (digest(token), int(time.time()) + days * 86400),
        )
    cfg = deployment()
    return f"http://{cfg['bind_host']}:{cfg['port']}/login#" + token


def authorized(cookie):
    try:
        exp, tag = (cookie or "").split(".")
        return int(exp) > time.time() and hmac.compare_digest(tag, token_for(exp))
    except (ValueError, TypeError):
        return False


def install(app):
    @app.middleware("http")
    async def private(request: Request, call_next):
        path = request.url.path
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            if origin and origin != str(request.base_url).rstrip("/"):
                return JSONResponse({"detail": "请求来源无效"}, status_code=403)
        if path not in {"/login", "/health", "/static/site.css"} and not authorized(
            request.cookies.get("radar_session")
        ):
            if path.startswith("/api/"):
                return JSONResponse({"detail": "请先登录"}, status_code=401)
            return RedirectResponse("/login", status_code=303)
        response = await call_next(request)
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Cache-Control"] = (
            "private, no-store"
            if not path.startswith("/static/")
            else "private, max-age=300"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.get("/login", response_class=HTMLResponse)
    def login_page():
        from .settings import ROOT

        return (ROOT / "web/login.html").read_text()

    @app.post("/login")
    async def login(request: Request):
        form = await request.form()
        value = str(form.get("token") or "")
        if not value or len(value) > 128:
            return HTMLResponse("访问码无效", 403)
        with database(write=True) as db:
            ok = db.execute(
                "UPDATE login_links SET used=1 WHERE digest=? AND used=0 AND expires_at>?",
                (digest(value), int(time.time())),
            ).rowcount
        if not ok:
            return HTMLResponse(
                "访问链接已使用或已过期，请从已登录的浏览器访问，或生成新链接。", 403
            )
        exp = int(time.time()) + 30 * 86400
        response = RedirectResponse("/", 303)
        response.set_cookie(
            "radar_session",
            str(exp) + "." + token_for(exp),
            httponly=True,
            samesite="strict",
            max_age=30 * 86400,
            secure=request.url.scheme == "https",
        )
        return response
