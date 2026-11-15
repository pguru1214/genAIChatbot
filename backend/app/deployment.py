"""Same-origin static hosting and a private access screen for the personal demo."""
import hashlib
import hmac
import html
import secrets
import time
from collections import OrderedDict, deque
from pathlib import Path
from urllib.parse import parse_qs

from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.staticfiles import StaticFiles

from app.config import get_settings


COOKIE = '__Host-tripweave-access'
LIFETIME = 12 * 60 * 60
_login_attempts = OrderedDict()


def signed_session(settings):
    payload = f'{int(time.time()) + LIFETIME}.{secrets.token_hex(16)}'
    signature = hmac.new(settings.session_signing_key.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return payload + '.' + signature


def valid_session(value, settings):
    try:
        expires, nonce, signature = value.split('.')
        payload = expires + '.' + nonce
        expected = hmac.new(settings.session_signing_key.encode(), payload.encode(), hashlib.sha256).hexdigest()
        return int(expires) > time.time() and hmac.compare_digest(signature, expected)
    except (AttributeError, TypeError, ValueError):
        return False


def login_page(error=''):
    return HTMLResponse('''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,nofollow">
<title>TripWeave · Private demo</title><style>
*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;background:#fbf4e8;color:#153c40;font:16px system-ui,sans-serif;padding:24px}
main{width:100%;max-width:420px;padding:32px;border:1px solid #e6d4bd;border-radius:24px;background:#fffdfa;box-shadow:0 18px 60px #69462718}
h1{font:700 32px Georgia,serif;margin:0 0 12px}p{line-height:1.6;color:#617274}label{display:block;font-weight:600;margin:24px 0 8px}
input,button{width:100%;padding:13px;border-radius:10px;font:inherit}input{border:1px solid #cfbda6}button{border:0;background:#c95732;color:white;cursor:pointer;margin-top:16px}
.error{color:#a73824;font-size:14px}small{display:block;line-height:1.6;margin-top:22px;color:#74807d}
</style></head><body><main><h1>TripWeave</h1><p>A private travel-planning demo. Enter the access password to explore India.</p>
<form method="post" action="/access"><label for="password">Access password</label><input id="password" name="password" type="password" required maxlength="200" autocomplete="current-password" autofocus>
<p class="error" role="alert">''' + html.escape(error) + '''</p><button type="submit">Open TripWeave</button></form>
<small>Free hosting may take about a minute to wake up. Demo data is temporary; API quotas apply.</small></main></body></html>''')


def login_allowed(client):
    now = time.monotonic()
    entries = _login_attempts.setdefault(client, deque())
    _login_attempts.move_to_end(client)
    while len(_login_attempts) > 1000:
        _login_attempts.popitem(last=False)
    while entries and now - entries[0] > 60:
        entries.popleft()
    if len(entries) >= 5:
        return False
    entries.append(now)
    return True


def configure_deployment(app):
    @app.middleware('http')
    async def private_demo_access(request: Request, call_next):
        settings = get_settings()
        if settings.public_deployment:
            # Fail closed even during startup/configuration mistakes.
            if len(settings.deployment_access_password) < 8 or len(settings.session_signing_key) < 32:
                return JSONResponse({'detail': 'Demo access is not configured.'}, status_code=503)
            path = request.url.path
            origin = request.headers.get('origin')
            expected_origin = str(request.base_url).rstrip('/')
            if request.method not in {'GET', 'HEAD', 'OPTIONS'} and origin and origin != expected_origin:
                return JSONResponse({'detail': 'Cross-site requests are not allowed.'}, status_code=403)
            if request.headers.get('content-length', '').isdigit() and int(request.headers['content-length']) > 65536:
                return JSONResponse({'detail': 'Request too large.'}, status_code=413)
            if path == '/access' and request.method == 'POST':
                client = request.client.host if request.client else 'unknown'
                if not login_allowed(client):
                    return JSONResponse({'detail': 'Too many login attempts. Wait one minute.'}, status_code=429,
                                        headers={'Retry-After': '60'})
                raw = await request.body()
                if len(raw) > 2048:
                    return JSONResponse({'detail': 'Request too large.'}, status_code=413)
                password = parse_qs(raw.decode('utf-8', errors='replace')).get('password', [''])[0]
                if not hmac.compare_digest(password.encode(), settings.deployment_access_password.encode()):
                    response = login_page('Incorrect password. Please try again.')
                    response.status_code = 401
                else:
                    response = RedirectResponse('/', status_code=303)
                    response.set_cookie(COOKIE, signed_session(settings), max_age=LIFETIME,
                        secure=True, httponly=True, samesite='strict', path='/')
            elif path != '/api/health' and not valid_session(request.cookies.get(COOKIE), settings):
                response = (JSONResponse({'detail': 'Sign in on the home page to access this private demo.'}, status_code=401)
                            if path.startswith('/api/') else login_page())
            else:
                response = await call_next(request)
            response.headers['Cache-Control'] = 'no-store'
            response.headers['X-Robots-Tag'] = 'noindex, nofollow'
            response.headers['X-Content-Type-Options'] = 'nosniff'
            response.headers['X-Frame-Options'] = 'DENY'
            response.headers['Referrer-Policy'] = 'same-origin'
            return response
        return await call_next(request)

    static = get_settings().frontend_dist
    if static:
        root = Path(static).resolve()
        if not (root / 'index.html').is_file():
            raise RuntimeError('FRONTEND_DIST must contain the built frontend index.html')
        app.mount('/', StaticFiles(directory=root, html=True), name='frontend')
