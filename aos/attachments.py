"""Files attached to tasks, approvals and contracts.

Safety design: files are stored under random names (the uploaded name is only a label), the type is never trusted,
downloads are always served as a plain download with `nosniff` and a sandboxing CSP so nothing can run in the browser,
and a short list of executable and scriptable types is refused outright.
"""
import base64
import binascii
import os
import re
import secrets
from urllib.parse import quote
from . import config
from .db import audit, db, now
from .accounts import Forbidden
from .approvals import identities

BLOCKED = {'.exe', '.bat', '.cmd', '.com', '.scr', '.msi', '.dll', '.ps1', '.vbs', '.js', '.jse', '.wsf', '.jar', '.sh', '.app', '.html', '.htm', '.svg', '.hta', '.lnk'}
STORED_RE = re.compile(r'[0-9a-f]{32}')


def _entity(entity):
    if entity not in config.COMMENT_ENTITIES:
        raise ValueError('Files can be attached to tasks, approvals and contracts')
    return entity


def clean_name(name):
    name = re.split(r'[\\/]', str(name or ''))[-1]
    name = re.sub(r'[\x00-\x1f\x7f"<>|?*:]', '', name).strip(' .')[:120]
    if not name:
        raise ValueError('The file needs a name')
    return name


def _who(user):
    return user['username'] if user and not user.get('open') else 'local'


def list_attachments(entity, ident):
    entity = _entity(entity)
    with db() as c:
        rows = c.execute('SELECT id,name,size,uploader,at FROM attachments WHERE entity=? AND entity_id=? ORDER BY id LIMIT 200', (entity, int(ident))).fetchall()
    return [dict(r) for r in rows]


def attachment_counts(entity):
    entity = _entity(entity)
    with db() as c:
        return {str(r[0]): r[1] for r in c.execute('SELECT entity_id,COUNT(*) FROM attachments WHERE entity=? GROUP BY entity_id', (entity,))}


def add_attachment(entity, ident, name, data_b64, user=None):
    entity = _entity(entity)
    name = clean_name(name)
    if os.path.splitext(name)[1].lower() in BLOCKED:
        raise ValueError('That type of file cannot be attached')
    try:
        data = base64.b64decode(str(data_b64 or ''), validate=True)
    except (binascii.Error, ValueError):
        raise ValueError('The file could not be read')
    if not data:
        raise ValueError('The file is empty')
    if len(data) > config.MAX_ATTACHMENT:
        raise ValueError(f'Files can be at most {config.MAX_ATTACHMENT // 1_000_000} MB')
    stored = secrets.token_hex(16)
    with config.LOCK, db() as c:
        if not c.execute(f'SELECT 1 FROM {entity} WHERE id=?', (int(ident),)).fetchone():
            raise ValueError('Record not found')
        if c.execute('SELECT COUNT(*) FROM attachments WHERE entity=? AND entity_id=?', (entity, int(ident))).fetchone()[0] >= config.MAX_ATTACHMENTS_PER_RECORD:
            raise ValueError(f'A record can have at most {config.MAX_ATTACHMENTS_PER_RECORD} files')
        config.ATTACH_DIR.mkdir(parents=True, exist_ok=True)
        path = config.ATTACH_DIR / stored
        path.write_bytes(data)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        cur = c.execute('INSERT INTO attachments(entity,entity_id,name,stored,size,uploader,at) VALUES(?,?,?,?,?,?,?)', (entity, int(ident), name, stored, len(data), _who(user), now()))
        audit(c, 'attach', entity, {'id': int(ident), 'attachment_id': cur.lastrowid, 'name': name, 'size': len(data)})
    return {'ok': True, 'id': cur.lastrowid}


def read_attachment(attachment_id):
    """(display name, bytes) for a download."""
    with db() as c:
        row = c.execute('SELECT name,stored FROM attachments WHERE id=?', (int(attachment_id),)).fetchone()
    if not row or not STORED_RE.fullmatch(row['stored']):
        raise ValueError('File not found')
    try:
        return row['name'], (config.ATTACH_DIR / row['stored']).read_bytes()
    except OSError:
        raise ValueError('File not found')


def download_headers(name, size):
    ascii_name = re.sub(r'[^A-Za-z0-9._ -]', '_', name)
    return {
        'Content-Type': 'application/octet-stream',
        'Content-Disposition': f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{quote(name)}',
        'X-Content-Type-Options': 'nosniff',
        'Content-Security-Policy': "sandbox; default-src 'none'",
        'Cache-Control': 'no-store',
        'Content-Length': str(size),
    }


def _unlink(stored):
    for s in stored:
        if STORED_RE.fullmatch(s or ''):
            try:
                (config.ATTACH_DIR / s).unlink()
            except OSError:
                pass


def delete_attachment(attachment_id, user=None):
    with config.LOCK, db() as c:
        row = c.execute('SELECT * FROM attachments WHERE id=?', (int(attachment_id),)).fetchone()
        if not row:
            raise ValueError('File not found')
        ids = identities(user)
        if ids is not None and user['role'] not in ('admin', 'manager') and row['uploader'].lower() not in ids:
            raise Forbidden('You can only remove files you attached')
        c.execute('DELETE FROM attachments WHERE id=?', (row['id'],))
        audit(c, 'detach', row['entity'], {'id': row['entity_id'], 'attachment_id': row['id'], 'name': row['name']})
    _unlink([row['stored']])
    return {'ok': True}


def purge_for_records(c, entity, idents):
    """Remove the attachment rows of deleted records inside the caller's transaction; returns stored names to unlink afterwards."""
    if not idents:
        return []
    marks = ','.join('?' * len(idents))
    stored = [r[0] for r in c.execute(f'SELECT stored FROM attachments WHERE entity=? AND entity_id IN ({marks})', [entity, *idents])]
    c.execute(f'DELETE FROM attachments WHERE entity=? AND entity_id IN ({marks})', [entity, *idents])
    return stored


def unlink_stored(stored):
    _unlink(stored)
