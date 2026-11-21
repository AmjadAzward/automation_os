"""Accounts, passwords, sessions and role-based access control."""
from . import config
import hashlib
import hmac
import re
import secrets
import sqlite3
import time
from .db import audit, db, now, today

COOKIE='aos_session'

SESSION_SECONDS=12*3600

ROLES=('viewer','member','manager','admin')

RANK={r:i for i,r in enumerate(ROLES)}

EMAIL_RE=re.compile(r'[^@\s]{1,64}@[^@\s]{1,200}\.[^@\s]{2,}')
USERNAME_RE=re.compile(r'[A-Za-z0-9._-]{3,32}')

PUBLIC_GET={'/api/health','/api/auth/me'}

PUBLIC_POST={'/api/auth/login','/api/auth/setup','/api/auth/logout'}

FAILS={}

class AuthError(Exception):
    """The caller is not signed in (HTTP 401)."""

class Forbidden(Exception):
    """The caller is signed in but not allowed to do this (HTTP 403)."""

def hash_password(password):
    """scrypt with a random salt. The cost is stored in the hash, so raising it later never locks anyone out."""
    salt=secrets.token_bytes(16);n=config.SCRYPT_N
    digest=hashlib.scrypt(password.encode(),salt=salt,n=n,r=8,p=1,dklen=32)
    return f'scrypt${n}${salt.hex()}${digest.hex()}'

def verify_password(password,stored):
    try:
        parts=stored.split('$')
        if len(parts)==4:_,n,salt,digest=parts;n=int(n)
        else:_,salt,digest=parts;n=2**14            # hashes written before the cost was stored
        if n<16 or n&(n-1):return False
        calc=hashlib.scrypt(password.encode(),salt=bytes.fromhex(salt),n=n,r=8,p=1,dklen=32)
        return hmac.compare_digest(calc.hex(),digest)
    except (ValueError,TypeError):return False

_DUMMY=[]

def dummy_hash():
    if not _DUMMY:_DUMMY.append(hash_password('not-a-real-password'))
    return _DUMMY[0]

def public_user(r):
    return {'id':r['id'],'username':r['username'],'display_name':r['display_name'],'role':r['role'],'active':bool(r['active']),'created_at':r['created_at'],'delegate_to':r['delegate_to'] if r['delegate_until']>=today() else '','delegate_until':r['delegate_until'] if r['delegate_until']>=today() else '','email':r['email'],'digest_optin':bool(r['digest_optin']),'digest_sent':r['digest_sent']}

def user_count():
    with db() as c:return c.execute('SELECT COUNT(*) FROM users').fetchone()[0]

def check_password_rules(password):
    if not isinstance(password,str) or not 10<=len(password)<=200:raise ValueError('Password must be 10 to 200 characters')

def create_user(row,bootstrap=False):
    username=str(row.get('username','')).strip()
    if not USERNAME_RE.fullmatch(username):raise ValueError('Username must be 3-32 letters, numbers, dots, dashes or underscores')
    display=str(row.get('display_name') or username).strip()[:60]
    role='admin' if bootstrap else str(row.get('role','member'))
    if role not in ROLES:raise ValueError('Role must be viewer, member, manager or admin')
    check_password_rules(row.get('password'))
    hashed=hash_password(row['password'])
    with config.LOCK,db() as c:
        if bootstrap and c.execute('SELECT COUNT(*) FROM users').fetchone()[0]:raise ValueError('Accounts are already set up')
        try:cur=c.execute('INSERT INTO users(username,display_name,role,password_hash,active,created_at) VALUES(?,?,?,?,1,?)',(username,display,role,hashed,now()))
        except sqlite3.IntegrityError as e:raise ValueError('That username is already taken') from e
        audit(c,'user_create','users',{'id':cur.lastrowid,'username':username,'role':role})
        return public_user(c.execute('SELECT * FROM users WHERE id=?',(cur.lastrowid,)).fetchone())

def list_users():
    with db() as c:return [public_user(r) for r in c.execute('SELECT * FROM users ORDER BY username COLLATE NOCASE')]

def update_user(ident,row):
    sets={}
    if 'display_name' in row:
        name=str(row['display_name']).strip()[:60]
        if not name:raise ValueError('Display name is required')
        sets['display_name']=name
    if 'role' in row:
        if row['role'] not in ROLES:raise ValueError('Role must be viewer, member, manager or admin')
        sets['role']=row['role']
    if 'email' in row:sets['email']=_clean_email(row['email'])
    if 'active' in row:sets['active']=1 if row['active'] in (True,1,'1','true','yes','on') else 0
    if row.get('password'):
        check_password_rules(row['password']);sets['password_hash']=hash_password(row['password'])
    if not sets:raise ValueError('Nothing to update')
    with config.LOCK,db() as c:
        u=c.execute('SELECT * FROM users WHERE id=?',(ident,)).fetchone()
        if not u:raise ValueError('User not found')
        new_role=sets.get('role',u['role']);new_active=sets.get('active',u['active'])
        if u['role']=='admin' and u['active'] and (new_role!='admin' or not new_active):
            if not c.execute("SELECT COUNT(*) FROM users WHERE role='admin' AND active=1 AND id!=?",(ident,)).fetchone()[0]:raise ValueError('At least one active admin is required')
        c.execute(f"UPDATE users SET {','.join(k+'=?' for k in sets)} WHERE id=?",tuple(sets.values())+(ident,))
        if not new_active or 'password_hash' in sets:c.execute('DELETE FROM sessions WHERE user_id=?',(ident,))
        audit(c,'user_update','users',{'id':ident,'changed':[k for k in sets if k!='password_hash']+(['password'] if 'password_hash' in sets else [])})
        return public_user(c.execute('SELECT * FROM users WHERE id=?',(ident,)).fetchone())

def _clean_email(value):
    value=str(value or '').strip()
    if value and (len(value)>120 or not EMAIL_RE.fullmatch(value)):raise ValueError('That does not look like an email address')
    return value

def set_profile(user,email,digest):
    """Your own email address and whether you want the daily digest."""
    require_account(user)
    address=_clean_email(email)
    with config.LOCK,db() as c:
        c.execute('UPDATE users SET email=?,digest_optin=? WHERE id=?',(address,1 if digest else 0,user['id']))
        audit(c,'profile_update','users',{'id':user['id'],'digest':bool(digest),'has_email':bool(address)})   # the address itself is not logged
        return public_user(c.execute('SELECT * FROM users WHERE id=?',(user['id'],)).fetchone())

def throttle_check(key):
    entry=FAILS.get(key)
    if not entry:return
    if time.time()>=entry[1]:FAILS.pop(key,None);return
    if entry[0]>=5:raise ValueError('Too many failed attempts. Please wait a minute and try again.')

def throttle_fail(key):
    count=FAILS.get(key,(0,0))[0]+1
    FAILS[key]=(count,time.time()+60)

def authenticate(username,password,ip=''):
    key=(ip,str(username).strip().lower())
    throttle_check(key)
    with db() as c:u=c.execute('SELECT * FROM users WHERE username=? COLLATE NOCASE AND active=1',(str(username).strip(),)).fetchone()
    ok=verify_password(str(password),u['password_hash'] if u else dummy_hash())
    if not (u and ok):
        throttle_fail(key);raise ValueError('Invalid username or password')
    FAILS.pop(key,None)
    return public_user(u)

def start_session(user_id):
    token=secrets.token_urlsafe(32)
    with config.LOCK,db() as c:
        c.execute('DELETE FROM sessions WHERE expires_at<?',(time.time(),))
        c.execute('INSERT INTO sessions(token_hash,user_id,expires_at,created_at) VALUES(?,?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),user_id,time.time()+SESSION_SECONDS,now()))
    return token

def session_user(token):
    if not token:return None
    with db() as c:
        r=c.execute('SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND s.expires_at>? AND u.active=1',(hashlib.sha256(token.encode()).hexdigest(),time.time())).fetchone()
    return public_user(r) if r else None

def end_session(token):
    if token:
        with config.LOCK,db() as c:c.execute('DELETE FROM sessions WHERE token_hash=?',(hashlib.sha256(token.encode()).hexdigest(),))

def require_account(user):
    if not user or user.get('open'):raise ValueError('Sign in with an account to do this')

def require_role(user,role):
    if not user or RANK[user['role']]<RANK[role]:raise Forbidden(f'This needs the {role} role or higher')

def change_password(user,current,new,keep_token=None):
    """Let people change their own password. Every other session is ended; the one making the change stays signed in."""
    require_account(user)
    key=('password',user['id'])
    throttle_check(key)
    check_password_rules(new)
    with config.LOCK,db() as c:
        row=c.execute('SELECT * FROM users WHERE id=?',(user['id'],)).fetchone()
        if not row or not verify_password(str(current),row['password_hash']):
            throttle_fail(key);raise ValueError('Your current password is not correct')
        FAILS.pop(key,None)
        if verify_password(new,row['password_hash']):raise ValueError('Choose a password you are not already using')
        c.execute('UPDATE users SET password_hash=? WHERE id=?',(hash_password(new),user['id']))
        keep=hashlib.sha256(keep_token.encode()).hexdigest() if keep_token else ''
        ended=c.execute('DELETE FROM sessions WHERE user_id=? AND token_hash!=?',(user['id'],keep)).rowcount
        audit(c,'password_change','users',{'id':user['id'],'other_sessions_ended':ended})
    return {'ok':True,'ended':ended}

def logout_all(user):
    require_account(user)
    with config.LOCK,db() as c:
        ended=c.execute('DELETE FROM sessions WHERE user_id=?',(user['id'],)).rowcount
        audit(c,'logout_all','users',{'id':user['id'],'sessions_ended':ended})
    return ended

def session_cookie(token,max_age=SESSION_SECONDS,secure=False):
    return f"{COOKIE}={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age={max_age}"+('; Secure' if secure else '')

def required_role(method,path):
    if method=='DELETE' and (path.startswith('/api/comments/') or path.startswith('/api/attachments/')):return 'member'      # the function checks it is your own comment
    if path in ('/api/auth/password','/api/auth/logout-all','/api/auth/profile','/api/digest/test'):return 'viewer'
    if path.startswith('/api/users'):return 'admin'
    if method=='GET':return 'admin' if path in ('/api/backup','/api/backup.zip','/api/backups') else 'viewer'
    if path in ('/api/automation/settings','/api/restore','/api/backups','/api/backups/restore'):return 'admin'
    if method=='DELETE':return 'manager'
    return 'member'

def check_access(method,path,user):
    """Raise AuthError / Forbidden unless this user may call this API path. Static files are always public."""
    if not path.startswith('/api/'):return
    if (method=='GET' and path in PUBLIC_GET) or (method=='POST' and path in PUBLIC_POST):return
    if not user:raise AuthError('Please sign in')
    if RANK[user['role']]<RANK[required_role(method,path)]:raise Forbidden(f"Your role ({user['role']}) is not allowed to do this")
