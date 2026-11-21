"""Comments on tasks, approvals and contracts, and the alerts they raise for the people involved."""
from datetime import datetime
from . import config
from .db import audit, db, now
from .accounts import Forbidden
from .approvals import delegators_of, identities, notifications

def _entity(entity):
    if entity not in config.COMMENT_ENTITIES:raise ValueError('Comments are available on tasks, approvals and contracts')
    return entity

def _name(user):return user['username'] if user and not user.get('open') else 'local'

def list_comments(entity,ident):
    entity=_entity(entity)
    with db() as c:
        rows=c.execute(f"SELECT m.id,m.author,COALESCE(u.display_name,m.author) AS author_name,m.body,m.at FROM comments m LEFT JOIN users u ON u.username=m.author COLLATE NOCASE WHERE m.entity=? AND m.entity_id=? ORDER BY m.id LIMIT 500",(entity,int(ident))).fetchall()
    return [dict(r) for r in rows]

def comment_counts(entity):
    entity=_entity(entity)
    with db() as c:return {str(r[0]):r[1] for r in c.execute('SELECT entity_id,COUNT(*) FROM comments WHERE entity=? GROUP BY entity_id',(entity,))}

def add_comment(entity,ident,body,user=None):
    entity=_entity(entity)
    body=str(body or '').strip()
    if not body:raise ValueError('Write something first')
    if len(body)>2000:raise ValueError('Comments can be at most 2,000 characters')
    with config.LOCK,db() as c:
        if not c.execute(f'SELECT 1 FROM {entity} WHERE id=?',(int(ident),)).fetchone():raise ValueError('Record not found')
        cur=c.execute('INSERT INTO comments(entity,entity_id,author,body,at) VALUES(?,?,?,?,?)',(entity,int(ident),_name(user),body,now()))
        audit(c,'comment',entity,{'id':int(ident),'comment_id':cur.lastrowid,'length':len(body)})   # the text itself is not copied into the audit log
    return {'ok':True,'id':cur.lastrowid}

def delete_comment(comment_id,user=None):
    with config.LOCK,db() as c:
        row=c.execute('SELECT * FROM comments WHERE id=?',(int(comment_id),)).fetchone()
        if not row:raise ValueError('Comment not found')
        ids=identities(user)
        if ids is not None and user['role']!='admin' and row['author'].lower() not in ids:raise Forbidden('You can only delete your own comments')
        c.execute('DELETE FROM comments WHERE id=?',(row['id'],))
        audit(c,'comment_delete',row['entity'],{'id':row['entity_id'],'comment_id':row['id']})
    return {'ok':True}

def _days_old(iso):
    try:
        moment=datetime.fromisoformat(iso)
        return max(0,(datetime.now(moment.tzinfo)-moment).days)
    except (TypeError,ValueError):return 99

def _events(c):
    """Recent comments and attachments as one list of things that happened to a record."""
    out=[]
    for m in c.execute('SELECT * FROM comments ORDER BY id DESC LIMIT 300'):
        excerpt=m['body'] if len(m['body'])<=70 else m['body'][:67]+'...'
        out.append({'key':f"comment:{m['id']}",'entity':m['entity'],'entity_id':m['entity_id'],'author':m['author'],'at':m['at'],'what':f'commented: \u201c{excerpt}\u201d'})
    for a in c.execute('SELECT * FROM attachments ORDER BY id DESC LIMIT 100'):
        out.append({'key':f"attachment:{a['id']}",'entity':a['entity'],'entity_id':a['entity_id'],'author':a['uploader'],'at':a['at'],'what':f"attached \u201c{a['name']}\u201d"})
    return out

def comment_notifications(user):
    """Recent comments, from other people, on requests, tasks and contracts you are involved in."""
    ids=identities(user)
    if ids is None:return []                                    # single-user mode has no "other people"
    mine=ids|delegators_of(user)
    out=[]
    with db() as c:
        names={r['username'].lower():r['display_name'] for r in c.execute('SELECT username,display_name FROM users')}
        for m in _events(c):
            if _days_old(m['at'])>3 or m['author'].lower() in ids:continue
            if m['entity']=='approvals':
                row=c.execute('SELECT title,requester FROM approvals WHERE id=?',(m['entity_id'],)).fetchone()
                if not row:continue
                people={str(row['requester']).strip().lower()}|{str(s[0]).strip().lower() for s in c.execute('SELECT approver FROM approval_steps WHERE approval_id=?',(m['entity_id'],))}
                title,page=row['title'],'approvals'
            elif m['entity']=='tasks':
                row=c.execute('SELECT title,owner FROM tasks WHERE id=?',(m['entity_id'],)).fetchone()
                if not row:continue
                people,title,page={str(row['owner']).strip().lower()},row['title'],'tasks'
            else:
                row=c.execute('SELECT contract,owner FROM contracts WHERE id=?',(m['entity_id'],)).fetchone()
                if not row:continue
                people,title,page={str(row['owner']).strip().lower()},row['contract'],'contracts'
            if not (people&mine):continue
            who=names.get(m['author'].lower(),m['author'])
            out.append({'key':m['key'],'kind':'comment','severity':'low','title':title,'detail':f"{who} {m['what']}",'page':page})
    return out[:20]

def all_notifications(user=None):
    """Everything that needs attention: approvals, deadlines, outcomes and new comments, most urgent first."""
    order={'high':0,'medium':1,'low':2}
    items=notifications(user)+comment_notifications(user)
    items.sort(key=lambda i:(order[i['severity']],i['title'].lower()))
    return items[:50]
