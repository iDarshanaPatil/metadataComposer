import base64
import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

BASE='/api/v1/variables/acme/web-dev/database'

def batch(client,changes,revision=None):
    if revision is None: revision=client.get(BASE).json()['revision']
    return client.post(BASE+'/batch',json={'revision':revision,'changes':changes})

def test_batch_is_atomic_including_history(workspace,test_engine):
    before=workspace.get('/api/v1/history/acme').json()
    response=batch(workspace,[{'op':'put','key':'HOST','value':'localhost'}, {'op':'put','key':'PORT','value':'not-a-number','type':'number'}])
    assert response.status_code==400
    assert workspace.get(BASE).json()['variables']==[]
    assert workspace.get('/api/v1/history/acme').json()==before

def test_secret_masking_reveal_and_audit(workspace,test_engine):
    assert batch(workspace,[{'op':'put','key':'PASSWORD','value':'hidden-value','secret':True}]).status_code==200
    assert workspace.get(BASE).json()['variables'][0]['value'] is None
    assert 'hidden-value' not in workspace.get('/api/v1/tree').text
    assert workspace.get('/api/v1/config/acme/web-dev').json()['config']['database']['PASSWORD'] is None
    with test_engine.connect() as conn:
        envelope=conn.execute(text("SELECT value FROM variables WHERE key='PASSWORD'")).scalar_one()
    assert envelope.startswith('v1.') and 'hidden-value' not in envelope
    assert workspace.post(BASE+'/PASSWORD/reveal').json()['value']=='hidden-value'
    assert workspace.get('/api/v1/history/acme').json()[0]['action']=='reveal'
    assert batch(workspace,[{'op':'put','key':'PASSWORD','description':'Rotated quarterly'}]).status_code==200
    assert workspace.post(BASE+'/PASSWORD/reveal').json()['value']=='hidden-value'
    assert all('hidden-value' not in str(h) for h in workspace.get('/api/v1/history/acme').json())

def test_copy_reencrypts_and_never_overwrites(workspace,test_engine):
    batch(workspace,[{'op':'put','key':'PASSWORD','value':'hidden-value','secret':True}])
    request={'org':'acme','source_app':'web-dev','target_app':'web-prod','namespace':'database','key':'PASSWORD'}
    assert workspace.post('/api/v1/copy',json=request).status_code==200
    assert workspace.post('/api/v1/copy',json=request).status_code==409
    with test_engine.connect() as conn:
        envelopes=conn.execute(text("SELECT value FROM variables WHERE key='PASSWORD' ORDER BY id")).scalars().all()
    assert len(envelopes)==2 and envelopes[0]!=envelopes[1]
    assert workspace.post('/api/v1/variables/acme/web-prod/database/PASSWORD/reveal').json()['value']=='hidden-value'

def test_stale_save_and_duplicate_keys_rejected(workspace):
    batch(workspace,[{'op':'put','key':'PORT','value':'5432','type':'number'}])
    assert batch(workspace,[{'op':'put','key':'PORT','value':'5000'}],revision=0).status_code==409
    assert batch(workspace,[{'op':'put','key':'X','value':'one'},{'op':'put','key':'X','value':'two'}]).status_code==400

def test_ref_rules_and_one_level_expansion(workspace):
    assert batch(workspace,[{'op':'put','key':'SELF','type':'ref','value':'database'}]).status_code==400
    assert batch(workspace,[{'op':'put','key':'MISSING','type':'ref','value':'missing'}]).status_code==400
    assert batch(workspace,[{'op':'put','key':'BACK','type':'ref','value':'default'}]).status_code==200
    default='/api/v1/variables/acme/web-dev/default'
    assert workspace.post(default+'/batch',json={'revision':0,'changes':[{'op':'put','key':'DB','type':'ref','value':'database'}]}).status_code==200
    assert workspace.delete('/api/v1/namespaces/acme/web-dev/database').status_code==400
    config=workspace.get('/api/v1/config/acme/web-dev?expand=1&refs=DB,not_found').json()
    assert config['config']['default']['DB']=={'BACK':{'$ref':'default'}}
    assert config['missing']==['default.not_found']

def test_history_survives_variable_and_namespace_deletion(workspace):
    batch(workspace,[{'op':'put','key':'HOST','value':'localhost'}])
    assert batch(workspace,[{'op':'delete','key':'HOST'}]).status_code==200
    assert workspace.delete('/api/v1/namespaces/acme/web-dev/database').status_code==200
    history=workspace.get('/api/v1/history/acme?key=HOST').json()
    assert [h['action'] for h in history]==['delete','create']

def test_default_cannot_be_deleted_and_app_cascade_works(workspace):
    assert workspace.delete('/api/v1/namespaces/acme/web-dev/default').status_code==400
    assert workspace.delete('/api/v1/orgs/acme/apps/web-dev').status_code==200
    assert workspace.get('/api/v1/orgs/acme/apps/web-dev').status_code==404
    assert workspace.request('DELETE','/api/v1/orgs/acme',json={'confirmation':'wrong'}).status_code==400
    assert workspace.request('DELETE','/api/v1/orgs/acme',json={'confirmation':'acme'}).status_code==200

def test_csrf_and_session_required(workspace):
    workspace.headers.pop('X-CSRF-Token')
    assert workspace.post('/api/v1/orgs',json={'name':'blocked'}).status_code==403
    workspace.cookies.clear()
    assert workspace.get(BASE).status_code==401

def test_database_constraints_cannot_be_bypassed(workspace,test_engine):
    with pytest.raises(IntegrityError):
        with test_engine.begin() as conn:
            conn.execute(text("INSERT INTO orgs(name,created_at) VALUES ('Bad Name',now())"))
    with pytest.raises(IntegrityError):
        with test_engine.begin() as conn:
            conn.execute(text("DELETE FROM namespaces WHERE name='default'"))
    with pytest.raises(IntegrityError):
        with test_engine.begin() as conn:
            conn.execute(text("DELETE FROM history"))

def test_encrypt_context_and_tamper_detection(monkeypatch):
    from app.config import settings
    monkeypatch.setenv('MASTER_KEY',base64.b64encode(b't'*32).decode())
    monkeypatch.setenv('OWNER_PASSWORD_HASH','test')
    monkeypatch.setenv('SESSION_SECRET','x'*32)
    settings.cache_clear()
    from app.crypto import encrypt,decrypt,aad
    from cryptography.exceptions import InvalidTag
    ctx=aad('acme','web','database','PASSWORD')
    value=encrypt('secret',ctx)
    assert decrypt(value,ctx)=='secret'
    with pytest.raises(InvalidTag): decrypt(value,aad('acme','billing','database','PASSWORD'))
    parts=value.split('.')
    parts[2]=('A' if parts[2][0]!='A' else 'B')+parts[2][1:]
    with pytest.raises(InvalidTag): decrypt('.'.join(parts),ctx)
    settings.cache_clear()

def test_secret_type_change_validates_current_value(workspace):
    batch(workspace,[{'op':'put','key':'TOKEN','value':'not-numeric','secret':True}])
    assert batch(workspace,[{'op':'put','key':'TOKEN','type':'number'}]).status_code==400
    assert workspace.post(BASE+'/TOKEN/reveal').json()['value']=='not-numeric'

def test_marking_secret_protects_previous_value(workspace):
    batch(workspace,[{'op':'put','key':'TOKEN','value':'sensitive'}])
    assert batch(workspace,[{'op':'put','key':'TOKEN','secret':True}]).status_code==200
    assert workspace.get('/api/v1/history/acme').json()[0]['old_value']=='secret'
