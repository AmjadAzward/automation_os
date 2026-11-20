"""Generic record create/read/update/delete, bulk changes, CSV import and search."""
from . import config
import csv
import io
import re
import sqlite3
from .db import audit, db, money, now
from .approvals import check_approval_rules, check_resubmission, create_steps

def add_row(table,row,dry_run=False):
    spec={
      'tasks':(['title','department','owner','due_date','status','priority'],['title']),
      'quotations':(['rfq','supplier','item','quantity','unit_price','currency','lead_days','terms'],['rfq','supplier','item','unit_price']),
      'contracts':(['contract','counterparty','obligation','owner','due_date','status'],['contract','obligation','due_date']),
      'tariffs':(['service','customer','currency','rate','unit','effective_from'],['service','rate']),
      'transactions':(['ref','service','customer','billed','units','currency','date'],['ref','service','customer','billed'])
      ,'recurring_tasks':(['title','department','owner','priority','frequency','next_due','active'],['title','frequency','next_due'])
      ,'approvals':(['title','category','requester','approver','second_approver','amount','currency','rationale','previous_id'],['title','requester','approver'])
    }
    if table not in spec:raise ValueError('Invalid resource')
    allowed,required=spec[table]
    payload={k:row[k] for k in allowed if k in row and row[k] is not None}
    for k in required:
        if not str(payload.get(k,'')).strip():raise ValueError(f'Missing: {k}')
    if table=='tasks' and payload.get('status','open') not in config.STATUSES:raise ValueError('Bad status')
    if table=='contracts' and payload.get('status','open') not in config.STATUSES:raise ValueError('Bad status')
    if table=='recurring_tasks' and payload.get('frequency') not in ('daily','weekly','monthly'):raise ValueError('Frequency must be daily, weekly or monthly')
    if table=='approvals':
        for k in ('amount','currency','category'):
            if not str(payload.get(k,'')).strip():payload.pop(k,None)
        payload['amount']=str(money(payload.get('amount','0')))
        check_approval_rules(payload)
        if payload.get('previous_id') in (None,'',0,'0'):payload.pop('previous_id',None)
        else:payload['previous_id']=check_resubmission(payload['previous_id'],payload['requester'])
    if table=='quotations':money(payload['unit_price']);payload['quantity']=float(payload.get('quantity') or 1)
    if table=='tariffs':money(payload['rate']);payload.setdefault('customer','*')
    if table=='transactions':money(payload['billed']);money(payload.get('units','1'))
    for date_field in ('due_date','next_due'):
        if date_field in payload and payload[date_field] and not re.fullmatch(r'\d{4}-\d{2}-\d{2}',str(payload[date_field])):raise ValueError('Date must be YYYY-MM-DD')
    if dry_run:return {'valid':True}
    if table != 'tariffs':payload['created_at']=now()
    cols=list(payload)
    qs=','.join(['?']*len(cols))
    with config.LOCK,db() as c:
        cur=c.execute(f"INSERT INTO {table}({','.join(cols)}) VALUES({qs})",tuple(str(payload[k]) if k not in ('quantity','lead_days') else payload[k] for k in cols))
        if table=='approvals':create_steps(c,cur.lastrowid,payload['approver'],payload.get('second_approver',''))
        audit(c,'create',table,{'id':cur.lastrowid,'values':payload})
        return {'id':cur.lastrowid}

def update_status(table,ident,status):
    if table not in ('tasks','contracts','exceptions') or status not in config.STATUSES:raise ValueError('Invalid status update')
    with config.LOCK,db() as c:
        r=c.execute(f'UPDATE {table} SET status=? WHERE id=?',(status,ident))
        if not r.rowcount:raise ValueError('Record not found')
        audit(c,'status_update',table,{'id':ident,'status':status})
    return {'ok':True}

def update_row(table,ident,row):
    spec={
      'tasks':['title','department','owner','due_date','status','priority'],
      'quotations':['rfq','supplier','item','quantity','unit_price','currency','lead_days','terms'],
      'contracts':['contract','counterparty','obligation','owner','due_date','status'],
      'tariffs':['service','customer','currency','rate','unit','effective_from'],
      'transactions':['ref','service','customer','billed','units','currency','date'],
      'recurring_tasks':['title','department','owner','priority','frequency','next_due','active'],
      'approvals':['title','category','requester','approver','second_approver','amount','currency','rationale']
    }
    if table not in spec:raise ValueError('Invalid resource')
    payload={k:row[k] for k in spec[table] if k in row}
    if not payload:raise ValueError('No editable fields supplied')
    if 'status' in payload and payload['status'] not in config.STATUSES:raise ValueError('Bad status')
    for k in ('unit_price','rate','billed','units'):
        if k in payload:money(payload[k])
    if table=='approvals':
        for k in ('amount','currency','category'):
            if k in payload and not str(payload[k]).strip():payload.pop(k)
        if not payload:raise ValueError('No editable fields supplied')
        if 'amount' in payload:payload['amount']=str(money(payload['amount']))
        for k in ('title','requester','approver'):
            if k in payload and not str(payload[k]).strip():raise ValueError(f'Missing: {k}')
    if 'due_date' in payload and payload['due_date'] and not re.fullmatch(r'\d{4}-\d{2}-\d{2}',str(payload['due_date'])):raise ValueError('Date must be YYYY-MM-DD')
    with config.LOCK,db() as c:
        existing=c.execute(f'SELECT * FROM {table} WHERE id=?',(ident,)).fetchone()
        if not existing:raise ValueError('Record not found')
        if table=='approvals':
            if existing['status']!='pending':raise ValueError('Decided requests cannot be edited')
            if c.execute("SELECT 1 FROM approval_steps WHERE approval_id=? AND status!='pending'",(ident,)).fetchone():raise ValueError('This request is already part-way through approval and can no longer be edited')
            check_approval_rules({**dict(existing),**payload})
        sets=','.join(f'{k}=?' for k in payload)
        c.execute(f'UPDATE {table} SET {sets} WHERE id=?',tuple(payload.values())+(ident,))
        if table=='approvals' and {'approver','second_approver'}&set(payload):
            now_row=c.execute('SELECT approver,second_approver FROM approvals WHERE id=?',(ident,)).fetchone();create_steps(c,ident,now_row['approver'],now_row['second_approver'] or '')
        audit(c,'update',table,{'id':ident,'values':payload})
    return {'ok':True}

def delete_row(table,ident):
    if table not in ('tasks','quotations','contracts','tariffs','transactions','recurring_tasks','approvals'):raise ValueError('Invalid resource')
    with config.LOCK,db() as c:
        row=c.execute(f'SELECT * FROM {table} WHERE id=?',(ident,)).fetchone()
        if not row:raise ValueError('Record not found')
        c.execute(f'DELETE FROM {table} WHERE id=?',(ident,))
        if table=='approvals':c.execute('DELETE FROM approval_steps WHERE approval_id=?',(ident,))
        audit(c,'delete',table,{'id':ident})
    return {'ok':True}

def bulk_exception_status(ids,status):
    if status not in config.STATUSES:raise ValueError('Invalid status')
    if not isinstance(ids,list) or not ids or len(ids)>200:raise ValueError('Select 1 to 200 exceptions')
    clean=[int(x) for x in ids]
    with config.LOCK,db() as c:
        qs=','.join('?' for _ in clean);cur=c.execute(f'UPDATE exceptions SET status=? WHERE id IN ({qs})',(status,*clean))
        audit(c,'bulk_status_update','exceptions',{'ids':clean,'status':status,'updated':cur.rowcount})
    return {'ok':True,'updated':cur.rowcount}

BULK_STATUS_TABLES=('tasks','contracts','exceptions')

BULK_DELETE_TABLES=('tasks','contracts','quotations','tariffs','transactions','recurring_tasks')

def bulk_action(table,ids,action,status=None):
    """Change the status of, or delete, many records at once. Approvals are excluded: they have their own rules."""
    if not isinstance(ids,list) or not 1<=len(ids)<=200:raise ValueError('Select 1 to 200 records')
    try:clean=sorted({int(i) for i in ids})
    except (TypeError,ValueError) as e:raise ValueError('Invalid record ids') from e
    marks=','.join(['?']*len(clean))
    with config.LOCK,db() as c:
        if action=='status':
            if table not in BULK_STATUS_TABLES or status not in config.STATUSES:raise ValueError('That status change is not allowed')
            cur=c.execute(f'UPDATE {table} SET status=? WHERE id IN ({marks})',[status,*clean])
        elif action=='delete':
            if table not in BULK_DELETE_TABLES:raise ValueError('These records cannot be deleted in bulk')
            cur=c.execute(f'DELETE FROM {table} WHERE id IN ({marks})',clean)
        else:raise ValueError('Unknown bulk action')
        audit(c,'bulk_'+action,table,{'ids':clean,'affected':cur.rowcount,**({'status':status} if action=='status' else {})})
    return {'ok':True,'affected':cur.rowcount}

SEARCH_SPEC={'tasks':('title','owner',['title','department','owner']),'approvals':('title','requester',['title','requester','approver','rationale']),'contracts':('contract','counterparty',['contract','counterparty','obligation','owner']),'quotations':('item','supplier',['item','supplier','rfq']),'tariffs':('service','customer',['service','customer']),'transactions':('ref','customer',['ref','service','customer']),'recurring_tasks':('title','owner',['title','owner','department']),'exceptions':('entity','kind',['entity','details'])}

def search(q):
    q=str(q or '').strip()
    if len(q)<2 or len(q)>100:return []
    like='%'+q.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
    out=[]
    with db() as c:
        for table,(title,sub,cols) in SEARCH_SPEC.items():
            where=' OR '.join(f"{col} LIKE ? ESCAPE '\\'" for col in cols)
            for r in c.execute(f'SELECT id,{title} AS title,{sub} AS sub FROM {table} WHERE {where} ORDER BY id DESC LIMIT 5',[like]*len(cols)):
                out.append({'table':table,'id':r['id'],'title':r['title'],'sub':r['sub'] or ''})
    return out[:30]

DEDUPE_KEYS={'tasks':('title','due_date','owner'),'contracts':('contract','obligation','due_date'),'quotations':('rfq','supplier','item'),'tariffs':('service','customer','effective_from'),'transactions':('ref',),'recurring_tasks':('title','frequency'),'approvals':('title','requester','amount')}
def _fingerprint(row,keys):return tuple(str(row.get(k) or '').strip().lower() for k in keys)

def import_csv(table,content,dry_run=False,skip_duplicates=True):
    """Load rows from a CSV. dry_run only checks them (nothing is written); duplicates, whether already stored or repeated in the file, are skipped unless told otherwise."""
    if table not in DEDUPE_KEYS:raise ValueError('Invalid import resource')
    if not isinstance(content,str) or len(content)>config.MAX_BODY:raise ValueError('Invalid CSV')
    rows=list(csv.DictReader(io.StringIO(content)))
    if len(rows)>5000:raise ValueError('Maximum 5,000 rows per import')
    keys=DEDUPE_KEYS[table]
    with db() as c:seen={_fingerprint(dict(r),keys) for r in c.execute(f"SELECT {','.join(keys)} FROM {table}")}
    inserted=0;errors=[];duplicates=[];preview=[]
    for n,row in enumerate(rows,2):
        clean={k.strip():v.strip() for k,v in row.items() if k is not None and v is not None}
        try:add_row(table,dict(clean),dry_run=True)                 # validate before anything is written
        except (ValueError,sqlite3.Error) as e:errors.append({'line':n,'error':str(e)});continue
        fingerprint=_fingerprint(clean,keys)
        duplicate=fingerprint in seen
        if duplicate:duplicates.append(n)
        if duplicate and skip_duplicates:continue
        seen.add(fingerprint)
        if len(preview)<5:preview.append(clean)
        if dry_run:inserted+=1;continue
        try:add_row(table,clean);inserted+=1
        except (ValueError,sqlite3.Error) as e:errors.append({'line':n,'error':str(e)})
    return {'dry_run':bool(dry_run),'inserted':inserted,'failed':len(errors),'errors':errors[:40],'duplicates':len(duplicates),'duplicate_lines':duplicates[:40],'skipped_duplicates':len(duplicates) if skip_duplicates else 0,'preview':preview}
