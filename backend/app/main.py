import time
from contextlib import asynccontextmanager
from collections import defaultdict, deque
from fastapi import FastAPI, Depends, Request, Response, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from .config import settings
from .db import session
from .models import Org, App, Namespace, Variable, History
from .schemas import Named, Login, Batch, Copy, DeleteOrg
from .auth import identity, config_identity, check_password, make_session
from . import service as svc

@asynccontextmanager
async def lifespan(app):
    from .crypto import cipher
    cipher()  # Fail at startup for a missing/invalid encryption key.
    if len(settings().session_secret) < 32:
        raise RuntimeError('SESSION_SECRET must contain at least 32 characters')
    yield

app = FastAPI(title='MetadataComposer', version='0.1.0', lifespan=lifespan)
attempts = defaultdict(deque)
DB = Depends(session)
USER = Depends(identity)

@app.middleware('http')
async def safety_headers(request: Request, call_next):
    origin = request.headers.get('origin')
    if request.method not in ('GET','HEAD','OPTIONS') and origin and origin != settings().allowed_origin:
        return JSONResponse({'error':'Origin not allowed'},status_code=403)
    response = await call_next(request)
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'no-referrer'
    return response

@app.exception_handler(HTTPException)
async def http_error(request, exc): return JSONResponse({'error':exc.detail},status_code=exc.status_code)
@app.exception_handler(RequestValidationError)
async def invalid(request, exc):
    errors = exc.errors()
    # Do not echo input values: they may contain secrets.
    message = '; '.join('.'.join(map(str,e['loc'][1:])) + ': ' + e['msg'] for e in errors)
    return JSONResponse({'error':message},status_code=400)
@app.exception_handler(IntegrityError)
async def conflict(request, exc):
    return JSONResponse({'error':'A database rule or concurrent change prevented this operation; nothing was saved.'},status_code=409)

@app.get('/api/health')
def health(): return {'status':'ok'}
@app.post('/api/auth/login')
def login(body: Login, request: Request, response: Response):
    address = request.client.host if request.client else 'unknown'
    queue = attempts[address]
    while queue and queue[0] < time.monotonic()-60: queue.popleft()
    if len(queue) >= 10: raise HTTPException(429,'Too many attempts. Try again in one minute.')
    queue.append(time.monotonic())
    if not check_password(body.password): raise HTTPException(401,'Incorrect password')
    queue.clear()
    response.set_cookie('metadata_session',make_session(),httponly=True,secure=settings().cookie_secure,samesite='strict',max_age=28800,path='/')
    return {'ok':True}
@app.get('/api/auth/me')
def me(user=USER): return user
@app.post('/api/auth/logout')
def logout(response: Response,user=USER):
    response.delete_cookie('metadata_session',path='/')
    return {'ok':True}

@app.get('/api/v1/orgs')
def orgs(db: Session=DB,user=USER):
    return [{'id':o.id,'name':o.name,'app_count':db.scalar(select(func.count(App.id)).where(App.org_id==o.id))} for o in db.scalars(select(Org).order_by(Org.name))]
@app.post('/api/v1/orgs',status_code=201)
def create_org(body: Named,db: Session=DB,user=USER):
    org = Org(name=body.name); db.add(org); db.flush()
    svc.log(db,org,None,None,user['name'],'create',key=org.name)
    db.commit(); return {'name':org.name}
@app.delete('/api/v1/orgs/{org}')
def delete_org(org:str,body:DeleteOrg,db:Session=DB,user=USER):
    item=svc.org_named(db,org)
    if body.confirmation != org: svc.fail('Type the org name to confirm')
    db.delete(item);db.commit();return {'deleted':True}

@app.get('/api/v1/orgs/{org}/apps')
def apps(org:str,db:Session=DB,user=USER):
    item=svc.org_named(db,org)
    return [{'id':a.id,'name':a.name,'namespace_count':db.scalar(select(func.count(Namespace.id)).where(Namespace.app_id==a.id))} for a in db.scalars(select(App).where(App.org_id==item.id).order_by(App.id))]
@app.post('/api/v1/orgs/{org}/apps',status_code=201)
def create_app(org:str,body:Named,db:Session=DB,user=USER):
    if body.name=='settings': svc.fail('settings is reserved; pick another app name')
    owner=svc.org_named(db,org)
    item=App(org_id=owner.id,name=body.name);db.add(item);db.flush()
    ns=Namespace(org_id=owner.id,app_id=item.id,name='default');db.add(ns);db.flush()
    svc.log(db,owner,item,None,user['name'],'create',key=item.name)
    svc.log(db,owner,item,ns,user['name'],'create')
    db.commit();return {'name':item.name}
@app.delete('/api/v1/orgs/{org}/apps/{app_name}')
def delete_app(org:str,app_name:str,db:Session=DB,user=USER):
    owner,item,_=svc.scope(db,org,app_name,lock=True)
    # Org-level record survives the app's cascading history deletion.
    svc.log(db,owner,None,None,user['name'],'delete',key=app_name)
    db.delete(item);db.commit();return {'deleted':True}

@app.get('/api/v1/namespaces/{org}/{app_name}')
def namespaces(org:str,app_name:str,db:Session=DB,user=USER):
    _,item,_=svc.scope(db,org,app_name)
    rows=db.scalars(select(Namespace).where(Namespace.app_id==item.id).order_by(Namespace.name!='default',Namespace.name)).all()
    return [{'id':n.id,'name':n.name,'revision':n.revision,'count':db.scalar(select(func.count(Variable.id)).where(Variable.namespace_id==n.id))} for n in rows]
@app.post('/api/v1/namespaces/{org}/{app_name}',status_code=201)
def create_namespace(org:str,app_name:str,body:Named,db:Session=DB,user=USER):
    if body.name=='default': svc.fail('Every app already has its default namespace')
    owner,item,_=svc.scope(db,org,app_name,lock=True)
    ns=Namespace(org_id=owner.id,app_id=item.id,name=body.name);db.add(ns);db.flush()
    svc.log(db,owner,item,ns,user['name'],'create');db.commit();return {'name':ns.name}
@app.delete('/api/v1/namespaces/{org}/{app_name}/{ns_name}')
def delete_namespace(org:str,app_name:str,ns_name:str,db:Session=DB,user=USER):
    owner,item,ns=svc.scope(db,org,app_name,ns_name,lock=True)
    if ns.name=='default': svc.fail('The default namespace cannot be deleted')
    ref=db.scalar(select(Variable).where(Variable.ref_namespace_id==ns.id))
    if ref: svc.fail(f'{ns.name} is used by ref {ref.key}; change those first')
    for row in db.scalars(select(Variable).where(Variable.namespace_id==ns.id)):
        svc.log(db,owner,item,ns,user['name'],'delete',row,row.value,row.secret)
    svc.log(db,owner,item,ns,user['name'],'delete');db.flush();db.delete(ns);db.commit();return {'deleted':True}

@app.get('/api/v1/variables/{org}/{app_name}/{ns_name}')
def variables(org:str,app_name:str,ns_name:str,db:Session=DB,user=USER):
    _,_,ns=svc.scope(db,org,app_name,ns_name)
    return {'revision':ns.revision,'variables':[svc.row_json(r) for r in db.scalars(select(Variable).where(Variable.namespace_id==ns.id).order_by(Variable.id))]}
@app.post('/api/v1/variables/{org}/{app_name}/{ns_name}/batch')
def save(org:str,app_name:str,ns_name:str,body:Batch,db:Session=DB,user=USER):
    owner,item,ns=svc.scope(db,org,app_name,ns_name,lock=True)
    result=svc.apply_changes(db,owner,item,ns,body,user['name']);db.commit();return result
@app.post('/api/v1/variables/{org}/{app_name}/{ns_name}/{key}/reveal')
def reveal(org:str,app_name:str,ns_name:str,key:str,db:Session=DB,user=USER):
    owner,item,ns=svc.scope(db,org,app_name,ns_name,lock=True)
    row=db.scalar(select(Variable).where(Variable.namespace_id==ns.id,Variable.key==key))
    if row is None: svc.fail('Variable not found',404)
    value=svc.reveal(db,owner,item,ns,row,user['name']);db.commit();return {'value':value}
@app.post('/api/v1/copy')
def copy(body:Copy,db:Session=DB,user=USER):
    result=svc.copy_items(db,body,user['name']);db.commit();return result
@app.get('/api/v1/copy-targets/{org}/{app_name}/{ns_name}')
def copy_targets(org:str,app_name:str,ns_name:str,key:str|None=None,db:Session=DB,user=USER):
    owner,item,_=svc.scope(db,org,app_name,ns_name)
    result=[]
    for target in db.scalars(select(App).where(App.org_id==owner.id,App.id!=item.id)):
        ns=db.scalar(select(Namespace).where(Namespace.app_id==target.id,Namespace.name==ns_name))
        if (key is None and ns is None) or (key is not None and ns is not None and not db.scalar(select(Variable).where(Variable.namespace_id==ns.id,Variable.key==key))): result.append(target.name)
    return result

@app.get('/api/v1/history/{org}')
def history(org:str,app_name:str|None=None,namespace:str|None=None,key:str|None=None,person:str|None=None,before:int|None=None,db:Session=DB,user=USER):
    owner=svc.org_named(db,org)
    query=select(History,App.name).outerjoin(App,History.app_id==App.id).where(History.org_id==owner.id)
    if app_name: query=query.where(App.name==app_name)
    if namespace: query=query.where(History.namespace==namespace)
    if key: query=query.where(History.key==key)
    if person: query=query.where(History.changed_by==person)
    if before: query=query.where(History.id<before)
    return [{'id':h.id,'app':name,'namespace':h.namespace,'key':h.key,'action':h.action,'old_value':'secret' if h.secret else h.old_value,'secret':h.secret,'changed_at':h.changed_at,'changed_by':h.changed_by} for h,name in db.execute(query.order_by(History.id.desc()).limit(100))]

@app.get('/api/v1/config/{org}/{app_name}')
def config(org:str,app_name:str,refs:str|None=None,expand:int=0,reveal:bool=False,db:Session=DB,user=Depends(config_identity)):
    if expand not in (0,1): svc.fail('expand must be 0 or 1')
    owner,item,_=svc.scope(db,org,app_name,lock=reveal)
    nss={n.id:n for n in db.scalars(select(Namespace).where(Namespace.app_id==item.id))}
    rows=db.scalars(select(Variable).where(Variable.app_id==item.id)).all()
    lookup={(nss[r.namespace_id].name,r.key):r for r in rows}
    revealed={}
    def value_of(row,do_expand=False):
        ns=nss[row.namespace_id]
        if row.type=='ref':
            if do_expand: return {r.key:value_of(r) for r in rows if r.namespace_id==row.ref_namespace_id}
            return {'$ref':row.value}
        if row.secret:
            if not reveal: return None
            if row.id not in revealed: revealed[row.id]=svc.reveal(db,owner,item,ns,row,user['name'])
            return revealed[row.id]
        return row.value
    result={};missing=[]
    requested = list(lookup) if refs is None else [tuple(x.split('.',1)) if '.' in x else ('default',x) for x in refs.split(',')]
    for ns,key in requested:
        row=lookup.get((ns,key))
        if row is None: missing.append(f'{ns}.{key}');continue
        result.setdefault(ns,{})[key]=value_of(row,expand==1)
    db.commit();return {'config':result,'missing':missing}

@app.get('/api/v1/tree')
def tree(db:Session=DB,user=USER):
    root={'id':'root','kind':'root','name':'Workspace','children':[]}
    for org in db.scalars(select(Org).order_by(Org.name)):
        o={'id':f'o:{org.name}','kind':'org','name':org.name,'children':[]};root['children'].append(o)
        for item in db.scalars(select(App).where(App.org_id==org.id).order_by(App.name)):
            a={'id':f'a:{org.name}/{item.name}','kind':'app','name':item.name,'children':[]};o['children'].append(a)
            for ns in db.scalars(select(Namespace).where(Namespace.app_id==item.id).order_by(Namespace.name!='default',Namespace.name)):
                rows=db.scalars(select(Variable).where(Variable.namespace_id==ns.id).order_by(Variable.key)).all()
                n={'id':f'n:{org.name}/{item.name}/{ns.name}','kind':'namespace','name':ns.name,'count':len(rows),'children':[]};a['children'].append(n)
                for r in rows:
                    value='••••••' if r.secret else 'ref:'+r.value if r.type=='ref' else r.value
                    if len(value)>32: value=value[:32]+'…'
                    n['children'].append({'id':f'{n["id"]}:{r.key}','kind':'variable','name':f'{r.key} = {value}','secret':r.secret,'children':[]})
    return root

@app.get('/api/v1/orgs/{org}')
def get_org(org:str,db:Session=DB,user=USER):
    item=svc.org_named(db,org)
    return {'id':item.id,'name':item.name}

@app.get('/api/v1/orgs/{org}/apps/{app_name}')
def get_app(org:str,app_name:str,db:Session=DB,user=USER):
    _,item,_=svc.scope(db,org,app_name)
    return {'id':item.id,'name':item.name}

from .schemas import PutVariable, Change

@app.put('/api/v1/variables/{org}/{app_name}/{ns_name}/{key}')
def put_variable(org:str,app_name:str,ns_name:str,key:str,body:PutVariable,db:Session=DB,user=USER):
    owner,item,ns=svc.scope(db,org,app_name,ns_name,lock=True)
    try:
        change=Change(op='put',key=key,**body.model_dump(exclude={'revision'},exclude_unset=True))
    except ValueError:
        svc.fail('Invalid variable key')
    result=svc.apply_changes(db,owner,item,ns,Batch(revision=body.revision,changes=[change]),user['name'])
    db.commit();return result

@app.delete('/api/v1/variables/{org}/{app_name}/{ns_name}/{key}')
def delete_variable(org:str,app_name:str,ns_name:str,key:str,revision:int,db:Session=DB,user=USER):
    owner,item,ns=svc.scope(db,org,app_name,ns_name,lock=True)
    try:
        body=Batch(revision=revision,changes=[Change(op='delete',key=key)])
    except ValueError:
        svc.fail('Invalid variable key or revision')
    result=svc.apply_changes(db,owner,item,ns,body,user['name'])
    db.commit();return result
