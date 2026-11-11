import base64
import json
import os
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from .config import settings

def enc64(value: bytes) -> str: return base64.urlsafe_b64encode(value).decode().rstrip('=')
def dec64(value: str) -> bytes: return base64.urlsafe_b64decode(value + '=' * (-len(value) % 4))
def aad(org, app, namespace, key):
    return json.dumps([org, app, namespace, key], separators=(',', ':')).encode()
def cipher():
    key = base64.b64decode(settings().master_key, validate=True)
    if len(key) != 32: raise ValueError('MASTER_KEY must decode to exactly 32 bytes')
    return AESGCM(key)
def encrypt(value: str, context: bytes) -> str:
    nonce = os.urandom(12)
    result = cipher().encrypt(nonce, value.encode(), context)
    return '.'.join(['v1', enc64(nonce), enc64(result[-16:]), enc64(result[:-16])])
def decrypt(value: str, context: bytes) -> str:
    version, nonce, tag, data = value.split('.')
    if version != 'v1': raise ValueError('Unsupported envelope')
    return cipher().decrypt(dec64(nonce), dec64(data) + dec64(tag), context).decode()
