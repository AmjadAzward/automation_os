"""Automation settings stored in the database."""
import json
from . import config
from .db import audit, db, read_table

def automation_settings():
    with db() as c:values={r['key']:r['value'] for r in c.execute('SELECT key,value FROM settings')}
    merged={**config.DEFAULT_SETTINGS,**{k:v for k,v in values.items() if k in config.DEFAULT_SETTINGS}}
    out={}
    for k,v in merged.items():
        if k in config.NUMERIC_SETTINGS:out[k]=int(v)
        elif k=='category_thresholds':
            try:parsed=json.loads(v)
            except ValueError:parsed={}
            out[k]=parsed if isinstance(parsed,dict) else {}
        else:out[k]=v=='1'
    return out

def _clean_thresholds(value):
    """Second-approver limits per category, e.g. {"Purchase": 5000}. A blank removes a limit; 0 switches the rule off for that category."""
    if isinstance(value,str):
        try:value=json.loads(value or '{}')
        except ValueError as e:raise ValueError('The category limits are not valid') from e
    if not isinstance(value,dict):raise ValueError('The category limits must be an object')
    out={}
    for category,limit in value.items():
        if category not in config.CATEGORIES:raise ValueError(f'Unknown category: {category}')
        if limit in (None,''):continue
        try:number=int(float(limit))
        except (TypeError,ValueError) as e:raise ValueError(f'The limit for {category} must be a number') from e
        out[category]=min(max(number,0),10**12)
    return json.dumps(out,sort_keys=True)

def save_automation_settings(row):
    allowed=set(config.DEFAULT_SETTINGS);updates={k:row[k] for k in row if k in allowed}
    if 'due_days' in updates:updates['due_days']=str(min(max(int(updates['due_days']),1),90))
    if 'scan_minutes' in updates:updates['scan_minutes']=str(min(max(int(updates['scan_minutes']),1),60))
    if 'second_approval_threshold' in updates:updates['second_approval_threshold']=str(min(max(int(float(updates['second_approval_threshold'])),0),10**12))
    if 'approval_escalate_days' in updates:updates['approval_escalate_days']=str(min(max(int(float(updates['approval_escalate_days'])),0),60))
    if 'digest_hour' in updates:updates['digest_hour']=str(min(max(int(float(updates['digest_hour'])),0),23))
    if 'category_thresholds' in updates:updates['category_thresholds']=_clean_thresholds(updates['category_thresholds'])
    for k in allowed-config.NUMERIC_SETTINGS-{'category_thresholds'}:
        if k in updates:updates[k]='1' if bool(updates[k]) else '0'
    with config.LOCK,db() as c:
        for k,v in updates.items():c.execute('INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)',(k,str(v)))
        audit(c,'automation_settings','settings',updates)
    return automation_settings()

def automation_runs():return read_table('automation_runs',100)
