"""Multi-stage approvals, out-of-office cover, the people directory and notifications."""
from . import config
import re
from datetime import datetime
from datetime import timedelta
from .db import audit, db, money, now, read_table, today
from .settings import automation_settings
from .accounts import Forbidden, RANK, require_account, user_count

def identities(user):
    return {str(user['username']).strip().lower(),str(user['display_name']).strip().lower()} if user and not user.get('open') else None

def check_approval_rules(p):
    requester=str(p.get('requester','')).strip().lower();first=str(p.get('approver','')).strip().lower();second=str(p.get('second_approver') or '').strip().lower()
    if requester==first:raise ValueError('Approver must be a different person from the requester')
    if second:
        if second==requester:raise ValueError('The second approver must be a different person from the requester')
        if second==first:raise ValueError('The second approver must be a different person from the first approver')
    limit=automation_settings()['second_approval_threshold']
    if limit and money(p.get('amount','0'))>=limit and not second:raise ValueError(f'Requests of {limit:,} or more need a second approver')

def create_steps(c,ident,approver,second=''):
    c.execute('DELETE FROM approval_steps WHERE approval_id=?',(ident,))
    for stage,name in enumerate([approver]+([second] if str(second).strip() else []),1):
        c.execute('INSERT INTO approval_steps(approval_id,stage,approver,status) VALUES(?,?,?,?)',(ident,stage,str(name).strip(),'pending'))

def decide_approval(ident,decision,comment='',user=None):
    """Record one approver's decision. A request is approved only when every step is approved; any rejection ends it."""
    if decision not in ('approved','rejected'):raise ValueError('Decision must be approved or rejected')
    comment=str(comment).strip()
    if len(comment)>2000:raise ValueError('Decision comment is too long')
    with config.LOCK,db() as c:
        row=c.execute('SELECT * FROM approvals WHERE id=?',(ident,)).fetchone()
        if not row:raise ValueError('Approval request not found')
        if row['status']!='pending':raise ValueError('This request has already been decided')
        steps=c.execute('SELECT * FROM approval_steps WHERE approval_id=? ORDER BY stage',(ident,)).fetchall()
        if not steps:
            create_steps(c,ident,row['approver'],row['second_approver'] or '')
            steps=c.execute('SELECT * FROM approval_steps WHERE approval_id=? ORDER BY stage',(ident,)).fetchall()
        current=next((s for s in steps if s['status']=='pending'),None)
        if current is None:raise ValueError('This request has no pending step')
        who=current['approver'];acting_for=''
        ids=identities(user)
        if ids is not None:
            who=user['display_name']
            assigned=str(current['approver']).strip().lower()
            covering=assigned not in ids and assigned in delegators_of(user)
            if user['role']!='admin' and assigned not in ids and not covering:raise Forbidden(f"This step is assigned to {current['approver']}")
            if covering:acting_for=current['approver']
            if str(row['requester']).strip().lower() in ids:raise Forbidden('You cannot decide your own request')
            if any(str(s['decided_by']).strip().lower() in ids for s in steps if s['status']=='approved'):raise Forbidden('You already approved an earlier step of this request')
        stamp=now()
        c.execute('UPDATE approval_steps SET status=?,comment=?,decided_by=?,decided_at=?,acting_for=? WHERE id=?',(decision,comment,who,stamp,acting_for,current['id']))
        if decision=='rejected':
            c.execute("UPDATE approval_steps SET status='skipped' WHERE approval_id=? AND status='pending'",(ident,))
            final='rejected'
        else:
            final='pending' if any(s['status']=='pending' and s['id']!=current['id'] for s in steps) else 'approved'
        if final!='pending':c.execute('UPDATE approvals SET status=?,decision_comment=?,decided_at=? WHERE id=?',(final,comment,stamp,ident))
        audit(c,'approval_decision','approvals',{'id':ident,'stage':current['stage'],'decision':decision,'decided_by':who,'acting_for':acting_for,'request_status':final,'comment':comment})
    return {'ok':True,'status':final,'stage':current['stage'],'stages':len(steps)}

def approvals_list(user=None):
    rows=read_table('approvals',500)
    steps={}
    with db() as c:
        for s in c.execute('SELECT * FROM approval_steps ORDER BY approval_id,stage'):steps.setdefault(s['approval_id'],[]).append(dict(s))
    ids=identities(user)
    cover=delegators_of(user) if ids is not None else set()
    for r in rows:
        st=steps.get(r['id']) or [{'stage':1,'approver':r['approver'],'status':r['status'],'comment':r['decision_comment'],'decided_by':r['approver'] if r['status']!='pending' else '','decided_at':r['decided_at']}]
        current=next((s for s in st if s['status']=='pending'),None) if r['status']=='pending' else None
        r['steps']=st
        r['progress']=f"{sum(1 for s in st if s['status']=='approved')}/{len(st)} approved"
        r['awaiting']=current['approver'] if current else ''
        if r['status']!='pending' or current is None:r['can_decide']=False
        elif ids is None:r['can_decide']=True
        else:
            r['can_decide']=((user['role']=='admin' or str(current['approver']).strip().lower() in (ids|cover))
                and str(r['requester']).strip().lower() not in ids
                and not any(str(s['decided_by']).strip().lower() in ids for s in st if s['status']=='approved'))
        # 'mine' = the current step is assigned to me. An admin's override right (can_decide) does not make every request theirs.
        r['mine']=bool(r['can_decide'] and (ids is None or str(current['approver']).strip().lower() in (ids|cover)))
        r['covering']=bool(r['mine'] and ids is not None and str(current['approver']).strip().lower() not in ids)
    return rows

def delegators_of(user):
    """Lower-cased usernames and display names of everyone who has currently handed their approvals to this user."""
    if not user or user.get('open'):return set()
    out=set()
    with db() as c:
        for r in c.execute("SELECT username,display_name FROM users WHERE active=1 AND delegate_to=? COLLATE NOCASE AND delegate_until>=?",(user['username'],today())):
            out|={r['username'].lower(),str(r['display_name']).strip().lower()}
    return out

def set_delegation(user,delegate,until):
    """Out of office: hand my approvals to a colleague until a date (at most 90 days ahead). An empty delegate ends it."""
    require_account(user)
    delegate=str(delegate or '').strip()
    with config.LOCK,db() as c:
        if not delegate:
            c.execute("UPDATE users SET delegate_to='',delegate_until='' WHERE id=?",(user['id'],))
            audit(c,'delegation_end','users',{'id':user['id']})
            return {'ok':True,'delegate_to':'','delegate_until':''}
        target=c.execute('SELECT username,role FROM users WHERE active=1 AND (username=? COLLATE NOCASE OR display_name=? COLLATE NOCASE)',(delegate,delegate)).fetchone()
        if not target:raise ValueError('The person covering for you must be an active user')
        if target['username'].lower()==str(user['username']).lower():raise ValueError('You cannot cover for yourself')
        if RANK[target['role']]<RANK['member']:raise ValueError('The person covering for you needs the member role or higher')
        until=str(until or '').strip()
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',until):raise ValueError('Choose the date you are back (YYYY-MM-DD)')
        try:back=datetime.strptime(until,'%Y-%m-%d').date()
        except ValueError as e:raise ValueError('That is not a real date') from e
        first=datetime.now().date()
        if back<first:raise ValueError('The return date cannot be in the past')
        if back>first+timedelta(days=90):raise ValueError('Cover can last at most 90 days. You can renew it later')
        c.execute('UPDATE users SET delegate_to=?,delegate_until=? WHERE id=?',(target['username'],until,user['id']))
        audit(c,'delegation_set','users',{'id':user['id'],'delegate':target['username'],'until':until})
    return {'ok':True,'delegate_to':target['username'],'delegate_until':until}

def people():
    """Active users as {username, display_name, can_decide}; safe to show to every signed-in user."""
    with db() as c:return [{'username':r['username'],'display_name':r['display_name'],'can_decide':RANK[r['role']]>=RANK['member']} for r in c.execute('SELECT username,display_name,role FROM users WHERE active=1 ORDER BY display_name COLLATE NOCASE')]

def canonical_person(name):
    """Map a typed name to the matching active user's username. Usernames never change; display names can."""
    key=str(name or '').strip()
    if not key:return ''
    with db() as c:
        r=c.execute('SELECT username FROM users WHERE active=1 AND username=? COLLATE NOCASE',(key,)).fetchone() or c.execute('SELECT username FROM users WHERE active=1 AND display_name=? COLLATE NOCASE',(key,)).fetchone()
    return r['username'] if r else key

def canonicalize_approvers(payload):
    """Approvers must be real, active users and are stored by username, so renaming someone never orphans a request."""
    known={p['username'].lower() for p in people()}
    for field,label in (('approver','Approver'),('second_approver','Second approver')):
        if field in payload and str(payload[field] or '').strip():
            name=canonical_person(payload[field])
            if name.lower() not in known:raise ValueError(f'{label} must be an active user')
            payload[field]=name

def prepare_approval_payload(payload,user):
    """When accounts exist, the requester is always the signed-in user (it cannot be spoofed) and approvers must be real users."""
    if user_count()==0 or not user or user.get('open'):return payload
    payload['requester']=user['username']
    canonicalize_approvers(payload)
    if payload.get('previous_id') not in (None,'',0,'0'):
        with db() as c:earlier=c.execute('SELECT requester FROM approvals WHERE id=?',(payload['previous_id'],)).fetchone()
        if earlier and not can_manage_approval(user,earlier['requester']):raise Forbidden('You can only resubmit your own requests')
    return payload

def can_manage_approval(user,requester):
    ids=identities(user)
    return ids is None or user['role']=='admin' or str(requester).strip().lower() in ids

def edit_approval_guard(ident,body,user):
    """Only the requester (or an admin) may change a request, so nobody can quietly swap in a friendlier approver."""
    with db() as c:row=c.execute('SELECT requester FROM approvals WHERE id=?',(ident,)).fetchone()
    if not row:raise ValueError('Record not found')
    if not can_manage_approval(user,row['requester']):raise Forbidden('Only the requester or an admin can change this request')
    if identities(user) is not None:
        if user['role']!='admin':body.pop('requester',None)
        canonicalize_approvers(body)

def delete_approval_guard(ident,user):
    with db() as c:row=c.execute('SELECT requester FROM approvals WHERE id=?',(ident,)).fetchone()
    if row and not can_manage_approval(user,row['requester']):raise Forbidden('Only the requester or an admin can delete this request')

def check_resubmission(previous_id,requester):
    """A resubmission must point at a rejected or withdrawn request, so history stays linked."""
    try:ident=int(previous_id)
    except (TypeError,ValueError) as e:raise ValueError('Invalid link to the earlier request') from e
    with db() as c:row=c.execute('SELECT status FROM approvals WHERE id=?',(ident,)).fetchone()
    if not row:raise ValueError('The earlier request was not found')
    if row['status'] not in ('rejected','withdrawn'):raise ValueError('Only a rejected or withdrawn request can be resubmitted')
    return ident

def withdraw_approval(ident,user=None,reason=''):
    """The requester (or an admin) pulls back a pending request. Unlike deleting it, the history is kept."""
    reason=str(reason or '').strip()
    if len(reason)>2000:raise ValueError('The reason is too long')
    with config.LOCK,db() as c:
        row=c.execute('SELECT * FROM approvals WHERE id=?',(ident,)).fetchone()
        if not row:raise ValueError('Approval request not found')
        if row['status']!='pending':raise ValueError('Only a pending request can be withdrawn')
        if not can_manage_approval(user,row['requester']):raise Forbidden('Only the requester or an admin can withdraw this request')
        c.execute("UPDATE approval_steps SET status='skipped' WHERE approval_id=? AND status='pending'",(ident,))
        c.execute("UPDATE approvals SET status='withdrawn',decision_comment=?,decided_at=? WHERE id=?",(reason,now(),ident))
        audit(c,'approval_withdrawn','approvals',{'id':ident,'reason':reason})
    return {'ok':True,'status':'withdrawn'}

def _age_days(iso):
    try:
        moment=datetime.fromisoformat(iso)
        return max(0,(datetime.now(moment.tzinfo)-moment).days)
    except (TypeError,ValueError):return 0

def notifications(user=None):
    """Everything that currently needs this person's attention. Derived live from the data, so it is never stale."""
    ids=identities(user)
    mine=lambda name:ids is None or str(name or '').strip().lower() in ids
    names={p['username'].lower():p['display_name'] for p in people()}
    label=lambda n:names.get(str(n or '').lower(),n)
    escalate=automation_settings()['approval_escalate_days']
    today_=datetime.now().date()
    items=[]
    def add(key,kind,severity,title,detail,page):items.append({'key':key,'kind':kind,'severity':severity,'title':title,'detail':detail,'page':page})
    for a in approvals_list(user):
        age=_age_days(a['created_at'])
        if a['status']=='pending':
            late=bool(escalate) and age>=escalate
            if a['mine']:
                done=sum(1 for s in a['steps'] if s['status']=='approved')
                add(f"approval:{a['id']}:{done}",'approval','high' if late else 'medium',a['title'],('Covering for '+label(a['awaiting'])+' · waiting for a decision' if a['covering'] else 'Waiting for your decision')+(f' · {age} days old' if age else ''),'approvals')
            elif late and (ids is None or user['role']=='admin' or mine(a['requester'])):
                add(f"stuck:{a['id']}:{a['awaiting']}",'stuck','high',a['title'],f"Stuck for {age} days with {label(a['awaiting'])}",'approvals')
        elif ids is not None and a['status']!='withdrawn' and mine(a['requester']) and a['decided_at'] and _age_days(a['decided_at'])<=7:
            add(f"outcome:{a['id']}:{a['decided_at']}",'outcome','low' if a['status']=='approved' else 'medium',a['title'],f"Your request was {a['status']}",'approvals')
    with db() as c:
        rows=[('task',r['id'],r['title'],r['owner'],r['due_date'],'tasks') for r in c.execute("SELECT id,title,owner,due_date FROM tasks WHERE status!='done' AND due_date!='' AND due_date<=? ORDER BY due_date LIMIT 60",((today_+timedelta(days=3)).isoformat(),))]
        rows+=[('contract',r['id'],r['contract'],r['owner'],r['due_date'],'contracts') for r in c.execute("SELECT id,contract,owner,due_date FROM contracts WHERE status!='done' AND due_date<=? ORDER BY due_date LIMIT 60",((today_+timedelta(days=7)).isoformat(),))]
    for kind,ident,title,owner,due,page in rows:
        if not mine(owner):continue
        try:days=(datetime.strptime(due,'%Y-%m-%d').date()-today_).days
        except ValueError:continue
        add(f'{kind}:{ident}:{due}',kind,'high' if days<0 else 'medium',title,(f'Overdue by {-days} day'+('s' if days!=-1 else '')) if days<0 else ('Due today' if days==0 else f'Due in {days} day'+('s' if days!=1 else '')),page)
    order={'high':0,'medium':1,'low':2}
    items.sort(key=lambda i:(order[i['severity']],i['title'].lower()))
    return items[:50]
