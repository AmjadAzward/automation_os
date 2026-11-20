"""Dashboards and reports computed from the data."""
import json
from datetime import date
from datetime import datetime
from datetime import timedelta
from decimal import Decimal
from .db import db, money, now, read_table, today

def insights():
    today_=today();cutoff=(datetime.now().date()+timedelta(days=7)).isoformat()
    with db() as c:
        overdue_tasks=c.execute("SELECT COUNT(*) FROM tasks WHERE status!='done' AND due_date!='' AND due_date<?",(today_,)).fetchone()[0]
        due_soon=c.execute("SELECT COUNT(*) FROM tasks WHERE status!='done' AND due_date>=? AND due_date<=?",(today_,cutoff)).fetchone()[0]
        high_exceptions=c.execute("SELECT COUNT(*) FROM exceptions WHERE status!='done' AND severity='high'").fetchone()[0]
        completed=c.execute("SELECT COUNT(*) FROM tasks WHERE status='done'").fetchone()[0]
        total=c.execute('SELECT COUNT(*) FROM tasks').fetchone()[0]
        recent=[dict(x) for x in c.execute('SELECT action,entity,at FROM audit ORDER BY id DESC LIMIT 6')]
    return {'overdue_tasks':overdue_tasks,'due_soon':due_soon,'high_exceptions':high_exceptions,'completion_rate':round(completed*100/total) if total else 0,'recent':recent}

def attention_queue():
    today_=today();cutoff=(datetime.now().date()+timedelta(days=7)).isoformat()
    with db() as c:
        tasks=[dict(x) for x in c.execute("SELECT id,title,owner,due_date,priority,status FROM tasks WHERE status!='done' AND due_date!='' AND due_date<=? ORDER BY due_date ASC LIMIT 20",(cutoff,))]
        contracts=[dict(x) for x in c.execute("SELECT id,contract,obligation,owner,due_date,status FROM contracts WHERE status!='done' AND due_date<=? ORDER BY due_date ASC LIMIT 20",(cutoff,))]
        exceptions=[dict(x) for x in c.execute("SELECT id,kind,entity,details,severity,status,created_at FROM exceptions WHERE status!='done' ORDER BY CASE severity WHEN 'high' THEN 0 ELSE 1 END,id DESC LIMIT 20")]
    for item in tasks+contracts:item['overdue']=item['due_date']<today_
    return {'tasks':tasks,'contracts':contracts,'exceptions':exceptions,'generated_at':now()}

def executive_report():
    today_=today()
    with db() as c:
        workload=[dict(x) for x in c.execute("SELECT CASE WHEN owner='' THEN 'Unassigned' ELSE owner END owner,COUNT(*) total,SUM(CASE WHEN status='done' THEN 1 ELSE 0 END) completed,SUM(CASE WHEN status!='done' AND due_date!='' AND due_date<? THEN 1 ELSE 0 END) overdue FROM tasks GROUP BY owner ORDER BY total DESC",(today_,))]
        departments=[dict(x) for x in c.execute("SELECT department,COUNT(*) total,SUM(CASE WHEN status!='done' THEN 1 ELSE 0 END) open FROM tasks GROUP BY department ORDER BY total DESC")]
        severities=[dict(x) for x in c.execute("SELECT severity,COUNT(*) total FROM exceptions WHERE status!='done' GROUP BY severity")]
        transactions=[dict(x) for x in c.execute('SELECT * FROM transactions')]
        tariffs=[dict(x) for x in c.execute('SELECT * FROM tariffs')]
    leakage={}
    for t in transactions:
        matches=[r for r in tariffs if r['service']==t['service'] and r['customer'] in (t['customer'],'*') and (not r['effective_from'] or r['effective_from']<=(t['date'] or today_)) and r['currency']==t['currency']]
        matches.sort(key=lambda r:(r['customer']!=t['customer'],r['effective_from']),reverse=False)
        if matches:
            gap=money(matches[0]['rate'])*money(t['units'])-money(t['billed'])
            if gap>0:leakage[t['currency']]=leakage.get(t['currency'],Decimal('0'))+gap
    savings={}
    for group in compare_quotes():
        totals=[money(x['total']) for x in group['alternatives']]
        if len(totals)>1:savings[group['currency']]=savings.get(group['currency'],Decimal('0'))+(max(totals)-min(totals))
    return {'generated_at':now(),'workload':workload,'departments':departments,'exception_severity':severities,'potential_leakage':{k:str(v) for k,v in leakage.items()},'quote_savings_opportunity':{k:str(v) for k,v in savings.items()}}

def compare_quotes():
    rows=read_table('quotations',3000)
    grouped={}
    for r in rows:
        key=(r['rfq'],r['item'],r['currency'])
        grouped.setdefault(key,[]).append(r)
    output=[]
    for (rfq,item,currency),group in grouped.items():
        try: sorted_group=sorted(group,key=lambda r:money(r['unit_price'])*money(r['quantity']))
        except ValueError:continue
        output.append({'rfq':rfq,'item':item,'currency':currency,'best_supplier':sorted_group[0]['supplier'],'best_total':str(money(sorted_group[0]['unit_price'])*money(sorted_group[0]['quantity'])),'offers':len(group),'alternatives':[{'supplier':r['supplier'],'total':str(money(r['unit_price'])*money(r['quantity'])),'lead_days':r['lead_days']} for r in sorted_group]})
    return output

def overview():
    with db() as c:
        count=lambda t: c.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]
        pending=c.execute("SELECT COUNT(*) FROM tasks WHERE status!='done'").fetchone()[0]
        outstanding=c.execute("SELECT COUNT(*) FROM exceptions WHERE status!='done'").fetchone()[0]
        approvals=c.execute("SELECT COUNT(*) FROM approvals WHERE status='pending'").fetchone()[0]
    return {'tasks':count('tasks'),'pending_tasks':pending,'quotations':count('quotations'),'contracts':count('contracts'),'transactions':count('transactions'),'exceptions':outstanding,'pending_approvals':approvals,'tariffs':count('tariffs')}


def _valid_day(value,label):
    value=str(value or '').strip()
    if not value:return ''
    try:datetime.strptime(value,'%Y-%m-%d')
    except ValueError as e:raise ValueError(f'{label} must be a date like 2026-01-31') from e
    return value

def audit_query(actor='',action='',entity='',since='',until='',limit=500):
    """Search the audit history. Every filter is optional and values are always bound as parameters."""
    where,args=[],[]
    for column,value in (('actor',actor),('action',action),('entity',entity)):
        if str(value or '').strip():where.append(f'{column}=?');args.append(str(value).strip())
    since,until=_valid_day(since,'From'),_valid_day(until,'To')
    if since:where.append('substr(at,1,10)>=?');args.append(since)
    if until:where.append('substr(at,1,10)<=?');args.append(until)
    try:limit=min(max(int(limit),1),2000)
    except (TypeError,ValueError):limit=500
    sql='SELECT * FROM audit'+(' WHERE '+' AND '.join(where) if where else '')+' ORDER BY id DESC LIMIT ?'
    with db() as c:return [dict(r) for r in c.execute(sql,[*args,limit])]

def audit_facets():
    """The people, actions and record types that appear in the history, for the filter menus."""
    with db() as c:
        pick=lambda col:[r[0] for r in c.execute(f"SELECT DISTINCT {col} FROM audit WHERE {col}!='' ORDER BY {col} LIMIT 200")]
        return {'actors':pick('actor'),'actions':pick('action'),'entities':pick('entity')}

def _done_count(action,details):
    """How many records an audit entry moved to done (0 if it was something else)."""
    try:d=json.loads(details)
    except ValueError:return 0
    if not isinstance(d,dict) or d.get('status')!='done':return 0
    if action=='status_update':return 1
    if action=='bulk_status':return int(d.get('affected') or 0)
    if action=='bulk_status_update':return int(d.get('updated') or 0)
    return 0

def trends(weeks=8):
    """Counts per week (Monday to Sunday) for the last few weeks: what was filed, decided, opened and finished."""
    try:weeks=min(max(int(weeks),2),26)
    except (TypeError,ValueError):weeks=8
    monday=datetime.now().date()-timedelta(days=datetime.now().date().weekday())
    starts=[monday-timedelta(weeks=i) for i in range(weeks-1,-1,-1)]
    keys=('approvals_filed','approvals_decided','exceptions_opened','exceptions_resolved','tasks_created','tasks_completed')
    buckets=[{'start':s.isoformat(),'label':f"{s.strftime('%b')} {s.day}",**{k:0 for k in keys}} for s in starts]
    def bump(stamp,key,n=1):
        try:day=date.fromisoformat(str(stamp)[:10])
        except ValueError:return
        i=(day-starts[0]).days//7
        if 0<=i<weeks:buckets[i][key]+=n
    floor=starts[0].isoformat()
    with db() as c:
        for r in c.execute('SELECT created_at FROM approvals WHERE created_at>=?',(floor,)):bump(r[0],'approvals_filed')
        for r in c.execute("SELECT decided_at FROM approvals WHERE status IN ('approved','rejected') AND decided_at>=?",(floor,)):bump(r[0],'approvals_decided')
        for r in c.execute('SELECT created_at FROM exceptions WHERE created_at>=?',(floor,)):bump(r[0],'exceptions_opened')
        for r in c.execute('SELECT created_at FROM tasks WHERE created_at>=?',(floor,)):bump(r[0],'tasks_created')
        for r in c.execute("SELECT action,entity,details,at FROM audit WHERE at>=? AND action IN ('exception_resolved','status_update','bulk_status','bulk_status_update')",(floor,)):
            if r['action']=='exception_resolved':bump(r['at'],'exceptions_resolved');continue
            n=_done_count(r['action'],r['details'])
            if n and r['entity']=='exceptions':bump(r['at'],'exceptions_resolved',n)
            elif n and r['entity']=='tasks':bump(r['at'],'tasks_completed',n)
    return {'weeks':buckets,'totals':{k:sum(b[k] for b in buckets) for k in keys}}
