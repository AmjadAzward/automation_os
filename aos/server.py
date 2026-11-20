"""The HTTP server: request guards, authentication, routing and static files."""
from . import config
import base64
import hmac
import json
import sqlite3
import threading
import time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler
from http.server import ThreadingHTTPServer
from urllib.parse import parse_qs
from urllib.parse import urlparse
from .db import CTX, audit, db, init, read_table, today
from .settings import automation_runs, automation_settings, save_automation_settings
from .accounts import AuthError, COOKIE, Forbidden, authenticate, change_password, check_access, create_user, end_session, list_users, logout_all, require_role, session_cookie, session_user, start_session, update_user, user_count
from .comments import add_comment, all_notifications, comment_counts, delete_comment, list_comments
from .approvals import approvals_list, decide_approval, delete_approval_guard, edit_approval_guard, notifications, people, prepare_approval_payload, set_delegation, withdraw_approval
from .records import add_row, bulk_action, bulk_exception_status, delete_row, import_csv, search, update_row, update_status
from .reports import audit_facets, audit_query, trends, attention_queue, compare_quotes, executive_report, insights, overview
from .backups import auto_backup, backup_export, list_backups, restore_backup, restore_stored_backup
from .automation import ai, scan, scheduler

_WRITES={}
def allow_write(key):
    """Sliding one-minute window of changes per client, so a runaway script or a stuck loop cannot flood the database."""
    limit=config.WRITE_LIMIT
    if not limit:return True
    t=time.time()
    recent=[x for x in _WRITES.get(key,[]) if t-x<60]
    if len(recent)>=limit:
        _WRITES[key]=recent;return False
    recent.append(t);_WRITES[key]=recent
    if len(_WRITES)>5000:
        for k in [k for k,v in _WRITES.items() if not v or t-v[-1]>60]:_WRITES.pop(k,None)
    return True

class Handler(BaseHTTPRequestHandler):
    def log_message(self,fmt,*args):print('[HTTP]',fmt%args)
    def send(self,obj,status=200,headers=None):
        buf=json.dumps(obj,ensure_ascii=False).encode()
        self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('X-Content-Type-Options','nosniff');self.send_header('Cache-Control','no-store')
        for k,v in (headers or {}).items():self.send_header(k,v)
        self.send_header('Content-Length',str(len(buf)));self.end_headers();self.wfile.write(buf)
    def fail(self,e):
        if isinstance(e,AuthError):return self.send({'error':str(e),'login':True},401)
        if isinstance(e,Forbidden):return self.send({'error':str(e)},403)
        self.send({'error':str(e)},400 if isinstance(e,(ValueError,sqlite3.IntegrityError)) else 500)
    def secure(self):
        """True when a TLS-terminating proxy told us the browser is on HTTPS, so the cookie can be marked Secure."""
        return (self.headers.get('X-Forwarded-Proto') or '').split(',')[0].strip().lower()=='https'
    def session_token(self):
        morsel=SimpleCookie(self.headers.get('Cookie') or '').get(COOKIE)
        return morsel.value if morsel else None
    def begin(self,method):
        """Identify the caller, enforce role permissions and tag audit entries. Returns the request path."""
        path=urlparse(self.path).path
        if user_count()==0:self.user={'id':0,'username':'local','display_name':'Local user','role':'admin','open':True}
        else:self.user=session_user(self.session_token())
        CTX.actor=self.user['username'] if self.user else ''
        check_access(method,path,self.user)
        return path
    def deny(self,code,text,extra=None):
        buf=json.dumps({'error':text}).encode()
        self.send_response(code)
        for k,v in (extra or {}).items():self.send_header(k,v)
        self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(buf)));self.end_headers();self.wfile.write(buf)
        return False
    def guard(self,write):
        """Reject DNS-rebinding hosts, cross-site writes, non-JSON bodies and (optionally) unauthenticated requests."""
        host=(self.headers.get('Host') or '').lower()
        if config.HOST in config.LOOPBACK:
            name=host[1:host.index(']')] if host.startswith('[') and ']' in host else host.rsplit(':',1)[0]
            if name not in config.LOOPBACK:return self.deny(403,'Invalid host header')
        if config.AUTH:
            given=self.headers.get('Authorization') or '';ok=False
            if given.startswith('Basic '):
                try:ok=hmac.compare_digest(base64.b64decode(given[6:]).decode('utf-8','replace').partition(':')[2].encode(),config.AUTH.encode())
                except Exception:ok=False
            if not ok:return self.deny(401,'Authentication required',{'WWW-Authenticate':'Basic realm="Automation OS"'})
        if write:
            origin=self.headers.get('Origin')
            if origin is not None and urlparse(origin).netloc.lower()!=host:return self.deny(403,'Cross-origin request blocked')
            if self.command in ('POST','PUT') and not (self.headers.get('Content-Type') or '').lower().startswith('application/json'):return self.deny(415,'Content-Type must be application/json')
            if not allow_write((self.client_address[0],self.session_token() or '')):return self.deny(429,'Too many changes in a short time. Please wait a moment.',{'Retry-After':'30'})
        return True
    def json_body(self):
        length=int(self.headers.get('Content-Length','0'))
        if not 0<length<=config.MAX_BODY:raise ValueError('Request body missing or too large')
        data=json.loads(self.rfile.read(length))
        if not isinstance(data,dict):raise ValueError('JSON object required')
        return data
    def do_GET(self):
        try:
            if not self.guard(False):return
            path=self.begin('GET')
            if path in ('/','/index.html'):
                data=(config.ROOT/'static'/'index.html').read_bytes()
                self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.send_header('X-Content-Type-Options','nosniff');self.send_header('Content-Security-Policy',"default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'");self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data);return
            if path=='/app.js':
                data=(config.ROOT/'static'/'app.js').read_bytes();self.send_response(200);self.send_header('Content-Type','text/javascript; charset=utf-8');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data);return
            icons={'/favicon.svg':('favicon.svg','image/svg+xml'),'/favicon.ico':('favicon-32.png','image/png'),'/favicon-32.png':('favicon-32.png','image/png'),'/favicon-180.png':('favicon-180.png','image/png')}
            if path in icons:
                name,ctype=icons[path];data=(config.ROOT/'static'/name).read_bytes();self.send_response(200);self.send_header('Content-Type',ctype);self.send_header('Cache-Control','public, max-age=86400');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data);return
            if path=='/api/auth/me':
                n=user_count();return self.send({'accounts':n>0,'user':self.user if n>0 else None})
            if path=='/api/users':return self.send(list_users())
            if path=='/api/approvals':return self.send(approvals_list(self.user))
            if path in ('/api/audit','/api/trends'):
                q=parse_qs(urlparse(self.path).query);g=lambda k:(q.get(k) or [''])[0]
                if path=='/api/trends':return self.send(trends(g('weeks') or 8))
                return self.send(audit_query(g('actor'),g('action'),g('entity'),g('since'),g('until'),g('limit') or 500))
            if path=='/api/audit/facets':return self.send(audit_facets())
            if path in ('/api/comments','/api/comments/counts'):
                q=parse_qs(urlparse(self.path).query);g=lambda k:(q.get(k) or [''])[0]
                if path=='/api/comments/counts':return self.send(comment_counts(g('entity')))
                return self.send(list_comments(g('entity'),g('id') or 0))
            if path=='/api/search':return self.send(search((parse_qs(urlparse(self.path).query).get('q') or [''])[0]))
            if path=='/api/backups':return self.send(list_backups())
            if path=='/api/overview':
                data=overview();data['awaiting_me']=sum(1 for a in approvals_list(self.user) if a['mine']);return self.send(data)
            if path=='/api/people':return self.send(people())
            if path=='/api/notifications':return self.send(all_notifications(self.user))
            if path=='/api/insights':return self.send(insights())
            if path=='/api/attention':return self.send(attention_queue())
            if path=='/api/reports/executive':return self.send(executive_report())
            if path=='/api/backup':return self.send(backup_export())
            if path=='/api/automation/settings':return self.send(automation_settings())
            if path=='/api/automation/runs':return self.send(automation_runs())
            if path=='/api/comparison':return self.send(compare_quotes())
            if path=='/api/health':return self.send({'ok':True,'service':'Automation OS','date':today()})
            if path.startswith('/api/'):
                table=path.split('/')[-1]
                return self.send(read_table(table))
            self.send({'error':'Not found'},404)
        except Exception as e:self.fail(e)
    def do_POST(self):
        try:
            if not self.guard(True):return
            path=self.begin('POST')
            obj=self.json_body()
            if path=='/api/auth/login':
                user=authenticate(obj.get('username',''),obj.get('password',''),self.client_address[0]);CTX.actor=user['username']
                with config.LOCK,db() as c:audit(c,'login','users',{'username':user['username']})
                return self.send({'user':user},headers={'Set-Cookie':session_cookie(start_session(user['id']),secure=self.secure())})
            if path=='/api/auth/setup':
                user=create_user(obj,bootstrap=True);return self.send({'user':user},headers={'Set-Cookie':session_cookie(start_session(user['id']),secure=self.secure())})
            if path=='/api/auth/logout':
                end_session(self.session_token());return self.send({'ok':True},headers={'Set-Cookie':session_cookie('',0,secure=self.secure())})
            if path=='/api/auth/delegate':return self.send(set_delegation(self.user,obj.get('delegate',''),obj.get('until','')))
            if path=='/api/comments':return self.send(add_comment(obj.get('entity'),obj.get('id'),obj.get('body'),self.user))
            if path=='/api/bulk':
                if obj.get('action')=='delete':require_role(self.user,'manager')
                return self.send(bulk_action(obj.get('table'),obj.get('ids'),obj.get('action'),obj.get('status')))
            if path=='/api/auth/password':return self.send(change_password(self.user,obj.get('current',''),obj.get('new',''),self.session_token()))
            if path=='/api/auth/logout-all':
                ended=logout_all(self.user);return self.send({'ok':True,'ended':ended},headers={'Set-Cookie':session_cookie('',0,secure=self.secure())})
            if path=='/api/users':return self.send(create_user(obj))
            if path=='/api/scan':return self.send(scan())
            if path=='/api/automation/settings':return self.send(save_automation_settings(obj))
            if path=='/api/ai':return self.send(ai(obj.get('prompt','')))
            if path=='/api/import':return self.send(import_csv(obj.get('table'),obj.get('csv'),bool(obj.get('dry_run')),obj.get('skip_duplicates',True) is not False))
            if path=='/api/status':return self.send(update_status(obj.get('table'),int(obj.get('id')),obj.get('status')))
            if path=='/api/exceptions/bulk':return self.send(bulk_exception_status(obj.get('ids'),obj.get('status')))
            if path=='/api/backups':return self.send({'ok':True,'name':auto_backup(force=True)})
            if path=='/api/backups/restore':return self.send(restore_stored_backup(obj.get('name')))
            if path=='/api/restore':return self.send(restore_backup(obj))
            if path=='/api/approvals/withdraw':return self.send(withdraw_approval(int(obj.get('id')),self.user,obj.get('reason','')))
            if path=='/api/approvals/decision':return self.send(decide_approval(int(obj.get('id')),obj.get('decision'),obj.get('comment',''),self.user))
            if path.startswith('/api/'):
                table=path.split('/')[-1]
                if table=='approvals':prepare_approval_payload(obj,self.user)
                return self.send(add_row(table,obj))
            self.send({'error':'Not found'},404)
        except Exception as e:self.fail(e)
    def do_PUT(self):
        try:
            if not self.guard(True):return
            parts=self.begin('PUT').strip('/').split('/')
            if len(parts)!=3 or parts[0]!='api':raise ValueError('Invalid update path')
            if parts[1]=='users':return self.send(update_user(int(parts[2]),self.json_body()))
            body=self.json_body()
            if parts[1]=='approvals':edit_approval_guard(int(parts[2]),body,self.user)
            return self.send(update_row(parts[1],int(parts[2]),body))
        except Exception as e:self.fail(e)
    def do_DELETE(self):
        try:
            if not self.guard(True):return
            parts=self.begin('DELETE').strip('/').split('/')
            if len(parts)!=3 or parts[0]!='api':raise ValueError('Invalid delete path')
            if parts[1]=='comments':return self.send(delete_comment(int(parts[2]),self.user))
            if parts[1]=='approvals':delete_approval_guard(int(parts[2]),self.user)
            return self.send(delete_row(parts[1],int(parts[2])))
        except Exception as e:self.fail(e)

def main():
    init()
    threading.Thread(target=scheduler,daemon=True).start()
    server=ThreadingHTTPServer((config.HOST,config.PORT),Handler)
    if config.HOST not in config.LOOPBACK and not config.AUTH:print('WARNING: listening on a non-local address without AUTOMATION_PASSWORD. Anyone on your network can read and change data.')
    if config.SCRYPT_N<16384:print('WARNING: AUTOMATION_SCRYPT_N is below the safe default; use it for tests only.')
    print(f'\nAutomation OS running at http://{config.HOST}:{config.PORT}\nPress Ctrl+C to stop. Local only; do NOT expose directly to the internet.\n')
    try:server.serve_forever()
    except KeyboardInterrupt:print('\nStopped.')
    finally:server.server_close()
