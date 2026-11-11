import re
from decimal import Decimal, InvalidOperation
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from .models import Org, App, Namespace, Variable, History
from .crypto import encrypt, decrypt, aad


def fail(message, status=400): raise HTTPException(status, message)
def org_named(db, name):
    org = db.scalar(select(Org).where(Org.name == name))
    if org is None: fail('Org not found', 404)
    return org

def scope(db, org_name, app_name, ns_name=None, lock=False):
    org = org_named(db, org_name)
    query = select(App).where(App.org_id == org.id, App.name == app_name)
    if lock: query = query.with_for_update()
    app = db.scalar(query)
    if app is None: fail('App not found', 404)
    ns = None
    if ns_name is not None:
        ns = db.scalar(select(Namespace).where(Namespace.app_id == app.id, Namespace.name == ns_name))
        if ns is None: fail('Namespace not found', 404)
    return org, app, ns

def context(org, app, ns, key): return aad(org.name, app.name, ns.name, key)
def plain(row, org, app, ns): return decrypt(row.value, context(org, app, ns, row.key)) if row.secret else row.value

def log(db, org, app, ns, actor, action, row=None, old='', secret=False, key=''):
    db.add(History(org_id=org.id, app_id=app.id if app else None, namespace=ns.name if ns else '',
        key=row.key if row else key, variable_id=row.id if row else None,
        action=action, old_value=old, secret=secret, changed_by=actor))

def validate(db, app, ns, kind, value, secret, description):
    if len(value.encode('utf-8')) > 65536: fail('value is larger than 64 KiB')
    if len(description) > 500: fail('description is longer than 500 characters')
    if kind == 'number':
        try:
            if not re.fullmatch(r'[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?', value) or not Decimal(value).is_finite(): raise InvalidOperation()
        except InvalidOperation: fail('value is not a finite number')
    if kind == 'boolean' and value not in ('true','false'): fail('a boolean must be true or false')
    if kind == 'ref':
        if secret: fail('A ref names a namespace, so it cannot be secret')
        if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,62}',value): fail('Invalid ref namespace name')
        target = db.scalar(select(Namespace).where(Namespace.app_id == app.id, Namespace.name == value))
        if target is None: fail(f'No namespace {value} in this app to point at')
        if target.id == ns.id: fail('A ref cannot point at its own namespace')
        return target.id
    return None

def row_json(row):
    return {'id':row.id,'key':row.key,'type':row.type,'value':None if row.secret else row.value,
        'secret':row.secret,'description':row.description,'updated_by':row.updated_by,'updated_at':row.updated_at}

def apply_changes(db: Session, org, app, ns, batch, actor):
    if ns.revision != batch.revision: fail('This namespace changed. Discard your draft and reload before editing.',409)
    keys = [c.key for c in batch.changes]
    if len(keys) != len(set(keys)): fail('Each key may appear only once in a save')
    changed = 0
    for change in batch.changes:
        row = db.scalar(select(Variable).where(Variable.namespace_id == ns.id, Variable.key == change.key))
        if change.op == 'delete':
            if row is None: fail(f'{change.key} no longer exists',409)
            log(db,org,app,ns,actor,'delete',row,row.value,row.secret)
            db.flush()
            db.delete(row)
            changed += 1
            continue
        fields = change.model_dump(exclude_unset=True, exclude={'op','key'})
        if any(v is None for v in fields.values()): fail('Updated fields cannot be null; omit them to keep the current value')
        if row is None and 'value' not in fields: fail('value is required for a new variable')
        kind = fields.get('type',row.type if row else 'string')
        secret = fields.get('secret',row.secret if row else False)
        description = fields.get('description',row.description if row else '').strip()
        value = fields.get('value')
        if value is None: value = plain(row,org,app,ns)
        target_id = validate(db,app,ns,kind,value,secret,description)
        if row and kind == row.type and secret == row.secret and description == row.description and value == plain(row,org,app,ns):
            continue
        old, old_secret = (row.value, row.secret) if row else ('',False)
        action = 'update' if row else 'create'
        # Once marked secret, the previous plaintext must not leak through history.
        if row and secret and not old_secret:
            old = encrypt(old, context(org, app, ns, row.key))
            old_secret = True
        if row is None:
            row = Variable(app_id=app.id,namespace_id=ns.id,key=change.key)
            db.add(row)
        row.type, row.secret, row.description = kind,secret,description
        row.value = encrypt(value,context(org,app,ns,row.key)) if secret else value
        row.ref_namespace_id, row.updated_by = target_id, actor
        db.flush()
        log(db,org,app,ns,actor,action,row,old,old_secret)
        changed += 1
    if changed: ns.revision += 1
    db.flush()
    return {'changed':changed, 'revision':ns.revision}

def reveal(db, org, app, ns, row, actor):
    value = plain(row,org,app,ns)
    if row.secret: log(db,org,app,ns,actor,'reveal',row)
    return value

def copy_items(db, request, actor):
    org = org_named(db,request.org)
    # Lock both apps in ID order to avoid opposite-direction copy deadlocks.
    apps = db.scalars(select(App).where(App.org_id==org.id, App.name.in_([request.source_app,request.target_app])).order_by(App.id).with_for_update()).all()
    lookup = {a.name:a for a in apps}
    if request.source_app == request.target_app: fail('Pick a different app to copy to')
    if len(lookup) != 2: fail('App not found',404)
    source,target = lookup[request.source_app],lookup[request.target_app]
    ns = db.scalar(select(Namespace).where(Namespace.app_id==source.id,Namespace.name==request.namespace))
    if ns is None: fail('Namespace not found',404)
    dest = db.scalar(select(Namespace).where(Namespace.app_id==target.id,Namespace.name==request.namespace))
    if request.key is None:
        if dest: fail(f'{target.name} already has {ns.name}; nothing was overwritten',409)
        dest = Namespace(org_id=org.id,app_id=target.id,name=ns.name)
        db.add(dest); db.flush()
        rows = db.scalars(select(Variable).where(Variable.namespace_id==ns.id)).all()
        log(db,org,target,dest,actor,'create')
    else:
        if dest is None: fail(f'{target.name} has no namespace {ns.name}; copy the namespace instead')
        if db.scalar(select(Variable).where(Variable.namespace_id==dest.id,Variable.key==request.key)):
            fail(f'{target.name} already has {ns.name}.{request.key}; nothing was overwritten',409)
        row = db.scalar(select(Variable).where(Variable.namespace_id==ns.id,Variable.key==request.key))
        if row is None: fail('Variable not found',404)
        rows = [row]
    for row in rows:
        value = plain(row,org,source,ns)
        ref = validate(db,target,dest,row.type,value,row.secret,row.description)
        copied = Variable(app_id=target.id,namespace_id=dest.id,key=row.key,type=row.type,secret=row.secret,
            value=encrypt(value,context(org,target,dest,row.key)) if row.secret else value,
            description=row.description,ref_namespace_id=ref,updated_by=actor)
        db.add(copied); db.flush()
        log(db,org,target,dest,actor,'create',copied)
    dest.revision += 1
    return {'copied':len(rows)}
