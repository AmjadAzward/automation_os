"""SQLite access, the schema and migrations, the audit trail and the per-request context."""
from . import config
import json
import sqlite3
import threading
from datetime import datetime
from decimal import Decimal
from decimal import InvalidOperation

SCHEMA='''
CREATE TABLE IF NOT EXISTS tasks(id INTEGER PRIMARY KEY AUTOINCREMENT,title TEXT NOT NULL,department TEXT NOT NULL DEFAULT 'General',owner TEXT DEFAULT '',due_date TEXT DEFAULT '',status TEXT NOT NULL DEFAULT 'open',priority TEXT NOT NULL DEFAULT 'medium',source TEXT DEFAULT 'manual',created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS quotations(id INTEGER PRIMARY KEY AUTOINCREMENT,rfq TEXT NOT NULL,supplier TEXT NOT NULL,item TEXT NOT NULL,quantity REAL NOT NULL DEFAULT 1,unit_price TEXT NOT NULL,currency TEXT NOT NULL DEFAULT 'USD',lead_days INTEGER DEFAULT 0,terms TEXT DEFAULT '',created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS contracts(id INTEGER PRIMARY KEY AUTOINCREMENT,contract TEXT NOT NULL,counterparty TEXT DEFAULT '',obligation TEXT NOT NULL,owner TEXT DEFAULT '',due_date TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'open',created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS tariffs(id INTEGER PRIMARY KEY AUTOINCREMENT,service TEXT NOT NULL,customer TEXT NOT NULL DEFAULT '*',currency TEXT NOT NULL DEFAULT 'USD',rate TEXT NOT NULL,unit TEXT DEFAULT 'each',effective_from TEXT DEFAULT '',UNIQUE(service,customer,effective_from));
CREATE TABLE IF NOT EXISTS transactions(id INTEGER PRIMARY KEY AUTOINCREMENT,ref TEXT NOT NULL,service TEXT NOT NULL,customer TEXT NOT NULL,billed TEXT NOT NULL,units TEXT NOT NULL DEFAULT '1',currency TEXT NOT NULL DEFAULT 'USD',date TEXT DEFAULT '',created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS exceptions(id INTEGER PRIMARY KEY AUTOINCREMENT,fingerprint TEXT NOT NULL UNIQUE,kind TEXT NOT NULL,entity TEXT NOT NULL,details TEXT NOT NULL,severity TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'open',created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY AUTOINCREMENT,action TEXT NOT NULL,entity TEXT NOT NULL,details TEXT NOT NULL,at TEXT NOT NULL,actor TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS automation_runs(id INTEGER PRIMARY KEY AUTOINCREMENT,started_at TEXT NOT NULL,finished_at TEXT NOT NULL,detected INTEGER NOT NULL DEFAULT 0,created INTEGER NOT NULL DEFAULT 0,resolved INTEGER NOT NULL DEFAULT 0,trigger TEXT NOT NULL DEFAULT 'manual');
CREATE TABLE IF NOT EXISTS recurring_tasks(id INTEGER PRIMARY KEY AUTOINCREMENT,title TEXT NOT NULL,department TEXT NOT NULL DEFAULT 'General',owner TEXT DEFAULT '',priority TEXT NOT NULL DEFAULT 'medium',frequency TEXT NOT NULL DEFAULT 'weekly',next_due TEXT NOT NULL,active TEXT NOT NULL DEFAULT 'yes',created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS approvals(id INTEGER PRIMARY KEY AUTOINCREMENT,title TEXT NOT NULL,category TEXT NOT NULL DEFAULT 'Operational',requester TEXT DEFAULT '',approver TEXT DEFAULT '',amount TEXT DEFAULT '0',currency TEXT NOT NULL DEFAULT 'USD',rationale TEXT DEFAULT '',status TEXT NOT NULL DEFAULT 'pending',decision_comment TEXT DEFAULT '',created_at TEXT NOT NULL,decided_at TEXT DEFAULT '',second_approver TEXT DEFAULT '',previous_id INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS approval_steps(id INTEGER PRIMARY KEY AUTOINCREMENT,approval_id INTEGER NOT NULL,stage INTEGER NOT NULL,approver TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'pending',comment TEXT DEFAULT '',decided_by TEXT DEFAULT '',decided_at TEXT DEFAULT '',acting_for TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY AUTOINCREMENT,username TEXT NOT NULL UNIQUE COLLATE NOCASE,display_name TEXT NOT NULL,role TEXT NOT NULL DEFAULT 'member',password_hash TEXT NOT NULL,active INTEGER NOT NULL DEFAULT 1,created_at TEXT NOT NULL,delegate_to TEXT NOT NULL DEFAULT '',delegate_until TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY,user_id INTEGER NOT NULL,expires_at REAL NOT NULL,created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_tasks_due ON tasks(due_date,status);
CREATE INDEX IF NOT EXISTS idx_contracts_due ON contracts(due_date,status);
CREATE INDEX IF NOT EXISTS idx_transactions_service ON transactions(service,customer);
'''

def now():return datetime.now().astimezone().isoformat(timespec='seconds')

def today():return datetime.now().date().isoformat()

def money(v):
    try: return Decimal(str(v).replace(',','').strip())
    except (InvalidOperation,ValueError): raise ValueError('Invalid monetary value')

def db():
    c=sqlite3.connect(config.DB,timeout=15)
    c.row_factory=sqlite3.Row
    c.execute('PRAGMA foreign_keys=ON')
    c.execute('PRAGMA busy_timeout=15000')
    c.execute('PRAGMA synchronous=NORMAL')   # with WAL this is crash-safe and avoids a disk sync on every commit
    return c

def migrate(c):
    """Bring databases created by older versions up to the current schema."""
    cols=lambda t:{r[1] for r in c.execute(f'PRAGMA table_info({t})')}
    if 'actor' not in cols('audit'):c.execute("ALTER TABLE audit ADD COLUMN actor TEXT NOT NULL DEFAULT ''")
    if 'previous_id' not in cols('approvals'):c.execute("ALTER TABLE approvals ADD COLUMN previous_id INTEGER NOT NULL DEFAULT 0")
    if 'second_approver' not in cols('approvals'):c.execute("ALTER TABLE approvals ADD COLUMN second_approver TEXT DEFAULT ''")
    if 'acting_for' not in cols('approval_steps'):c.execute("ALTER TABLE approval_steps ADD COLUMN acting_for TEXT DEFAULT ''")
    if 'delegate_to' not in cols('users'):c.execute("ALTER TABLE users ADD COLUMN delegate_to TEXT NOT NULL DEFAULT ''")
    if 'delegate_until' not in cols('users'):c.execute("ALTER TABLE users ADD COLUMN delegate_until TEXT NOT NULL DEFAULT ''")
    for r in c.execute("SELECT id,approver FROM approvals WHERE status='pending' AND id NOT IN (SELECT approval_id FROM approval_steps)").fetchall():
        c.execute("INSERT INTO approval_steps(approval_id,stage,approver,status) VALUES(?,1,?,'pending')",(r['id'],r['approver']))

def init():
    config.DB.parent.mkdir(parents=True,exist_ok=True)
    with db() as c:
        c.execute('PRAGMA journal_mode=WAL')    # readers no longer block the writer; persists in the database file
        c.executescript(SCHEMA)
        migrate(c)
        for key,value in config.DEFAULT_SETTINGS.items():c.execute('INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)',(key,value))

def audit(c,action,entity,details):
    c.execute('INSERT INTO audit(action,entity,details,at,actor) VALUES(?,?,?,?,?)',(action,entity,json.dumps(details,ensure_ascii=False),now(),actor()))

def read_table(table,limit=500):
    if table not in ('tasks','quotations','contracts','tariffs','transactions','exceptions','audit','automation_runs','recurring_tasks','approvals','approval_steps'):raise ValueError('Invalid resource')
    with db() as c:return [dict(x) for x in c.execute(f'SELECT * FROM {table} ORDER BY id DESC LIMIT ?', (min(max(limit,1),3000),))]

CTX=threading.local()

def actor():return getattr(CTX,'actor','') or ''
