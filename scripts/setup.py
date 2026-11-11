"""Generate local configuration without installing any Python packages."""
import base64
import getpass
import hashlib
import os
from pathlib import Path
import secrets


def main():
    target = Path(__file__).resolve().parents[1] / '.env'
    if target.exists():
        print('.env already exists; leaving your password and encryption key unchanged.')
        return
    password = getpass.getpass('Choose a workspace password (at least 12 characters): ')
    if len(password) < 12:
        raise SystemExit('Please use at least 12 characters. Run this script again.')
    if password != getpass.getpass('Confirm password: '):
        raise SystemExit('Passwords did not match. No configuration was written.')
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(),salt=salt,n=16384,r=8,p=1)
    values = {
        'MASTER_KEY':base64.b64encode(secrets.token_bytes(32)).decode(),
        'SESSION_SECRET':secrets.token_urlsafe(48),
        'OWNER_PASSWORD_HASH':salt.hex()+':'+digest.hex(),
        'OWNER_NAME':'Darshu',
        'DATABASE_URL':'postgresql+psycopg://metadata:metadata@localhost:5432/metadata',
        'ALLOWED_ORIGIN':'http://localhost:8080',
        'COOKIE_SECURE':'false',
        'READ_API_TOKEN':'',
    }
    fd = os.open(target, os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600)
    with os.fdopen(fd,'w') as out:
        out.write('\n'.join(f'{k}={v}' for k,v in values.items())+'\n')
    print('Created .env. Keep a private backup: the master key is required to decrypt your secrets.')
    print('Next: docker compose up --build')

if __name__ == '__main__':
    main()
