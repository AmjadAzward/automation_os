"""Trash: deleted records are kept for a while, with their comments and attached files, so a mistake can be undone."""
import json
from datetime import datetime
from . import config
from .db import actor, audit, db, now
from .attachments import STORED_RE, unlink_stored

TRASHABLE = {'tasks': 'title', 'contracts': 'contract', 'quotations': 'item', 'tariffs': 'service', 'transactions': 'ref', 'recurring_tasks': 'title', 'assets': 'name'}
KEEP_DAYS = 30


def capture(c, table, idents):
    """Copy records (and their comments and attachment entries) into the trash. Call inside the delete transaction, before deleting. Returns trash ids."""
    out = []
    for ident in idents:
        row = c.execute(f'SELECT * FROM {table} WHERE id=?', (ident,)).fetchone()
        if not row:
            continue
        payload = {'row': dict(row)}
        if table in config.COMMENT_ENTITIES:
            payload['comments'] = [dict(r) for r in c.execute('SELECT * FROM comments WHERE entity=? AND entity_id=?', (table, ident))]
            payload['attachments'] = [dict(r) for r in c.execute('SELECT * FROM attachments WHERE entity=? AND entity_id=?', (table, ident))]
        cur = c.execute('INSERT INTO trash(entity,entity_id,title,payload,deleted_by,deleted_at) VALUES(?,?,?,?,?,?)',
                        (table, ident, str(row[TRASHABLE[table]] or '')[:200], json.dumps(payload, ensure_ascii=False), _actor(), now()))
        out.append(cur.lastrowid)
    return out


def _actor():
    return actor() or 'local'


def _age_days(iso):
    try:
        moment = datetime.fromisoformat(iso)
        return max(0, (datetime.now(moment.tzinfo) - moment).days)
    except (TypeError, ValueError):
        return 0


def _files(payload):
    return [a['stored'] for a in payload.get('attachments', []) if STORED_RE.fullmatch(str(a.get('stored', '')))]


def trashed_files(c):
    """File names still needed by items in the trash (so cleanups never delete them)."""
    keep = set()
    for (raw,) in c.execute('SELECT payload FROM trash'):
        try:
            keep.update(_files(json.loads(raw)))
        except ValueError:
            pass
    return keep


def list_trash():
    purge_old()
    with db() as c:
        rows = c.execute('SELECT id,entity,entity_id,title,payload,deleted_by,deleted_at FROM trash ORDER BY id DESC LIMIT 500').fetchall()
    out = []
    for r in rows:
        try:
            files = len(_files(json.loads(r['payload'])))
        except ValueError:
            files = 0
        out.append({'id': r['id'], 'entity': r['entity'], 'title': r['title'], 'deleted_by': r['deleted_by'], 'deleted_at': r['deleted_at'],
                    'days_left': max(0, KEEP_DAYS - _age_days(r['deleted_at'])), 'files': files})
    return out


def restore_item(trash_id):
    with config.LOCK, db() as c:
        item = c.execute('SELECT * FROM trash WHERE id=?', (int(trash_id),)).fetchone()
        if not item or item['entity'] not in TRASHABLE:
            raise ValueError('That item is no longer in the trash')
        payload = json.loads(item['payload'])
        table = item['entity']
        cols = [r[1] for r in c.execute(f'PRAGMA table_info({table})')]
        row = {k: v for k, v in payload['row'].items() if k in cols}
        if c.execute(f'SELECT 1 FROM {table} WHERE id=?', (row.get('id'),)).fetchone():
            row.pop('id', None)                       # the old number was reused: take a new one
        keys = list(row)
        cur = c.execute(f"INSERT INTO {table}({','.join(keys)}) VALUES({','.join(['?'] * len(keys))})", [row[k] for k in keys])
        new_id = cur.lastrowid if 'id' not in row else row['id']
        for m in payload.get('comments', []):
            c.execute('INSERT INTO comments(entity,entity_id,author,body,at) VALUES(?,?,?,?,?)', (table, new_id, m['author'], m['body'], m['at']))
        restored_files = 0
        for a in payload.get('attachments', []):
            if STORED_RE.fullmatch(str(a.get('stored', ''))) and (config.ATTACH_DIR / a['stored']).is_file():
                c.execute('INSERT INTO attachments(entity,entity_id,name,stored,size,uploader,at) VALUES(?,?,?,?,?,?,?)',
                          (table, new_id, a['name'], a['stored'], a['size'], a['uploader'], a['at']))
                restored_files += 1
        c.execute('DELETE FROM trash WHERE id=?', (item['id'],))
        audit(c, 'restore_item', table, {'id': new_id, 'from_trash': item['id'], 'title': item['title']})
    return {'ok': True, 'id': new_id, 'entity': table, 'files': restored_files}


def _remove(c, rows):
    stored = []
    for r in rows:
        try:
            stored += _files(json.loads(r['payload']))
        except ValueError:
            pass
        c.execute('DELETE FROM trash WHERE id=?', (r['id'],))
    return stored


def delete_item(trash_id):
    """Remove one item for good, including its files."""
    with config.LOCK, db() as c:
        rows = c.execute('SELECT * FROM trash WHERE id=?', (int(trash_id),)).fetchall()
        if not rows:
            raise ValueError('That item is no longer in the trash')
        stored = _remove(c, rows)
        audit(c, 'trash_delete', rows[0]['entity'], {'from_trash': rows[0]['id'], 'title': rows[0]['title']})
    unlink_stored(stored)
    return {'ok': True}


def purge_old():
    """Forget items older than KEEP_DAYS. Called when the trash is listed and by the scheduler."""
    with config.LOCK, db() as c:
        old = [r for r in c.execute('SELECT * FROM trash') if _age_days(r['deleted_at']) >= KEEP_DAYS]
        if not old:
            return 0
        stored = _remove(c, old)
        audit(c, 'trash_purge', 'trash', {'items': len(old)})
    unlink_stored(stored)
    return len(old)
