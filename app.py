"""Automation OS: dependency-free, local-first business automation starter.
Run: python app.py. No cloud account, API key or pip install required.

The code lives in the `aos` package. This file is the entry point and re-exports the public
names so `import app` keeps working for scripts and tests. Change settings with
`app.config.NAME = value` (the modules read them from there at run time).
"""
from aos import config
from aos.config import *  # noqa: F401,F403  (read-only copies; change values via app.config)
from aos.db import *  # noqa: F401,F403
from aos.settings import *  # noqa: F401,F403
from aos.accounts import *  # noqa: F401,F403
from aos.approvals import *  # noqa: F401,F403
from aos.records import *  # noqa: F401,F403
from aos.reports import *  # noqa: F401,F403
from aos.backups import *  # noqa: F401,F403
from aos.automation import *  # noqa: F401,F403
from aos.server import *  # noqa: F401,F403

if __name__ == '__main__':
    main()
