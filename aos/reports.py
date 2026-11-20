"""Dashboards and reports computed from the data."""
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
