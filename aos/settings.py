"""Automation settings stored in the database."""
from . import config
from .db import audit, db, read_table

def automation_settings():
    with db() as c:values={r['key']:r['value'] for r in c.execute('SELECT key,value FROM settings')}
    numeric=config.NUMERIC_SETTINGS
    return {**{k:(int(v) if k in numeric else v=='1') for k,v in config.DEFAULT_SETTINGS.items()},**{k:(int(v) if k in numeric else v=='1') for k,v in values.items() if k in config.DEFAULT_SETTINGS}}

def save_automation_settings(row):
    allowed=set(config.DEFAULT_SETTINGS);updates={k:row[k] for k in row if k in allowed}
    if 'due_days' in updates:updates['due_days']=str(min(max(int(updates['due_days']),1),90))
    if 'scan_minutes' in updates:updates['scan_minutes']=str(min(max(int(updates['scan_minutes']),1),60))
    if 'second_approval_threshold' in updates:updates['second_approval_threshold']=str(min(max(int(float(updates['second_approval_threshold'])),0),10**12))
    if 'approval_escalate_days' in updates:updates['approval_escalate_days']=str(min(max(int(float(updates['approval_escalate_days'])),0),60))
    for k in allowed-config.NUMERIC_SETTINGS:
        if k in updates:updates[k]='1' if bool(updates[k]) else '0'
    with config.LOCK,db() as c:
        for k,v in updates.items():c.execute('INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)',(k,str(v)))
        audit(c,'automation_settings','settings',updates)
    return automation_settings()

def automation_runs():return read_table('automation_runs',100)
