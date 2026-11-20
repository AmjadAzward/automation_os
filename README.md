<div align="center">

<h1><span style="color:#635BFF">Automation</span> <span style="color:#0F9F6E">OS</span></h1>

### A modern, local-first workspace for business operations and automation

[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![SQLite](https://img.shields.io/badge/SQLite-Local_Data-003B57?style=for-the-badge&logo=sqlite&logoColor=white)](https://www.sqlite.org/)
[![License](https://img.shields.io/badge/License-MIT-0F9F6E?style=for-the-badge)](LICENSE)
[![Dependencies](https://img.shields.io/badge/Dependencies-Zero-635BFF?style=for-the-badge)](#technology)

Track work, contracts, supplier quotes, tariffs, billing records and operational exceptions from one private dashboard that runs entirely on your computer.

</div>

---

## Overview

Automation OS is a dependency-free operations platform built with the Python standard library, SQLite, HTML, CSS and JavaScript. It combines everyday record management with configurable automation rules, audit history and an optional local AI assistant.

The application binds to localhost by default, keeps its database on your machine and requires no paid APIs, subscriptions or cloud hosting.

## Highlights

| Area | Capabilities |
|---|---|
| Command Center | Live totals, completion ring, task pipeline, exception feed and a get-started checklist |
| Automation Center | Configurable rules, manual runs, scheduled scans and run history |
| Recurring Work | Daily, weekly and monthly task templates with automatic generation |
| Approval Center | One- or two-step approvals, amount thresholds, enforced approvers, comments and audit history |
| Accounts and Roles | Sign-in, four roles (viewer, member, manager, admin) and a per-user audit trail |
| Work Queue | Kanban board with drag-and-drop status changes, plus card and table views |
| Supplier Comparison | RFQ grouping, total-price comparison, lead times and commercial terms |
| Contract Obligations | Counterparty commitments, ownership and deadline monitoring |
| Revenue Assurance | Approved tariff master and automated billing shortfall detection |
| Exception Management | Severity, status workflows and automatic resolution when conditions clear |
| Performance Insights | Overdue work, upcoming deadlines, completion rates and recent activity |
| Reports and Backup | Workload analytics, financial exposure, savings opportunities and JSON backup |
| Data Portability | CSV import and export, search, sorting, duplicating, editing, deletion with undo, JSON backup and restore |
| Local AI | Optional Ollama-powered analysis without sending data to a cloud model |
| Auditability | Persistent history for creates, updates, deletions and automation events |

## Interface

- Floating top navigation with grouped pages, a live approvals and exceptions badge, and a last-scan indicator
- Press **Ctrl+K** to jump to any page or run an action
- Light and dark themes, remembered per browser
- Create and edit records in a slide-in drawer; boards, cards and sortable tables for every list
- Tab titles show the current page and the number of items needing attention
- Fully responsive: on phones a bottom tab bar replaces the top navigation, boards swipe sideways, forms slide up full-screen with 16px inputs, and tap targets are at least 36px

| Key | Action |
|---|---|
| `Ctrl+K` | Open the jump palette |
| `/` | Focus the search box |
| `n` | New record on the current page |
| `r` | Run an automation scan |
| `t` | Toggle light and dark theme |

The Ctrl+K palette also searches your records (tasks, approvals, contracts, quotes, rates, billing and exceptions) and opens the matching page with the search filled in.

## Automation Engine

Automation OS evaluates operational data every five minutes while the server is running. Each rule can be enabled or disabled independently from the Automation Center.

```text
Operational records
        |
        v
Configurable rule engine
        |
        +-- Task deadline monitoring
        +-- Contract obligation monitoring
        +-- Revenue leakage detection
        |
        v
Exceptions, auto-resolution and audit history
```

The early-warning window can be configured from 1 to 90 days. A manual scan can also be run at any time. Automations create reviewable exceptions and never send messages, approve purchases or move money.

## Quick Start

### Windows

1. Install [Python 3.11 or newer](https://www.python.org/downloads/) and enable **Add Python to PATH**.
2. Clone this repository.
3. Double-click `START_WINDOWS.bat` or run:

```powershell
py -3 app.py
```

4. Open [http://127.0.0.1:8765](http://127.0.0.1:8765).

### macOS and Linux

```bash
python3 app.py
```

Then open [http://127.0.0.1:8765](http://127.0.0.1:8765).

## Optional Local AI

Install [Ollama](https://ollama.com/download), then download the default model:

```bash
ollama pull llama3.2:3b
```

Keep Ollama running while using the Local AI Assistant. The core application works normally without it.

## CSV Imports

Ready-to-use examples are available in the [`samples`](samples) directory. Supported imports include tasks, quotations, contracts, tariffs and transactions.

## REST API

```bash
curl http://127.0.0.1:8765/api/health
curl http://127.0.0.1:8765/api/overview
curl http://127.0.0.1:8765/api/automation/settings
curl http://127.0.0.1:8765/api/automation/runs
curl -X POST http://127.0.0.1:8765/api/scan -H "Content-Type: application/json" -d '{}'
```

Full endpoint notes are available in [`docs/API.md`](docs/API.md).

## Technology

| Layer | Technology |
|---|---|
| Server | Python standard library HTTP server |
| Database | SQLite |
| Interface | Semantic HTML, modern CSS and vanilla JavaScript |
| Local AI | Ollama, optional |
| Required packages | None |

## Project Structure

```text
automation_os/
|-- app.py                 Application server, API and automation engine
|-- static/
|   |-- index.html         Application shell and design system
|   |-- app.js             Interface behavior and API integration
|   `-- favicon*.svg/png   Browser tab icons
|-- tests/                 Backend unit tests and a dependency-free browser smoke test
|-- samples/               CSV import templates
|-- docs/                  API documentation
|-- START_WINDOWS.bat      Windows launcher
`-- LICENSE                MIT License
```

## Accounts, roles and approvals

The app starts in **single-user mode**: no sign-in, full access, and a banner offering to set up accounts. Choose **Set up accounts** to create the first administrator. From then on everyone signs in (sessions last 12 hours, passwords are stored as salted scrypt hashes, repeated failures are throttled) and the audit history records who did what. Existing data is kept.

| Role | Can do |
|---|---|
| viewer | Read everything |
| member | Create and edit records, import, run scans, decide approvals assigned to them |
| manager | Everything a member can, plus delete records |
| admin | Everything, including users, automation settings, backups and restore |

**Approvals are enforced by identity.** A request has an approver and an optional second approver, who must be three different people. The steps run in order and every step must approve; any rejection ends the request. Only the person assigned to the current step (matched on username or display name) can decide it, nobody can decide their own request, and nobody can approve two steps of the same request. An admin can step in on any step except on a request they made. In Automation Center, an admin can require a second approver above an amount, for example 5,000, and requests above it are refused without one.

Approvers are chosen from a list of real, active users and stored by username, so renaming someone never orphans a request. The requester is always the signed-in user and cannot be spoofed. Only the requester (or an admin) can edit or delete a request, so nobody can quietly swap in a friendlier approver. Requests created before accounts were turned on keep working: their approver names are matched against usernames and display names.

**Waiting on you.** The Approvals tab badge, the dashboard and the Today page show what is assigned to *you*, not every pending request, and the Approval Center has an "awaiting me" filter. An admin's right to step in does not make every request theirs.

### Notifications

The bell in the top bar lists what needs your attention, updated every minute: approvals waiting on you, outcomes of your own requests from the last week, and your tasks and contracts that are overdue or due soon. Requests that sit unanswered longer than the limit set in Automation Center (default 3 days, 0 turns it off) are flagged as stuck for the requester and admins, and show as high priority for the approver. Dismissing hides an alert on that browser only, and a new event such as the next approval step brings it back. Desktop alerts are optional and use the browser's own notification permission; nothing is sent to any outside service.

## Backups

A snapshot is written to `data/backups/` once a day while the server runs (the newest 14 are kept). The Reports page can create one on demand and restore from any stored or downloaded backup. A restore is all-or-nothing: an invalid file changes nothing.

## Optional password

By default the app listens only on `127.0.0.1`. To protect it with a password, for example before sharing it on a trusted network, set `AUTOMATION_PASSWORD` before starting (any username is accepted):

```bash
set AUTOMATION_PASSWORD=choose-a-long-passphrase     # Windows
export AUTOMATION_PASSWORD=choose-a-long-passphrase  # macOS / Linux
```

If you also set `AUTOMATION_HOST=0.0.0.0` to allow other machines, a password is strongly recommended and the server prints a warning without one. Traffic is not encrypted, so keep it on a trusted network or behind a TLS reverse proxy.

Regardless of password, the server rejects requests with an unexpected `Host` header (DNS rebinding), cross-origin writes, and request bodies that are not `application/json` (cross-site form posts).

## Security Scope

This project is a local prototype. It does not currently provide authentication, role-based permissions, CSRF protection, HTTPS termination, managed backups or multi-tenant isolation.

Keep it bound to `127.0.0.1`. Do not expose port `8765` to the public internet or use the application for confidential production records until appropriate security controls are implemented.

## Tests

```bash
python -m unittest discover -s tests -v
```

Tests use a temporary database and never touch your real data.

## Browser smoke test

```bash
node tests/ui_smoke.mjs
```

Needs Node 22+ and Chrome or Edge (set `BROWSER=/path/to/browser` if it is not found). It starts its own server on a temporary database and drives a real browser through sign-in, roles, a two-step approval across three people, and a responsive check at 360, 390, 768, 1024 and 1440 pixels (no sideways scrolling, tap-target sizes, bottom tab bar). Set `SHOTS=/some/folder` to save screenshots. No npm packages are required.

## Roadmap

- Notifications with human approval gates
- PostgreSQL support for concurrent teams
- External accounting and procurement adapters
- End-to-end browser tests and production monitoring
- Approval delegation and out-of-office cover
- Email or chat digests (alerts are in-app today)

## License

Automation OS is available under the [MIT License](LICENSE).

<div align="center">

<strong><span style="color:#635BFF">Local by default.</span> <span style="color:#0F9F6E">Automated with control.</span></strong>

</div>
