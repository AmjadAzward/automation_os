"""Backup export, restore and the automatic daily backups."""
import base64
import binascii
import io
import os
from . import config
import json
import re
import sqlite3
import zipfile
from datetime import datetime
from .db import audit, db, now, read_table
from .settings import automation_settings, save_automation_settings
from .attachments import STORED_RE
from .trash import trashed_files

def backup_export():
    tables=('tasks','recurring_tasks','approvals','approval_steps','comments','attachments','quotations','contracts','tariffs','transactions','exceptions','audit','automation_runs')
    return {'format':'automation-os-backup','version':1,'exported_at':now(),'settings':automation_settings(),'data':{t:read_table(t,3000) for t in tables}}

RESTORE_TABLES=('tasks','recurring_tasks','approvals','approval_steps','comments','attachments','quotations','contracts','tariffs','transactions','exceptions','automation_runs')

def backup_zip():
    """One .zip holding backup.json and every attached file."""
    buf=io.BytesIO()
    with zipfile.ZipFile(buf,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('backup.json',json.dumps(backup_export(),ensure_ascii=False,indent=1))
        for row in read_table('attachments',3000):
            path=config.ATTACH_DIR/row['stored']
            if STORED_RE.fullmatch(row['stored']) and path.is_file():z.write(path,'attachments/'+row['stored'])
    return buf.getvalue()

def restore_zip(b64):
    """Restore from a backup .zip (sent as base64). Only backup.json and attachments/<random name> are accepted; sizes are capped."""
    try:raw=base64.b64decode(str(b64 or ''),validate=True)
    except (binascii.Error,ValueError):raise ValueError('The backup file could not be read')
    return restore_zip_bytes(raw)

def restore_zip_bytes(raw):
    try:z=zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile:raise ValueError('This is not a valid backup .zip')
    files={}
    with z:
        names=[i.filename for i in z.infolist()]
        for name in names:
            if name!='backup.json' and not (name.startswith('attachments/') and STORED_RE.fullmatch(name[12:])):raise ValueError('The backup .zip contains unexpected files')
        if 'backup.json' not in names:raise ValueError('The backup .zip has no backup.json')
        meta=z.open('backup.json').read(50_000_001)
        if len(meta)>50_000_000:raise ValueError('backup.json is too large')
        for name in names:
            if name=='backup.json':continue
            blob=z.open(name).read(config.MAX_ATTACHMENT+1)
            if len(blob)>config.MAX_ATTACHMENT:raise ValueError('The backup .zip contains an oversized file')
            files[name[12:]]=blob
    try:obj=json.loads(meta.decode('utf-8'))
    except (UnicodeDecodeError,json.JSONDecodeError):raise ValueError('backup.json could not be read')
    return restore_backup(obj,files)

def _tidy_attachments(files):
    """After a restore: put back files from a .zip, drop files nothing refers to, and count entries whose file is missing."""
    config.ATTACH_DIR.mkdir(parents=True,exist_ok=True)
    for stored,blob in files.items():
        p=config.ATTACH_DIR/stored
        if not p.exists():
            p.write_bytes(blob)
            try:os.chmod(p,0o600)
            except OSError:pass
    with db() as c:
        rows=[r[0] for r in c.execute('SELECT stored FROM attachments')]
        keep=set(rows)|trashed_files(c)
    for p in config.ATTACH_DIR.iterdir():
        if STORED_RE.fullmatch(p.name) and p.name not in keep:
            try:p.unlink()
            except OSError:pass
    return sum(1 for s in rows if not (config.ATTACH_DIR/s).is_file())

def restore_backup(obj,files=None):
    if not isinstance(obj,dict) or obj.get('format')!='automation-os-backup' or not isinstance(obj.get('data'),dict):raise ValueError('This is not an Automation OS backup file')
    data=obj['data'];counts={}
    for t in RESTORE_TABLES:
        if t in data and not isinstance(data[t],list):raise ValueError(f'Backup table {t} is malformed')
    try:_restore_tables(data,counts)
    except sqlite3.Error as e:raise ValueError(f'Backup contains invalid records, nothing was changed ({e})') from e
    restored,skipped=0,[]
    if isinstance(obj.get('settings'),dict):                 # settings are restored one by one; a bad value never blocks the data
        for key,value in obj['settings'].items():
            if key not in config.DEFAULT_SETTINGS:continue
            try:save_automation_settings({key:value});restored+=1
            except (ValueError,TypeError):skipped.append(key)
    missing=_tidy_attachments(files or {}) if 'attachments' in data else 0
    return {'ok':True,'restored':counts,'settings_restored':restored,'settings_skipped':skipped,'attachments_missing':missing}

def _restore_tables(data,counts):
    with config.LOCK,db() as c:
        for t in RESTORE_TABLES:
            if t not in data:continue
            cols=[r[1] for r in c.execute(f'PRAGMA table_info({t})')]
            c.execute(f'DELETE FROM {t}');n=0
            for row in data[t]:
                if not isinstance(row,dict):continue
                if t=='attachments' and not (STORED_RE.fullmatch(str(row.get('stored',''))) and row.get('entity') in config.COMMENT_ENTITIES):continue    # the stored name becomes a file path, so it must be one we made
                keys=[k for k in row if k in cols]
                if not keys:continue
                c.execute(f"INSERT INTO {t}({','.join(keys)}) VALUES({','.join(['?']*len(keys))})",[row[k] for k in keys]);n+=1
            counts[t]=n
        if 'approvals' in data and 'approval_steps' not in data:c.execute('DELETE FROM approval_steps')
        audit(c,'restore','backup',counts)

def auto_backup(force=False):
    """Write a .zip (records and attached files) to data/backups. One per day unless forced; keeps the newest BACKUP_KEEP."""
    config.BACKUP_DIR.mkdir(parents=True,exist_ok=True)
    stamp=datetime.now().strftime('%Y-%m-%d-%H%M%S') if force else datetime.now().strftime('%Y-%m-%d')
    path=config.BACKUP_DIR/f'backup-{stamp}.zip'
    if path.exists() or path.with_suffix('.json').exists():return None
    tmp=path.with_suffix('.tmp');tmp.write_bytes(backup_zip());tmp.replace(path)
    try:os.chmod(path,0o600);os.chmod(config.BACKUP_DIR,0o700)   # backups hold business data: owner-only where the OS supports it
    except OSError:pass
    for old in sorted(_stored(),key=lambda p:p.stat().st_mtime,reverse=True)[config.BACKUP_KEEP:]:old.unlink()
    return path.name

def _stored():
    """Stored backups: .zip (current) and .json (older versions of this app)."""
    return list(config.BACKUP_DIR.glob('backup-*.zip'))+list(config.BACKUP_DIR.glob('backup-*.json')) if config.BACKUP_DIR.exists() else []

def list_backups():
    if not config.BACKUP_DIR.exists():return []
    files=sorted(_stored(),key=lambda p:p.stat().st_mtime,reverse=True)
    return [{'name':p.name,'size':p.stat().st_size,'modified':datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec='seconds')} for p in files]

def restore_stored_backup(name):
    if not isinstance(name,str) or not re.fullmatch(r'backup-[0-9-]+\.(zip|json)',name):raise ValueError('Invalid backup name')
    path=config.BACKUP_DIR/name
    if not path.is_file():raise ValueError('Backup not found')
    try:
        if name.endswith('.zip'):return restore_zip_bytes(path.read_bytes())
        data=json.loads(path.read_text(encoding='utf-8'))
    except (OSError,json.JSONDecodeError) as e:raise ValueError('Backup file could not be read') from e
    return restore_backup(data)
