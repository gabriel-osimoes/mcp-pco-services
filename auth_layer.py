"""OAuth 2.1-style authorization-code/PKCE bridge for PCO Personal Access Tokens.

The authorization UI is hosted by this service; it is NOT Planning Center OAuth.
"""
import base64
import contextvars
import hashlib
import html
import json
import os
import secrets
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode, urlsplit

import asyncpg
import httpx
from cryptography.fernet import Fernet
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse

current_pat = contextvars.ContextVar('pco_pat', default=None)


def env(name):
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f'Missing required environment variable: {name}')
    return value


def issuer():
    return env('PUBLIC_URL').rstrip('/')


def cipher():
    return Fernet(env('TOKEN_ENCRYPTION_KEY').encode())


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def utcnow():
    return datetime.now(timezone.utc)


async def db():
    connection = await asyncpg.connect(env('DATABASE_URL'))
    return connection


async def initialize():
    conn = await db()
    try:
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS oauth_clients (
                client_id TEXT PRIMARY KEY, redirect_uris JSONB NOT NULL,
                client_name TEXT NOT NULL, created_at TIMESTAMPTZ DEFAULT NOW()
            );
            CREATE TABLE IF NOT EXISTS oauth_codes (
                code_hash TEXT PRIMARY KEY, client_id TEXT NOT NULL,
                redirect_uri TEXT NOT NULL, challenge TEXT NOT NULL,
                pat_ciphertext BYTEA NOT NULL, expires_at TIMESTAMPTZ NOT NULL
            );
            CREATE TABLE IF NOT EXISTS oauth_tokens (
                token_hash TEXT PRIMARY KEY, client_id TEXT NOT NULL,
                pat_ciphertext BYTEA NOT NULL, token_type TEXT NOT NULL,
                expires_at TIMESTAMPTZ NOT NULL
            );
            CREATE INDEX IF NOT EXISTS oauth_tokens_expiry ON oauth_tokens(expires_at);
        ''')
    finally:
        await conn.close()


def allowed_redirect(uri):
    try:
        p = urlsplit(uri)
        return (p.scheme == 'https' and bool(p.netloc) and not p.username and not p.password and not p.fragment) or (
            p.scheme == 'http' and p.hostname in ('localhost', '127.0.0.1', '::1') and not p.username and not p.password and not p.fragment
        )
    except ValueError:
        return False


def error(message, status=400):
    return JSONResponse({'error': message}, status_code=status, headers={'Cache-Control': 'no-store'})


async def metadata(request):
    base = issuer()
    return JSONResponse({
        'issuer': base, 'authorization_endpoint': base + '/authorize',
        'token_endpoint': base + '/token', 'registration_endpoint': base + '/register',
        'revocation_endpoint': base + '/revoke',
        'response_types_supported': ['code'], 'grant_types_supported': ['authorization_code', 'refresh_token'],
        'code_challenge_methods_supported': ['S256'], 'token_endpoint_auth_methods_supported': ['none'],
        'scopes_supported': ['pco'],
    })


async def resource_metadata(request):
    return JSONResponse({'resource': issuer() + '/mcp', 'authorization_servers': [issuer()], 'scopes_supported': ['pco']})


async def register(request):
    try:
        data = await request.json()
        uris = data.get('redirect_uris')
        if not isinstance(uris, list) or not 1 <= len(uris) <= 10 or any(not isinstance(u, str) or not allowed_redirect(u) for u in uris):
            return error('invalid_redirect_uris')
        client_id = secrets.token_urlsafe(32)
        name = str(data.get('client_name', 'MCP Client'))[:120]
        conn = await db()
        try:
            await conn.execute('INSERT INTO oauth_clients(client_id, redirect_uris, client_name) VALUES($1,$2::jsonb,$3)', client_id, json.dumps(uris), name)
        finally:
            await conn.close()
        return JSONResponse({'client_id': client_id, 'client_name': name, 'redirect_uris': uris,
                             'token_endpoint_auth_method': 'none', 'grant_types': ['authorization_code', 'refresh_token'],
                             'response_types': ['code']}, status_code=201)
    except (ValueError, TypeError):
        return error('invalid_client_metadata')


async def valid_authorization(params):
    client_id = params.get('client_id', '')
    redirect_uri = params.get('redirect_uri', '')
    challenge = params.get('code_challenge', '')
    if params.get('response_type') != 'code' or params.get('code_challenge_method') != 'S256' or not re.fullmatch(r'[A-Za-z0-9_-]{43,128}', challenge):
        return False
    conn = await db()
    try:
        record = await conn.fetchrow('SELECT redirect_uris FROM oauth_clients WHERE client_id=$1', client_id)
    finally:
        await conn.close()
    return bool(record and redirect_uri in record['redirect_uris'])


FORM = '''<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Conectar Planning Center</title><style>body{font-family:system-ui;background:#f6f7fb;color:#172033;margin:0;padding:36px 16px}
main{max-width:430px;margin:auto;background:white;padding:30px;border-radius:14px;box-shadow:0 5px 25px #0001}
label{display:block;margin-top:18px;font-weight:600}input{box-sizing:border-box;width:100%;padding:12px;margin-top:6px;border:1px solid #bbc3d1;border-radius:7px}
button{background:#1764ce;color:white;border:0;padding:13px;width:100%;border-radius:7px;margin-top:24px;cursor:pointer}
p{line-height:1.5;color:#49556a;font-size:14px}</style></head><body><main><h2>Conectar Planning Center</h2>
<p>Insira seu Application ID e Secret do Personal Access Token. Eles serão validados no Planning Center e armazenados criptografados no servidor desta integração, não no cliente de IA.</p>
<form method="post" action="{form_action}"><input type="hidden" name="ticket" value="{ticket}">
<label>Application ID<input name="app_id" required autocomplete="off"></label>
<label>Secret<input name="secret" type="password" required autocomplete="off"></label>
<button type="submit">Conectar com segurança</button></form><p>Use somente um servidor que você reconhece e confia.</p></main></body></html>'''

# A signed, short-lived form ticket prevents parameter tampering between GET and POST.
from cryptography.fernet import InvalidToken


async def authorize_get(request):
    params = dict(request.query_params)
    if not await valid_authorization(params):
        return error('invalid_authorization_request')
    ticket = cipher().encrypt(json.dumps({'params': params, 'expires': (utcnow() + timedelta(minutes=10)).timestamp()}).encode()).decode()
    # Use the configured canonical HTTPS origin for both the form target and CSP.
    # This prevents browser-side form blocking if a proxy serves the OAuth page
    # under a different origin than the PUBLIC_URL origin.
    action = issuer() + '/authorize'
    page = (FORM.replace('{ticket}', html.escape(ticket, quote=True))
                .replace('{form_action}', html.escape(action, quote=True)))
    return HTMLResponse(page, headers={
        'Cache-Control': 'no-store',
        'Referrer-Policy': 'no-referrer',
        'Content-Security-Policy': (
            "default-src 'none'; style-src 'unsafe-inline'; "
            f"form-action 'self' {issuer()}; "
            "base-uri 'none'; frame-ancestors 'none'"
        ),
    })


async def authorize_post(request):
    form = await request.form()
    try:
        data = json.loads(cipher().decrypt(str(form.get('ticket', '')).encode()).decode())
        if data['expires'] < utcnow().timestamp():
            return error('expired_authorization')
        params = data['params']
    except (InvalidToken, ValueError, KeyError, TypeError):
        return error('invalid_authorization_ticket')
    if not await valid_authorization(params):
        return error('invalid_authorization_request')
    app_id = str(form.get('app_id', '')).strip()
    secret = str(form.get('secret', '')).strip()
    if not app_id or not secret or len(app_id) > 300 or len(secret) > 500:
        return error('invalid_credentials')
    async with httpx.AsyncClient(timeout=15) as client:
        try:
            response = await client.get('https://api.planningcenteronline.com/services/v2/service_types', auth=(app_id, secret), params={'per_page': 1})
        except httpx.RequestError:
            return error('planning_center_unavailable', 502)
    if response.status_code != 200:
        return error('planning_center_credentials_rejected', 401)
    code = secrets.token_urlsafe(40)
    encrypted = cipher().encrypt(json.dumps([app_id, secret]).encode())
    conn = await db()
    try:
        await conn.execute('INSERT INTO oauth_codes(code_hash,client_id,redirect_uri,challenge,pat_ciphertext,expires_at) VALUES($1,$2,$3,$4,$5,$6)',
                           digest(code), params['client_id'], params['redirect_uri'], params['code_challenge'], encrypted, utcnow() + timedelta(minutes=5))
    finally:
        await conn.close()
    query = {'code': code}
    if 'state' in params:
        query['state'] = params['state']
    return RedirectResponse(params['redirect_uri'] + ('&' if '?' in params['redirect_uri'] else '?') + urlencode(query), status_code=303, headers={'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer'})


def make_token():
    return secrets.token_urlsafe(48)


async def token(request):
    form = await request.form()
    grant = form.get('grant_type')
    client_id = str(form.get('client_id', ''))
    conn = await db()
    try:
        if grant == 'authorization_code':
            verifier = str(form.get('code_verifier', ''))
            if not re.fullmatch(r'[A-Za-z0-9._~-]{43,128}', verifier):
                return error('invalid_grant')
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
            async with conn.transaction():
                record = await conn.fetchrow('DELETE FROM oauth_codes WHERE code_hash=$1 AND client_id=$2 AND redirect_uri=$3 AND challenge=$4 AND expires_at>NOW() RETURNING pat_ciphertext',
                                             digest(str(form.get('code', ''))), client_id, str(form.get('redirect_uri', '')), challenge)
            if not record:
                return error('invalid_grant')
            encrypted = record['pat_ciphertext']
        elif grant == 'refresh_token':
            async with conn.transaction():
                record = await conn.fetchrow("DELETE FROM oauth_tokens WHERE token_hash=$1 AND client_id=$2 AND token_type='refresh' AND expires_at>NOW() RETURNING pat_ciphertext",
                                             digest(str(form.get('refresh_token', ''))), client_id)
            if not record:
                return error('invalid_grant')
            encrypted = record['pat_ciphertext']
        else:
            return error('unsupported_grant_type')
        access, refresh = make_token(), make_token()
        await conn.executemany('INSERT INTO oauth_tokens(token_hash,client_id,pat_ciphertext,token_type,expires_at) VALUES($1,$2,$3,$4,$5)', [
            (digest(access), client_id, encrypted, 'access', utcnow() + timedelta(hours=1)),
            (digest(refresh), client_id, encrypted, 'refresh', utcnow() + timedelta(days=30)),
        ])
        return JSONResponse({'access_token': access, 'refresh_token': refresh, 'token_type': 'Bearer', 'expires_in': 3600, 'scope': 'pco'}, headers={'Cache-Control': 'no-store', 'Pragma': 'no-cache'})
    finally:
        await conn.close()


async def revoke(request):
    form = await request.form()
    conn = await db()
    try:
        await conn.execute('DELETE FROM oauth_tokens WHERE token_hash=$1 AND client_id=$2', digest(str(form.get('token', ''))), str(form.get('client_id', '')))
    finally:
        await conn.close()
    return JSONResponse({}, headers={'Cache-Control': 'no-store'})


class ProtectedMCP:
    """Enforce bearer authorization before any /mcp request reaches FastMCP."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or not (scope.get('path', '') == '/mcp' or scope.get('path', '').startswith('/mcp/')):
            return await self.app(scope, receive, send)
        headers = dict(scope.get('headers', []))
        authorization = headers.get(b'authorization', b'').decode('latin1')
        value = authorization[7:] if authorization.lower().startswith('bearer ') else ''
        record = None
        if value:
            conn = await db()
            try:
                record = await conn.fetchrow("SELECT pat_ciphertext FROM oauth_tokens WHERE token_hash=$1 AND token_type='access' AND expires_at>NOW()", digest(value))
            finally:
                await conn.close()
        if not record:
            response = JSONResponse({'error': 'unauthorized'}, status_code=401, headers={
                'WWW-Authenticate': f'Bearer resource_metadata="{issuer()}/.well-known/oauth-protected-resource"',
                'Cache-Control': 'no-store',
            })
            return await response(scope, receive, send)
        try:
            pat = json.loads(cipher().decrypt(record['pat_ciphertext']).decode())
        except (InvalidToken, ValueError):
            return await error('invalid_credentials', 401)(scope, receive, send)
        marker = current_pat.set(tuple(pat))
        try:
            return await self.app(scope, receive, send)
        finally:
            current_pat.reset(marker)
