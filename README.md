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
| Command Center | Live operational totals, exception summaries and quick-start guidance |
| Automation Center | Configurable rules, manual runs, scheduled scans and run history |
| Recurring Work | Daily, weekly and monthly task templates with automatic generation |
| Work Queue | Task ownership, priorities, due dates and status tracking |
| Supplier Comparison | RFQ grouping, total-price comparison, lead times and commercial terms |
| Contract Obligations | Counterparty commitments, ownership and deadline monitoring |
| Revenue Assurance | Approved tariff master and automated billing shortfall detection |
| Exception Management | Severity, status workflows and automatic resolution when conditions clear |
| Performance Insights | Overdue work, upcoming deadlines, completion rates and recent activity |
| Reports and Backup | Workload analytics, financial exposure, savings opportunities and JSON backup |
| Data Portability | CSV import, CSV export, search, editing and deletion |
| Local AI | Optional Ollama-powered analysis without sending data to a cloud model |
| Auditability | Persistent history for creates, updates, deletions and automation events |

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
|   |-- index.html         Responsive application shell and design system
|   `-- app.js             Interface behavior and API integration
|-- samples/               CSV import templates
|-- docs/                  API documentation
|-- START_WINDOWS.bat      Windows launcher
`-- LICENSE                MIT License
```

## Security Scope

This project is a local prototype. It does not currently provide authentication, role-based permissions, CSRF protection, HTTPS termination, managed backups or multi-tenant isolation.

Keep it bound to `127.0.0.1`. Do not expose port `8765` to the public internet or use the application for confidential production records until appropriate security controls are implemented.

## Roadmap

- Authentication and role-based access control
- Notifications with human approval gates
- PostgreSQL support for concurrent teams
- External accounting and procurement adapters
- Backup, retention and restore workflows
- Test automation and production monitoring
- Multi-stage approval workflows

## License

Automation OS is available under the [MIT License](LICENSE).

<div align="center">

<strong><span style="color:#635BFF">Local by default.</span> <span style="color:#0F9F6E">Automated with control.</span></strong>

</div>
