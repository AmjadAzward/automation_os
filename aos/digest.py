"""The daily digest: a short summary of what needs each person.

Nothing leaves this computer unless an administrator has configured an SMTP server AND the person opted in.
Every digest is also written to an outbox folder so it can be read, audited or sent by other means.
"""
import os
import re
import smtplib
import ssl
from datetime import datetime
from email.message import EmailMessage
from . import config
from .db import audit, db
from .settings import automation_settings
from .accounts import list_users
from .comments import all_notifications

def smtp_configured():return bool(config.SMTP_HOST and config.SMTP_FROM)

def build_digest(user):
    """Subject and plain-text body for one person. `count` is 0 when nothing needs them."""
    items=all_notifications(user)
    name=(user.get('display_name') or user.get('username') or 'there') if user else 'there'
    if not items:
        return {'count':0,'subject':'Automation OS: nothing needs you today','body':f'Hi {name},\n\nNothing needs your attention right now.\n\n{config.PUBLIC_URL}\n'}
    sections=[('high','Urgent'),('medium','Needs attention'),('low','For your information')]
    lines=[f'Hi {name},','',f"{len(items)} thing{'s' if len(items)!=1 else ''} need{'s' if len(items)==1 else ''} your attention:",'']
    for severity,heading in sections:
        group=[i for i in items if i['severity']==severity]
        if not group:continue
        lines.append(heading.upper())
        lines+= [f"  - {i['title']}: {i['detail']}" for i in group]
        lines.append('')
    lines+=[f'Open Automation OS: {config.PUBLIC_URL}','','You receive this because you turned on the daily digest. You can turn it off in the account menu.']
    count=len(items)
    return {'count':count,'subject':f"Automation OS: {count} item{'s' if count!=1 else ''} need{'s' if count==1 else ''} your attention",'body':'\n'.join(lines)+'\n'}

def write_outbox(user,digest):
    """Save the digest as a text file. Returns the file name."""
    folder=config.OUTBOX_DIR
    folder.mkdir(parents=True,exist_ok=True)
    safe=re.sub(r'[^A-Za-z0-9._-]','_',str(user.get('username') or 'local'))
    path=folder/f"digest-{safe}-{datetime.now():%Y%m%d-%H%M%S-%f}.txt"
    path.write_text(f"To: {user.get('email') or '(no email address)'}\nSubject: {digest['subject']}\n\n{digest['body']}",encoding='utf-8')
    try:os.chmod(folder,0o700);os.chmod(path,0o600)
    except OSError:pass
    for old in sorted(folder.glob('digest-*.txt'),key=lambda p:p.stat().st_mtime,reverse=True)[500:]:old.unlink()     # keep the newest 500
    return path.name

def send_email(to,subject,body):
    message=EmailMessage()
    message['From']=config.SMTP_FROM;message['To']=to;message['Subject']=subject    # header values with line breaks are rejected by the library
    message.set_content(body)
    mode=config.SMTP_SECURITY
    if mode=='ssl':client=smtplib.SMTP_SSL(config.SMTP_HOST,config.SMTP_PORT,timeout=20,context=ssl.create_default_context())
    else:client=smtplib.SMTP(config.SMTP_HOST,config.SMTP_PORT,timeout=20)
    with client:
        if mode=='starttls':client.starttls(context=ssl.create_default_context())
        if config.SMTP_USER:client.login(config.SMTP_USER,config.SMTP_PASSWORD)
        client.send_message(message)

def deliver(user,digest):
    """Save to the outbox and, when possible, email it. Never raises: the outcome is described in the result."""
    result={'written':write_outbox(user,digest),'emailed':False,'reason':''}
    address=str(user.get('email') or '').strip() if user else ''
    if not smtp_configured():result['reason']='Email is not set up on this server, so the digest was only saved to the outbox folder.'
    elif not address:result['reason']='You have not added an email address, so the digest was only saved to the outbox folder.'
    else:
        try:send_email(address,digest['subject'],digest['body']);result['emailed']=True
        except (OSError,smtplib.SMTPException,ValueError) as e:
            result['reason']='The email could not be sent. The digest was saved to the outbox folder.'
            with config.LOCK,db() as c:audit(c,'digest_failed','users',{'user':user.get('username'),'error':type(e).__name__})   # the error text is not stored: it can contain server details
    return result

def run_digests(at=None):
    """Called by the scheduler every few minutes. Once a day, after the chosen hour, each opted-in person gets their digest (if anything needs them)."""
    settings=automation_settings()
    if not settings['digest_enabled']:return []
    at=at or datetime.now()
    if at.hour<settings['digest_hour']:return []
    day=at.date().isoformat();sent=[]
    for user in list_users():
        if not user['active'] or not user['digest_optin'] or user['digest_sent']==day:continue
        with config.LOCK,db() as c:c.execute('UPDATE users SET digest_sent=? WHERE id=?',(day,user['id']))     # mark first: a crash can never cause a repeat
        digest=build_digest(user)
        if not digest['count']:continue
        sent.append({'user':user['username'],**deliver(user,digest)})
    return sent
