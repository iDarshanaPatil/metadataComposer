import base64
import hashlib
import hmac
import json
import secrets
import time
from fastapi import Request, HTTPException
from .config import settings

def password_hash(password: str, salt: bytes | None = None):
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1)
    return salt.hex() + ':' + digest.hex()

def check_password(password: str):
    try:
        salt, _ = settings().owner_password_hash.split(':')
        return hmac.compare_digest(password_hash(password, bytes.fromhex(salt)), settings().owner_password_hash)
    except ValueError:
        return False

def make_session():
    payload = base64.urlsafe_b64encode(json.dumps({'expires': time.time()+28800, 'csrf': secrets.token_urlsafe(24)}).encode()).decode()
    signature = hmac.new(settings().session_secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return payload + '.' + signature

def identity(request: Request):
    try:
        payload, signature = request.cookies.get('metadata_session','').split('.')
        expected = hmac.new(settings().session_secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected): raise ValueError()
        data = json.loads(base64.urlsafe_b64decode(payload))
        if data['expires'] < time.time(): raise ValueError()
    except (ValueError, KeyError, TypeError):
        raise HTTPException(401, 'Please sign in')
    if request.method not in ('GET','HEAD','OPTIONS'):
        if not hmac.compare_digest(request.headers.get('X-CSRF-Token',''), data['csrf']):
            raise HTTPException(403, 'Invalid request token')
    return {'name': settings().owner_name, 'csrf': data['csrf']}

def config_identity(request: Request):
    token = request.headers.get('Authorization','').removeprefix('Bearer ')
    if settings().read_api_token and hmac.compare_digest(token, settings().read_api_token):
        return {'name':'read-api'}
    return identity(request)
