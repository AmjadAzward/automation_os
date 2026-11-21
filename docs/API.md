# API reference (local prototype)

**GET** `/api/health`, `/api/overview`, `/api/comparison`, `/api/tasks`, `/api/quotations`, `/api/contracts`, `/api/tariffs`, `/api/transactions`, `/api/exceptions`, `/api/audit`.

**POST** `/api/tasks`, `/api/quotations`, `/api/contracts`, `/api/tariffs`, `/api/transactions`: JSON object matching UI fields.

**POST** `/api/status`: `{"table":"tasks|contracts|exceptions","id":1,"status":"open|in_progress|blocked|done"}`.

**GET** `/api/approvals`, `/api/recurring_tasks`, `/api/backup`, `/api/automation/runs`, `/api/reports/executive`.

**POST** `/api/approvals`, `/api/recurring_tasks`: create records. **POST** `/api/approvals/decision`: `{"id":1,"decision":"approved|rejected","comment":""}` (final, one decision per request; approver must differ from requester).

**POST** `/api/restore`: a file produced by `/api/backup`. Replaces tasks, approvals, quotations, contracts, tariffs, transactions, exceptions and run history in one transaction; an invalid file changes nothing.

**GET** `/api/search?q=term`: records matching `term` (2-100 characters) across tasks, approvals, contracts, quotations, rates, billing, recurring tasks and exceptions.

**GET** `/api/backups` lists stored backups; **POST** `/api/backups` creates one now; **POST** `/api/backups/restore` with `{"name":"backup-2026-01-01.json"}` restores a stored one.

Writes must send `Content-Type: application/json` and, if an `Origin` header is present, it must match the `Host`. Set `AUTOMATION_PASSWORD` to require HTTP Basic authentication on every request.

**Accounts.** `GET /api/auth/me` returns `{accounts, user}`. While no accounts exist the API is open (single-user mode). `POST /api/auth/setup` `{username, display_name, password}` creates the first admin once and signs in. `POST /api/auth/login` `{username, password}` sets an HttpOnly, SameSite=Strict session cookie (12 hours); `POST /api/auth/logout` ends it. Once accounts exist every other API call needs the cookie (401 otherwise, with `login: true`). Passwords must be 10 to 200 characters.

**Comments.** `GET /api/comments?entity=tasks|approvals|contracts&id=N` returns the thread (`author`, `author_name`, `body`, `at`); `GET /api/comments/counts?entity=...` maps record ids to counts. `POST /api/comments` `{entity, id, body}` (member role, 1 to 2,000 characters). `DELETE /api/comments/<id>` for the author or an admin. `GET /api/notifications` now also returns `comment` items.

**Attachments.** `GET /api/attachments?entity=tasks|approvals|contracts&id=N` lists files (`id`, `name`, `size`, `uploader`, `at`); `GET /api/attachments/counts?entity=...` maps record ids to counts. `POST /api/attachments` `{entity, id, name, data}` where `data` is the file as base64 (member role, at most 2 MB, 10 per record, executable types refused). `GET /api/attachments/<id>/download` always returns `application/octet-stream` with `Content-Disposition: attachment`, `nosniff` and a sandboxing CSP. `DELETE /api/attachments/<id>` for the uploader, a manager or an admin.

**Audit and trends.** `GET /api/audit?actor=&action=&entity=&since=YYYY-MM-DD&until=YYYY-MM-DD&limit=` filters the history (newest first, limit up to 2,000; bad dates are a 400). `GET /api/audit/facets` lists the people, actions and record types present. `GET /api/trends?weeks=8` (2 to 26) returns weekly buckets (`start`, `label`, `approvals_filed`, `approvals_decided`, `exceptions_opened`, `exceptions_resolved`, `tasks_created`, `tasks_completed`) and `totals`.

**Import.** `POST /api/import` accepts `dry_run` (validate and count without writing) and `skip_duplicates` (default true). The reply has `inserted`, `failed`, `errors`, `duplicates`, `duplicate_lines`, `skipped_duplicates` and the first `preview` rows. Duplicates are detected against stored records and within the file, using a key per record type (for example task title + due date + owner, or billing reference).

**Digest.** `GET /api/digest/status` returns `{enabled, hour, smtp}` (never credentials). `GET /api/digest/preview` returns `{count, subject, body}` for the caller. `POST /api/digest/test` saves the caller's digest to the outbox and emails it if possible, returning `{written, emailed, reason}`. `POST /api/auth/profile` `{email, digest}` sets the caller's own address and opt-in (any role). The settings `digest_enabled`, `digest_hour` and `category_thresholds` (an object such as `{"Purchase": 5000}`) are changed through `POST /api/automation/settings` (admin). Requests that change data return 429 with `Retry-After` when a client exceeds the per-minute limit.

**Withdraw and resubmit.** `POST /api/approvals/withdraw` `{id, reason?}` withdraws a pending request (requester or admin only; 400 if it is not pending). Steps still pending become `skipped`, decided steps are kept, and the request gets status `withdrawn`. `POST /api/approvals` accepts `previous_id`, which must be a rejected or withdrawn request (and, once accounts exist, one you own or you are an admin); the new request records the link.

**Out-of-office cover.** `POST /api/auth/delegate` `{delegate, until}` hands the caller's approvals to an active member-or-higher user until `until` (YYYY-MM-DD, today to 90 days ahead; the date itself still counts). An empty `delegate` ends it. `GET /api/auth/me` shows `delegate_to` and `delegate_until` while cover is active. The delegate can decide steps assigned to the caller; the step then records `decided_by` (the delegate) and `acting_for` (the person covered). `GET /api/people` adds `can_decide`, and approvals add `covering`.

**Bulk.** `POST /api/bulk` `{table, ids, action, status?}` with `action` `status` (tasks, contracts, exceptions; member role) or `delete` (tasks, contracts, quotations, tariffs, transactions, recurring_tasks; manager role). 1 to 200 ids; returns `{affected}` and writes one audit entry listing the ids. Approvals are not accepted.

**Self-service.** `POST /api/auth/password` `{current, new}` changes the caller's own password (any role; 400 if the current one is wrong, throttled after repeated failures) and ends every other session. `POST /api/auth/logout-all` ends all of the caller's sessions. Both need an account (not single-user mode).

**Users (admin only).** `GET /api/users`, `POST /api/users` `{username, display_name, role, password}`, `PUT /api/users/<id>` with any of `display_name`, `role`, `active`, `password`. The last active admin cannot be demoted or disabled. Roles: viewer < member < manager < admin. Viewers are read-only; members write; managers also delete; admins also manage users, settings, backups and restore (these return 403 for lower roles).

**Approvals.** `GET /api/approvals` adds `steps`, `progress`, `awaiting` and `can_decide` (for the calling user). Create and edit accept `second_approver`. `POST /api/approvals/decision` decides the current step only if you are assigned to it (or an admin) and it is not your own request; it returns `{status, stage, stages}` where `status` stays `pending` until the last step approves. Requests at or above the `second_approval_threshold` setting (0 = off) must have a second approver. A request that already has a decided step can no longer be edited.

**People and notifications.** `GET /api/people` lists active users as `{username, display_name}` for any signed-in user (used for approver pickers). `GET /api/notifications` returns what needs the caller's attention as `[{key, kind, severity, title, detail, page}]`, where `kind` is `approval`, `stuck`, `outcome`, `task` or `contract`, most urgent first. `GET /api/overview` adds `awaiting_me`, the number of pending approval steps assigned to the caller, and `GET /api/approvals` adds `mine` per request.

Once accounts exist, `POST /api/approvals` sets `requester` to the caller (any value you send is ignored) and requires `approver` and `second_approver` to be active users (display names are accepted and stored as usernames). `PUT` and `DELETE` on an approval return 403 unless the caller is the requester or an admin. The `approval_escalate_days` setting (0 to 60, default 3) controls when pending requests are flagged as stuck.

**POST** `/api/scan`: `{}` — scans due dates and tariff underbilling.

**POST** `/api/import`: `{"table":"tasks","csv":"title,department,...\n..."}`.

**POST** `/api/ai`: `{"prompt":"Explain these terms..."}` — requires local Ollama.

No authentication is implemented. **Never expose this API outside the trusted local machine.**
