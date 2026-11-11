import base64
import os
import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from alembic import command
from alembic.config import Config

@pytest.fixture(scope='session')
def test_engine():
    url = os.environ.get('TEST_DATABASE_URL')
    if not url:
        pytest.skip('Set TEST_DATABASE_URL to a disposable PostgreSQL database ending in _test')
    if not (make_url(url).database or '').endswith('_test'):
        raise RuntimeError('Refusing to reset a database whose name does not end in _test')
    os.environ['DATABASE_URL'] = url
    os.environ['MASTER_KEY'] = base64.b64encode(b't'*32).decode()
    os.environ['SESSION_SECRET'] = 'test-session-secret-'*3
    os.environ['OWNER_NAME'] = 'Test Owner'
    os.environ['ALLOWED_ORIGIN'] = 'http://testserver'
    os.environ['COOKIE_SECURE'] = 'false'
    os.environ['OWNER_PASSWORD_HASH'] = 'placeholder'
    from app.auth import password_hash
    os.environ['OWNER_PASSWORD_HASH'] = password_hash('a-long-test-password')
    from app.config import settings
    from app.db import engine
    settings.cache_clear();engine.cache_clear()
    command.upgrade(Config('alembic.ini'),'head')
    yield engine()
    engine().dispose()

@pytest.fixture
def client(test_engine):
    with test_engine.begin() as conn:
        conn.execute(text('TRUNCATE history, variables, namespaces, apps, orgs RESTART IDENTITY CASCADE'))
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as client:
        assert client.post('/api/auth/login',json={'password':'a-long-test-password'}).status_code == 200
        client.headers['X-CSRF-Token'] = client.get('/api/auth/me').json()['csrf']
        yield client

@pytest.fixture
def workspace(client):
    assert client.post('/api/v1/orgs',json={'name':'acme'}).status_code == 201
    for name in ['web-dev','web-prod']:
        assert client.post('/api/v1/orgs/acme/apps',json={'name':name}).status_code == 201
        assert client.post(f'/api/v1/namespaces/acme/{name}',json={'name':'database'}).status_code == 201
    return client
