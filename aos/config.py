"""Settings and constants shared by every module.

Read them as `config.NAME` (not `from .config import NAME`) so that tests and tools can change them at run time."""
import os
import threading
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent

DB=Path(os.getenv('AUTOMATION_DB',str(ROOT/'data'/'automation.sqlite3')))

HOST=os.getenv('AUTOMATION_HOST','127.0.0.1')

PORT=int(os.getenv('AUTOMATION_PORT','8765'))

AUTH=os.getenv('AUTOMATION_PASSWORD','')

LOOPBACK=('127.0.0.1','localhost','::1')

BACKUP_DIR=DB.parent/'backups'

BACKUP_KEEP=14
def _scrypt_cost():
    """Password hashing cost. Keep the default in real use; AUTOMATION_SCRYPT_N exists so tests run quickly."""
    try:n=int(os.getenv('AUTOMATION_SCRYPT_N','16384'))
    except ValueError:return 16384
    return n if n>=16 and n&(n-1)==0 else 16384
SCRYPT_N=_scrypt_cost()

MAX_BODY=3_000_000

LOCK=threading.RLock()

STATUSES={'open','in_progress','blocked','done'}

DEFAULT_SETTINGS={'task_rule':'1','contract_rule':'1','revenue_rule':'1','auto_resolve':'1','due_days':'14','scan_minutes':'5','second_approval_threshold':'0','approval_escalate_days':'3'}

NUMERIC_SETTINGS={'due_days','scan_minutes','second_approval_threshold','approval_escalate_days'}
