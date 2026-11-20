'use strict';
/* Automation OS - UI */
const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const store = {
  get(k, d) { try { return localStorage.getItem(k) ?? d; } catch (e) { return d; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* storage unavailable */ } }
};

/* ---------- theme ---------- */
(() => {
  let t = store.get('aos-theme', null);
  if (!t) t = matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  document.documentElement.dataset.theme = t;
})();
function toggleTheme() {
  const n = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
  document.documentElement.dataset.theme = n;
  store.set('aos-theme', n);
}

/* ---------- icons ---------- */
const ICON = {
  dashboard: '<path d="M3 11.5 12 4l9 7.5"/><path d="M5.5 10v10h13V10M9 20v-6h6v6"/>',
  today: '<rect x="3.5" y="5" width="17" height="15" rx="2"/><path d="M3.5 10h17M8 3v4M16 3v4"/>',
  insights: '<path d="M4 19V9M10 19V5M16 19v-7M22 19H2"/>',
  tasks: '<path d="M9 5h10M9 12h10M9 19h10"/><path d="m3 5 1.3 1.3L6.5 4M3 12l1.3 1.3L6.5 11M3 19l1.3 1.3L6.5 18"/>',
  recurring_tasks: '<path d="M4 12a8 8 0 0 1 14-5.3L20 9M20 4v5h-5M20 12a8 8 0 0 1-14 5.3L4 15M4 20v-5h5"/>',
  approvals: '<circle cx="12" cy="12" r="9"/><path d="m8 12.5 2.8 2.8L16.5 9"/>',
  contracts: '<path d="M7 3h10l3 3v15H7z"/><path d="M17 3v4h4M10 12h7M10 16h7"/>',
  quotations: '<path d="M6 3h12v18H6z"/><path d="M9 8h6M9 12h6M9 16h3"/>',
  tariffs: '<circle cx="12" cy="12" r="9"/><path d="M15 8.5c-.7-.5-1.6-.8-2.5-.8-1.5 0-2.5.7-2.5 1.8 0 2.8 5 1.1 5 4 0 1.1-1 1.9-2.6 1.9-1 0-2-.3-2.8-.9M12 6v12"/>',
  transactions: '<path d="M4 7h16v12H4zM4 10h16"/><path d="M7 15h3"/>',
  automation: '<path d="M13 2 4 14h7l-1 8 9-12h-7z"/>',
  exceptions: '<path d="M12 3 2.5 20h19z"/><path d="M12 9v5M12 17h.01"/>',
  reports: '<path d="M6 3h9l4 4v14H6z"/><path d="M14 3v5h5M9 13h7M9 17h5"/>',
  audit: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  ai: '<rect x="4" y="6" width="16" height="13" rx="3"/><path d="M9 11h.01M15 11h.01M9 15h6M12 3v3"/>',
  imports: '<path d="M12 3v12M7 10l5 5 5-5"/><path d="M4 18v3h16v-3"/>',
  users: '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20c.6-3.6 3.2-5.5 6.5-5.5s5.9 1.9 6.5 5.5M16 4.8a3.4 3.4 0 0 1 0 6.4M18.5 14.7c1.7.7 2.9 2.4 3.3 5.3"/>',
  act: '<path d="M5 12h14M13 6l6 6-6 6"/>'
};
const svg = k => `<svg viewBox="0 0 24 24" aria-hidden="true">${ICON[k] || ICON.act}</svg>`;

/* ---------- pages ---------- */
const PAGES = {
  dashboard: ['Command Center', 'Your operations at a glance'],
  today: ['Today', 'What needs attention right now'],
  insights: ['Performance Insights', 'Deadlines, risk and completion trends'],
  tasks: ['Work Queue', 'Assign, monitor and close tasks'],
  recurring_tasks: ['Recurring Tasks', 'Routine work that generates itself'],
  approvals: ['Approval Center', 'Review and decide controlled requests'],
  contracts: ['Contract Obligations', 'Deadlines and commitments to counterparties'],
  quotations: ['Supplier Comparison', 'Compare equivalent RFQ offers'],
  tariffs: ['Rate Master', 'Approved reference rates for revenue checks'],
  transactions: ['Billing Records', 'Billing activity checked against approved rates'],
  automation: ['Automation Center', 'Configure rules and monitor automation runs'],
  exceptions: ['Exception Center', 'Deadlines, underbilling and operational alerts'],
  reports: ['Reports & Backup', 'Executive analytics and portable data export'],
  audit: ['Audit History', 'Every recorded change to local data'],
  ai: ['Local AI Assistant', 'Optional Ollama-powered draft analysis'],
  imports: ['CSV Imports', 'Load existing records without retyping'],
  users: ['Users & Roles', 'Control who can sign in and what they can do']
};
const GROUPS = [
  ['Overview', ['dashboard', 'today', 'insights']],
  ['Work', ['tasks', 'recurring_tasks', 'approvals', 'contracts']],
  ['Commercial', ['quotations', 'tariffs', 'transactions']],
  ['Control', ['automation', 'exceptions', 'reports', 'audit']],
  ['Tools', ['ai', 'imports', 'users']]
];
const groupOf = k => GROUPS.find(g => g[1].includes(k)) || GROUPS[0];

/* ---------- field definitions (create / edit / import) ---------- */
const defs = {
  tasks: [['title','Task title','text',1],['department','Department'],['owner','Owner'],['due_date','Due date','date'],['status','Status','select:open,in_progress,blocked,done'],['priority','Priority','select:low,medium,high']],
  recurring_tasks: [['title','Task title','text',1],['department','Department'],['owner','Owner'],['priority','Priority','select:low,medium,high'],['frequency','Frequency','select:daily,weekly,monthly'],['next_due','Next generation date','date',1],['active','Active','select:yes,no']],
  approvals: [['title','Request title','text',1],['category','Category','select:Purchase,Operational,Contract,Payment,Other'],['requester','Requester','text',1],['approver','Approver','text',1],['second_approver','Second approver (optional)'],['amount','Amount','number'],['currency','Currency'],['rationale','Business rationale','area']],
  quotations: [['rfq','RFQ / reference','text',1],['supplier','Supplier','text',1],['item','Item / description','text',1],['quantity','Quantity','number'],['unit_price','Unit price','number',1],['currency','Currency'],['lead_days','Lead days','number'],['terms','Commercial terms','area']],
  contracts: [['contract','Contract name','text',1],['counterparty','Counterparty'],['obligation','Obligation','area',1],['owner','Owner'],['due_date','Due date','date',1],['status','Status','select:open,in_progress,blocked,done']],
  tariffs: [['service','Service code','text',1],['customer','Customer (* = default)'],['currency','Currency'],['rate','Rate','number',1],['unit','Unit'],['effective_from','Effective from','date']],
  transactions: [['ref','Invoice / transaction ref','text',1],['service','Service code','text',1],['customer','Customer','text',1],['billed','Billed amount','number',1],['units','Units','number'],['currency','Currency'],['date','Transaction date','date']]
};
const ST = ['open', 'in_progress', 'blocked', 'done'];

/* ---------- how each resource is shown ---------- */
const RES = {
  tasks:   { noun: 'task', title: r => r.title, sub: r => [r.department, r.owner].filter(Boolean).join(' · ') || 'Unassigned', status: 'status', statuses: ST, drag: true, date: 'due_date', priority: 'priority', views: ['board', 'cards', 'table'] },
  contracts: { noun: 'contract', title: r => r.contract, sub: r => [r.counterparty, r.owner].filter(Boolean).join(' · '), body: r => r.obligation, status: 'status', statuses: ST, drag: true, date: 'due_date', views: ['board', 'cards', 'table'] },
  approvals: { noun: 'request', title: r => r.title, sub: r => `${person(r.requester)} → ${[r.approver, r.second_approver].filter(Boolean).map(person).join(' → ')}`, body: r => r.rationale, status: 'status', statuses: ['pending', 'approved', 'rejected', 'withdrawn'], money: r => [r.amount, r.currency], chips: r => [r.category, r.steps && r.steps.length > 1 ? r.progress : '', r.covering ? 'covering for ' + person(r.awaiting) : '', r.previous_id ? 'resubmission of #' + r.previous_id : ''], views: ['board', 'cards', 'table'] },
  recurring_tasks: { noun: 'template', title: r => r.title, sub: r => [r.department, r.owner].filter(Boolean).join(' · ') || 'Unassigned', status: 'active', priority: 'priority', chips: r => [r.frequency, 'next ' + r.next_due], views: ['cards', 'table'] },
  quotations: { noun: 'quote', title: r => r.item, sub: r => `${r.rfq} · ${r.supplier}`, body: r => r.terms, money: r => [r.unit_price, r.currency + ' / unit'], chips: r => ['qty ' + r.quantity, r.lead_days ? r.lead_days + 'd lead' : ''], views: ['cards', 'table'] },
  tariffs: { noun: 'rate', title: r => r.service, sub: r => 'Customer: ' + (r.customer || '*'), money: r => [r.rate, `${r.currency || ''} / ${r.unit || 'unit'}`], chips: r => [r.effective_from ? 'from ' + r.effective_from : ''], views: ['cards', 'table'] },
  transactions: { noun: 'record', title: r => r.ref, sub: r => `${r.service} · ${r.customer}`, money: r => [r.billed, r.currency], chips: r => [r.units ? r.units + ' units' : '', r.date], views: ['cards', 'table'] },
  exceptions: { noun: 'exception', readonly: true, title: r => r.entity, sub: r => r.kind.replace(/_/g, ' '), body: r => r.details, status: 'status', statuses: ST, drag: true, priority: 'severity', views: ['board', 'cards', 'table'] },
  audit: { noun: 'event', readonly: true, views: ['timeline', 'table'] }
};

/* ---------- helpers ---------- */
let active = 'dashboard';
let ME = { accounts: false, user: null };
let READY = false;
let PEOPLE = [];
let NOTES = [];
const person = u => { const p = PEOPLE.find(x => x.username.toLowerCase() === String(u || '').toLowerCase()); return p ? p.display_name : (u || ''); };
const mineName = n => !!(ME.accounts && ME.user && [ME.user.username, ME.user.display_name].some(x => x.toLowerCase() === String(n || '').trim().toLowerCase()));
const ownsApproval = r => !ME.accounts || can.admin || mineName(r.requester);
const RANKS = { viewer: 0, member: 1, manager: 2, admin: 3 };
const rank = () => (ME.accounts ? (ME.user ? RANKS[ME.user.role] : -1) : 3);
const can = { get write() { return rank() >= 1; }, get del() { return rank() >= 2; }, get admin() { return rank() >= 3; } };
const visible = k => k !== 'users' || can.admin;
let currentRows = [];
let bestIds = new Set();
async function api(path, options = {}) {
  const r = await fetch('/api/' + path, { headers: { 'Content-Type': 'application/json' }, ...options });
  const out = await r.json();
  if (!r.ok) {
    if (r.status === 401 && out.login && ME.accounts && READY) { ME.user = null; showLogin(); }
    throw Error(out.error || 'Request failed');
  }
  return out;
}
function msg(text, action) {
  const el = $('#message');
  el.textContent = text;
  if (action) {
    const b = document.createElement('button');
    b.className = 'tbtn'; b.textContent = action.label;
    b.onclick = () => { el.classList.add('hidden'); action.run(); };
    el.append(b);
  }
  el.classList.remove('hidden');
  clearTimeout(window._toast);
  window._toast = setTimeout(() => el.classList.add('hidden'), action ? 9000 : 4200);
}
const human = s => String(s ?? '').replace(/_/g, ' ');
const num = v => { const n = Number(String(v).replace(/,/g, '')); return Number.isFinite(n) ? n.toLocaleString(undefined, { maximumFractionDigits: 2 }) : esc(v); };
const isoToday = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };
function dueInfo(date, done) {
  if (!date || done) return null;
  const n = Math.round((new Date(date + 'T00:00:00') - new Date(isoToday() + 'T00:00:00')) / 864e5);
  if (Number.isNaN(n)) return null;
  if (n < 0) return ['bad', `${-n}d overdue`];
  if (n === 0) return ['warn', 'Due today'];
  if (n <= 7) return ['warn', `Due in ${n}d`];
  return ['', date];
}
function downloadBlob(blob, name) {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob); a.download = name; a.click();
  URL.revokeObjectURL(a.href);
}
const stamp = () => new Date().toISOString().slice(0, 10);
const downloadJson = (data, name) => downloadBlob(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }), name);
function exportCsv(rows, key) {
  if (!rows.length) return msg('Nothing to export');
  const cols = Object.keys(rows[0]).filter(c => !['steps', 'can_decide'].includes(c));
  const q = v => '"' + String(typeof v === 'object' && v !== null ? JSON.stringify(v) : v ?? '').replace(/"/g, '""') + '"';
  const csv = [cols.join(','), ...rows.map(r => cols.map(c => q(r[c])).join(','))].join('\r\n');
  downloadBlob(new Blob([csv], { type: 'text/csv' }), `${key}-${stamp()}.csv`);
  msg('CSV export created');
}
const setBody = h => { $('#content').innerHTML = h; };
const setActions = h => { $('#pageactions').innerHTML = h; };
const empty = (t, d = '') => `<div class="empty"><b>${esc(t)}</b>${esc(d)}</div>`;

/* ---------- navigation ---------- */
let badges = {};
let lastScanAt = null;
function ago(iso) {
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return '';
  const m = Math.max(0, Math.round((Date.now() - t) / 60000));
  return m < 1 ? 'just now' : m < 60 ? `${m}m ago` : m < 1440 ? `${Math.round(m / 60)}h ago` : `${Math.round(m / 1440)}d ago`;
}
function paintScan() { const el = $('#lastscan'); if (el) el.textContent = lastScanAt ? 'Last scan ' + ago(lastScanAt) : 'No scan yet'; }
function nav() {
  const g = groupOf(active);
  $('#groups').innerHTML = GROUPS.map(([n, items]) => [n, items.filter(visible)]).filter(([, items]) => items.length)
    .map(([n, items]) => `<button data-go="${items[0]}" class="${g[0] === n ? 'on' : ''}">${n}</button>`).join('');
  const TAB_ICON = { Overview: 'dashboard', Work: 'tasks', Commercial: 'quotations', Control: 'automation', Tools: 'ai' };
  const tabBadge = { Work: badges.approvals, Control: badges.exceptions };
  $('#tabbar').innerHTML = GROUPS.map(([n, items]) => [n, items.filter(visible)]).filter(([, items]) => items.length)
    .map(([n, items]) => `<button data-go="${items[0]}" class="${g[0] === n ? 'on' : ''}" aria-label="${n}">${svg(TAB_ICON[n] || 'act')}${n}${tabBadge[n] ? `<span class="dot">${tabBadge[n]}</span>` : ''}</button>`).join('');
  $('#subnav').innerHTML = g[1].filter(visible).map(k => {
    const b = badges[k];
    return `<button data-go="${k}" class="${k === active ? 'on' : ''}">${svg(k)}${esc(PAGES[k][0])}${b ? `<span class="dot">${b}</span>` : ''}</button>`;
  }).join('');
}
async function refreshBadges() {
  if (!READY) return;
  try {
    const [s, runs, notes] = await Promise.all([api('overview'), api('automation/runs'), api('notifications')]);
    lastScanAt = runs[0] ? runs[0].finished_at : null; paintScan();
    const mineCount = ME.accounts ? s.awaiting_me : s.pending_approvals;
    badges = { approvals: mineCount, exceptions: s.exceptions };
    const n = (mineCount || 0) + (s.exceptions || 0);
    setNotes(notes);
    document.title = `${n ? `(${n}) ` : ''}${PAGES[active][0]} · Automation OS`;
    nav();
  } catch (e) { /* non-critical */ }
}
function go(key) {
  if (!PAGES[key] || !visible(key)) key = 'dashboard';
  if (location.hash === '#/' + key) render(key); else location.hash = '#/' + key;
}
const switchTo = go;
function route() {
  if (!READY) return;
  const k = location.hash.replace(/^#\/?/, '') || 'dashboard';
  render(PAGES[k] && visible(k) ? k : 'dashboard');
}
/* Pages draw one at a time. If you click through tabs quickly, a slow page can no longer finish
   after a newer one and overwrite it; pages queued behind a newer request are skipped. */
let renderChain = Promise.resolve(), renderTicket = 0;
function render(key) {
  const ticket = ++renderTicket;
  renderChain = renderChain.then(() => (ticket === renderTicket ? drawPage(key) : null));
  return renderChain;
}
async function drawPage(key) {
  active = key;
  document.body.dataset.rendered = '';
  const [title, desc] = PAGES[key];
  document.title = `${title} · Automation OS`;
  $('#title').textContent = title; $('#subtitle').textContent = desc;
  setActions(''); nav();
  try {
    if (key === 'dashboard') await dashboard();
    else if (key === 'today') await todayView();
    else if (key === 'insights') await insightsView();
    else if (key === 'automation') await automationView();
    else if (key === 'reports') await reportsView();
    else if (key === 'ai') assistant();
    else if (key === 'imports') importsView();
    else if (key === 'users') await usersView();
    else await records(key);
  } catch (e) { setBody(empty('Something went wrong', e.message)); }
  document.body.dataset.rendered = key;   // lets tests (and anything else) know the page has finished drawing
  refreshBadges();
}

/* ---------- reusable pieces ---------- */
function ring(pct, label) {
  const C = 2 * Math.PI * 52;
  return `<div class="ring"><svg viewBox="0 0 128 128"><circle class="bg" cx="64" cy="64" r="52"/><circle class="fg" cx="64" cy="64" r="52" stroke-dasharray="${(Math.max(0, Math.min(100, pct)) / 100 * C).toFixed(1)} ${C.toFixed(1)}"/></svg><div>${esc(label)}</div></div>`;
}
function plainTable(rows) {
  if (!rows || !rows.length) return empty('Nothing here yet');
  const keys = Object.keys(rows[0]);
  return `<div class="tw"><table><thead><tr>${keys.map(k => `<th>${esc(human(k))}</th>`).join('')}</tr></thead><tbody>${rows.map(r => `<tr>${keys.map(k => `<td class="${['details', 'title', 'terms', 'obligation', 'rationale'].includes(k) ? 'wrap' : ''}">${esc(typeof r[k] === 'object' && r[k] !== null ? JSON.stringify(r[k]) : r[k])}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
}
function feedItem(r, type) {
  const d = r.due_date ? dueInfo(r.due_date, false) : null;
  const sev = r.severity || '';
  const title = r.title || r.contract || r.entity;
  const sub = r.details || r.obligation || `${r.owner || 'Unassigned'}${r.due_date ? ' · due ' + r.due_date : ''}`;
  return `<div class="fi">${type === 'exception' ? `<input class="exc" type="checkbox" value="${r.id}" aria-label="Select">` : `<span class="sv ${r.overdue ? 'high' : ''}"></span>`}<div><b>${esc(title)}</b><small>${esc(sub)}</small></div><div class="rt">${d ? `<span class="badge ${d[0]}">${esc(d[1])}</span>` : ''}${sev ? `<span class="badge ${esc(sev)}">${esc(sev)}</span>` : ''}${r.priority && type !== 'exception' ? `<span class="badge ${esc(r.priority)}">${esc(r.priority)}</span>` : ''}</div></div>`;
}

/* ---------- dashboard ---------- */
async function dashboard() {
  const [s, ins, exc, tasks, runs] = await Promise.all([api('overview'), api('insights'), api('exceptions'), api('tasks'), api('automation/runs')]);
  const steps = [['Add an approved rate', s.tariffs > 0, 'tariffs'], ['Record billing activity', s.transactions > 0, 'transactions'], ['Create your first task', s.tasks > 0, 'tasks'], ['Run an automation scan', runs.length > 0, 'automation']];
  const stepsLeft = steps.filter(x => !x[1]).length;
  const h = new Date().getHours();
  const hello = h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening';
  const open = exc.filter(x => x.status !== 'done');
  const parts = [];
  if (ins.overdue_tasks) parts.push(`${ins.overdue_tasks} overdue task${ins.overdue_tasks > 1 ? 's' : ''}`);
  if (ins.high_exceptions) parts.push(`${ins.high_exceptions} high-risk alert${ins.high_exceptions > 1 ? 's' : ''}`);
  const apv = ME.accounts ? s.awaiting_me : s.pending_approvals;
  if (apv) parts.push(`${apv} approval${apv > 1 ? 's' : ''} ${ME.accounts ? 'waiting on you' : 'waiting'}`);
  const lead = parts.length ? 'Needs you: ' + parts.join(', ') + '.' : 'Nothing is overdue and no high-risk alerts are open.';
  const counts = ST.map(k => [k, tasks.filter(t => t.status === k).length]);
  const max = Math.max(1, ...counts.map(c => c[1]));
  const color = { open: 'var(--blue)', in_progress: 'var(--warn)', blocked: 'var(--bad)', done: 'var(--good)' };
  const kpi = (page, label, val, note, k) => `<button class="c kpi s3" data-go="${page}" style="--k:${k}"><span class="l"><i></i>${label}</span><b>${val}</b><span class="n">${note}</span></button>`;
  setBody(`<div class="bento">
    <section class="c hero s8"><div><div class="eb">${new Date().toLocaleDateString(undefined, { weekday: 'long', month: 'long', day: 'numeric' })}</div><h2>${hello}.</h2><p>${esc(lead)}</p></div>
      <div class="acts">${can.write ? '<button class="btn pri" data-act="scan">Run automation scan</button>' : ''}<button class="btn" data-go="today">Open Today</button>${s.tasks + s.contracts + s.quotations === 0 ? '<button class="btn" data-act="demo">Load sample records</button>' : ''}</div></section>
    <section class="c s4"><div class="hd"><div><h2>Completion</h2><small>Tasks marked done</small></div></div><div class="ringbox">${ring(ins.completion_rate, ins.completion_rate + '%')}<div class="legend"><span><b>${s.tasks}</b> tasks total</span><span><b>${s.pending_tasks}</b> still open</span><span><b>${ins.due_soon}</b> due this week</span></div></div></section>
    ${kpi('tasks', 'Pending tasks', s.pending_tasks, 'In the work queue', 'var(--blue)')}
    ${kpi('approvals', ME.accounts ? 'Waiting on you' : 'Pending approvals', ME.accounts ? s.awaiting_me : s.pending_approvals, ME.accounts ? `${s.pending_approvals} pending in total` : 'Awaiting a decision', 'var(--accent)')}
    ${kpi('exceptions', 'Open exceptions', s.exceptions, 'Awaiting review', 'var(--bad)')}
    ${kpi('contracts', 'Obligations', s.contracts, 'Contracts tracked', 'var(--good)')}
    ${stepsLeft ? `<section class="c s12"><div class="hd"><div><h2>Get started</h2><small>${4 - stepsLeft} of 4 steps complete</small></div></div><div class="chips">${steps.map(([t, d, p]) => `<button data-go="${p}" class="${d ? 'on' : ''}">${d ? '✓ ' : ''}${esc(t)}</button>`).join('')}</div></section>` : ''}
    <section class="c s7"><div class="hd"><div><h2>Latest exceptions</h2><small>Newest detected items</small></div><button class="btn sm" data-go="exceptions">View all</button></div><div class="feed">${open.slice(0, 5).map(x => `<div class="fi"><span class="sv ${x.severity === 'high' ? 'high' : ''}"></span><div><b>${esc(x.entity)}</b><small>${esc(x.details)}</small></div><div class="rt"><span class="badge ${esc(x.severity)}">${esc(x.severity)}</span></div></div>`).join('') || empty('All clear', 'No open exceptions.')}</div></section>
    <section class="c s5"><div class="hd"><div><h2>Task pipeline</h2><small>Live status distribution</small></div><button class="btn sm" data-go="tasks">Open board</button></div>${tasks.length ? `<div class="bars">${counts.map(([k, n]) => `<div class="bar2" style="--k:${color[k]}"><div class="t"><span>${human(k)}</span><span>${n}</span></div><div class="trk"><div class="fil" style="width:${n / max * 100}%"></div></div></div>`).join('')}</div>` : empty('No tasks yet', 'Create one from the Work Queue.')}</section>
  </div>`);
}

/* ---------- today ---------- */
async function todayView() {
  const [q, appr] = await Promise.all([api('attention'), api('approvals')]);
  const waiting = appr.filter(a => a.status === 'pending' && (!ME.accounts || a.mine));
  const items = [...q.tasks.map(x => ({ ...x, _t: 'task' })), ...q.contracts.map(x => ({ ...x, _t: 'contract' }))].sort((a, b) => a.due_date.localeCompare(b.due_date));
  const t = isoToday();
  const lanes = [['Overdue', items.filter(x => x.due_date < t)], ['Today', items.filter(x => x.due_date === t)], ['Next 7 days', items.filter(x => x.due_date > t)]];
  setActions(`<button class="btn" data-go="approvals">Approvals</button>${can.write ? '<button class="btn pri" data-act="scan">Run scan</button>' : ''}`);
  setBody(`<div class="bento">
    <section class="c s7"><div class="hd"><div><h2>Tasks &amp; obligations</h2><small>${items.length} item${items.length === 1 ? '' : 's'} due within seven days</small></div></div>
      ${items.length ? lanes.filter(l => l[1].length).map(([n, a]) => `<div class="grp">${n} · ${a.length}</div><div class="feed" style="margin-bottom:14px">${a.map(x => feedItem(x, x._t)).join('')}</div>`).join('') : empty('Nothing due this week', 'Enjoy the quiet.')}</section>
    <section class="c s5"><div class="hd"><div><h2>Priority exceptions</h2><small>Tick alerts to resolve them together</small></div></div>
      <div class="acts" style="margin-bottom:10px"><button class="btn sm" data-act="selall">Select all</button><button class="btn sm good" data-act="resolve">Mark selected done</button></div>
      <div class="feed">${q.exceptions.map(x => feedItem(x, 'exception')).join('') || empty('No open exceptions')}</div></section>
    <section class="c s12"><div class="hd"><div><h2>${ME.accounts ? 'Waiting for your decision' : 'Waiting for a decision'}</h2><small>${waiting.length} pending approval${waiting.length === 1 ? '' : 's'}</small></div><button class="btn sm" data-go="approvals">Open Approval Center</button></div>
      <div class="feed">${waiting.map(a => `<div class="fi"><span class="sv"></span><div><b>${esc(a.title)}</b><small>${esc(person(a.requester))} → ${esc(person(a.approver))} · ${num(a.amount)} ${esc(a.currency)}</small></div><div class="rt"><span class="badge">${esc(a.category)}</span>${a.can_decide ? `<button class="btn sm good" data-act="decide" data-id="${a.id}" data-d="approved">Approve</button><button class="btn sm bad" data-act="decide" data-id="${a.id}" data-d="rejected">Reject</button>` : `<span class="badge">waiting for ${esc(person(a.awaiting || a.approver))}</span>`}</div></div>`).join('') || empty('Nothing waiting', 'Every request has been decided.')}</div></section></div>`);
}

/* ---------- insights ---------- */
async function insightsView() {
  const x = await api('insights');
  const kpi = (l, v, n, k) => `<div class="c kpi s3" style="--k:${k};cursor:default"><span class="l"><i></i>${l}</span><b>${v}</b><span class="n">${n}</span></div>`;
  setBody(`<div class="bento">${kpi('Overdue tasks', x.overdue_tasks, 'Past their due date', 'var(--bad)')}${kpi('Due this week', x.due_soon, 'Next seven days', 'var(--warn)')}${kpi('High-risk alerts', x.high_exceptions, 'Needs attention', 'var(--accent)')}${kpi('Completion rate', x.completion_rate + '%', 'Tasks marked done', 'var(--good)')}
    <section class="c s5"><div class="hd"><div><h2>Operational health</h2><small>Calculated from local records</small></div></div><div class="ringbox">${ring(x.completion_rate, x.completion_rate + '%')}<p style="margin:0">Focus first on overdue tasks and high-severity exceptions. Completion is measured across every task in the workspace.</p></div></section>
    <section class="c s7"><div class="hd"><div><h2>Recent activity</h2><small>Latest recorded changes</small></div><button class="btn sm" data-go="audit">Full history</button></div><div class="tl">${x.recent.map(r => `<div class="fi"><div><b>${esc(human(r.action))} · ${esc(r.entity)}</b><small>${esc(r.at)}</small></div></div>`).join('') || empty('No activity yet')}</div></section></div>`);
}

/* ---------- bulk selection ---------- */
const BULK = { tasks: ['status', 'delete'], contracts: ['status', 'delete'], exceptions: ['status'], quotations: ['delete'], tariffs: ['delete'], transactions: ['delete'], recurring_tasks: ['delete'] };
const bulkOps = key => (BULK[key] || []).filter(o => (o === 'status' ? can.write : can.del));
let selectMode = false, picked = new Set(), shownIds = [], repaintRecords = null;
const pickBox = (key, r, cfg) => (selectMode ? `<label class="pick"><input type="checkbox" class="pickbox" data-id="${r.id}" ${picked.has(r.id) ? 'checked' : ''} aria-label="Select ${esc(cfg.title ? cfg.title(r) : r.id)}"></label>` : '');
function renderBulkBar() {
  const bar = $('#bulkbar');
  if (!bar) return;
  bar.classList.toggle('hidden', !selectMode);
  const all = $('#pickall'); if (all) all.checked = shownIds.length > 0 && shownIds.every(id => picked.has(id));
  if (!selectMode) return;
  const ops = bulkOps(active), n = picked.size;
  bar.innerHTML = `<b>${n} selected</b><button class="btn sm" data-act="pickall">Select all shown</button>`
    + (ops.includes('status') ? `<select id="bulkstatus" aria-label="New status">${ST.map(s => `<option value="${s}">${human(s)}</option>`).join('')}</select><button class="btn sm good" data-act="bulkstatus" ${n ? '' : 'disabled'}>Apply</button>` : '')
    + (ops.includes('delete') ? `<button class="btn sm bad" data-act="bulkdelete" ${n ? '' : 'disabled'}>Delete</button>` : '')
    + '<button class="btn sm" data-act="selectmode">Done</button>';
}
async function runBulk(action) {
  const ids = [...picked];
  if (!ids.length) return msg('Select at least one record');
  const body = { table: active, ids, action };
  if (action === 'status') body.status = $('#bulkstatus').value;
  else if (!confirm(`Delete ${ids.length} record${ids.length === 1 ? '' : 's'}? This cannot be undone.`)) return;
  try { const r = await api('bulk', { method: 'POST', body: JSON.stringify(body) }); msg(action === 'status' ? `${r.affected} updated` : `${r.affected} deleted`); render(active); }
  catch (ex) { msg(ex.message); }
}

/* ---------- records (board / cards / table) ---------- */
function ownerActions(key, r) {
  if (key !== 'approvals' || !can.write || !ownsApproval(r)) return '';
  if (r.status === 'pending') return `<button class="ln" data-act="withdraw" data-id="${r.id}">Withdraw</button>`;
  if (r.status === 'rejected' || r.status === 'withdrawn') return `<button class="ln" data-act="resubmit" data-id="${r.id}">Resubmit</button>`;
  return '';
}
function openWithdraw(id) {
  drawer('Withdraw request', '<p>Withdrawing cancels the request. Approvers are no longer asked to decide it, and it stays on file with your reason so the history is kept. You can resubmit it later.</p><div class="field"><label for="wr">Reason (optional)</label><textarea id="wr" name="reason" placeholder="Why are you withdrawing it?"></textarea></div>', 'Withdraw request', async d => {
    await api('approvals/withdraw', { method: 'POST', body: JSON.stringify({ id: Number(id), reason: d.reason || '' }) });
    closeLayer(); msg('Request withdrawn'); render(active);
  });
}
function stepsHtml(r) {
  if (!r.steps || r.steps.length < 2) return '';
  return `<div class="steps2">${r.steps.map(s => `<div class="st ${esc(s.status)}"><span class="n">${s.stage}</span><span><b>${esc(person(s.approver))}</b><small>${s.status === 'pending' ? 'waiting' : esc(s.status)}${s.decided_by && (s.decided_by !== person(s.approver) || s.acting_for) ? ' · by ' + esc(s.decided_by) + (s.acting_for ? ' (covering for ' + esc(person(s.acting_for)) + ')' : '') : ''}</small></span></div>`).join('')}</div>`;
}
const approvalEditable = r => r.status === 'pending' && !(r.steps || []).some(s => s.status !== 'pending');
function cardHtml(key, r, cfg) {
  const d = cfg.date ? dueInfo(r[cfg.date], r[cfg.status] === 'done') : null;
  const chips = [...(cfg.chips ? cfg.chips(r) : [])].filter(Boolean);
  if (key === 'quotations' && bestIds.has(r.id)) chips.unshift('★ Best price');
  const money = cfg.money ? cfg.money(r) : null;
  const body = cfg.body ? cfg.body(r) : '';
  const editable = can.write && !cfg.readonly && !(key === 'approvals' && (!approvalEditable(r) || !ownsApproval(r)));
  const pr = cfg.priority && r[cfg.priority] ? r[cfg.priority] : '';
  const st = cfg.status ? String(r[cfg.status]) : '';
  const stCls = key === 'recurring_tasks' ? (st === 'yes' ? 'good' : '') : st;
  const stLabel = key === 'recurring_tasks' ? (st === 'yes' ? 'Active' : 'Paused') : human(st);
  const movable = cfg.drag && can.write;
  const statusSelect = movable
    ? `<select class="status" data-id="${r.id}" data-table="${key}" aria-label="Change status">${ST.map(s => `<option value="${s}" ${s === st ? 'selected' : ''}>${human(s)}</option>`).join('')}</select>` : '';
  const decide = key === 'approvals' && r.status === 'pending'
    ? (r.can_decide
      ? `<button class="btn sm good" data-act="decide" data-id="${r.id}" data-d="approved">Approve</button><button class="btn sm bad" data-act="decide" data-id="${r.id}" data-d="rejected">Reject</button>`
      : `<span class="note">Waiting for ${esc(person(r.awaiting || r.approver))}</span>`) : '';
  return `<article class="card ${pr ? 'e-' + esc(pr) : ''}" data-id="${r.id}" ${movable && !selectMode ? 'draggable="true"' : ''}>
    <div class="top">${pickBox(key, r, cfg)}<h3>${esc(cfg.title(r))}</h3>${st && !cfg.statuses ? `<span class="badge ${esc(stCls)}">${esc(stLabel)}</span>` : ''}${pr && !cfg.date && key !== 'exceptions' ? `<span class="badge ${esc(pr)}">${esc(pr)}</span>` : ''}${key === 'exceptions' ? `<span class="badge ${esc(pr)}">${esc(pr)}</span>` : ''}</div>
    ${cfg.sub ? `<div class="sub">${esc(cfg.sub(r))}</div>` : ''}
    ${money ? `<div class="money">${num(money[0])} <small>${esc(money[1])}</small></div>` : ''}
    ${body ? `<p class="body">${esc(body)}</p>` : ''}
    ${key === 'approvals' ? stepsHtml(r) : ''}
    ${key === 'approvals' && r.decision_comment ? `<div class="note">“${esc(r.decision_comment)}”</div>` : ''}
    ${chips.length || d || (pr && cfg.date) ? `<div class="meta">${d ? `<span class="badge ${d[0]}">${esc(d[1])}</span>` : ''}${pr && cfg.date ? `<span class="badge ${esc(pr)}">${esc(pr)}</span>` : ''}${chips.map(c => `<span class="badge ${c.startsWith('★') ? 'good' : ''}">${esc(c)}</span>`).join('')}</div>` : ''}
    <div class="foot">${decide || statusSelect}${key === 'approvals' && r.status !== 'pending' ? `<span class="badge ${esc(r.status)}">${esc(r.status)}</span>` : ''}
      <span class="sp"></span>${ownerActions(key, r)}${!cfg.readonly && can.write ? `<button class="ln" data-act="dup" data-id="${r.id}">Duplicate</button>` : ''}${editable ? `<button class="ln" data-act="edit" data-id="${r.id}">Edit</button>` : ''}${!cfg.readonly && can.del && (key !== 'approvals' || ownsApproval(r)) ? `<button class="ln d" data-act="del" data-id="${r.id}">Delete</button>` : ''}</div></article>`;
}
const HIDE = new Set(['steps', 'can_decide']);
function tableHtml(key, rows, cfg, sort) {
  if (!rows.length) return empty('No matching records');
  const keys = Object.keys(rows[0]).filter(k => !HIDE.has(k));
  const acts = !cfg.readonly && (can.write || can.del);
  return `<div class="tw"><table class="${acts ? 'act' : ''}"><thead><tr>${selectMode ? '<th><input type="checkbox" id="pickall" aria-label="Select all shown"></th>' : ''}${keys.map(k => `<th data-sort="${k}" title="Sort">${esc(human(k))}${sort && sort.k === k ? `<span class="ar">${sort.dir > 0 ? '▲' : '▼'}</span>` : ''}</th>`).join('')}${acts ? '<th>Actions</th>' : ''}</tr></thead><tbody>${rows.map(r => `<tr>${selectMode ? `<td><input type="checkbox" class="pickbox" data-id="${r.id}" ${picked.has(r.id) ? 'checked' : ''} aria-label="Select record ${r.id}"></td>` : ''}${keys.map(k => {
    const v = r[k];
    const badge = ['status', 'severity', 'priority'].includes(k) && v;
    return `<td class="${['details', 'title', 'terms', 'obligation', 'rationale', 'decision_comment'].includes(k) ? 'wrap' : ''}">${badge ? `<span class="badge ${esc(v)}">${esc(human(v))}</span>` : esc(typeof v === 'object' && v !== null ? JSON.stringify(v) : v)}</td>`;
  }).join('')}${acts ? `<td>${key === 'approvals' && r.can_decide ? `<button class="ln" data-act="decide" data-id="${r.id}" data-d="approved">Approve</button><button class="ln d" data-act="decide" data-id="${r.id}" data-d="rejected">Reject</button>` : ''}${ownerActions(key, r)}${can.write ? `<button class="ln" data-act="dup" data-id="${r.id}">Duplicate</button>` : ''}${can.write && !(key === 'approvals' && (!approvalEditable(r) || !ownsApproval(r))) ? `<button class="ln" data-act="edit" data-id="${r.id}">Edit</button>` : ''}${can.del && (key !== 'approvals' || ownsApproval(r)) ? `<button class="ln d" data-act="del" data-id="${r.id}">Delete</button>` : ''}</td>` : ''}</tr>`
  ).join('')}</tbody></table></div>`;
}
function auditSummary(raw) {
  let o; try { o = JSON.parse(raw); } catch (e) { return String(raw || ''); }
  const v = o && o.values ? o.values : o;
  if (!v || typeof v !== 'object') return String(raw || '');
  return Object.entries(v).slice(0, 4).map(([k, x]) => `${human(k)}: ${typeof x === 'object' ? JSON.stringify(x) : x}`).join(' · ').slice(0, 180);
}
function auditHtml(list) {
  if (!list.length) return empty('No matching events');
  const tone = { create: 'good', delete: 'bad', update: 'blue', restore: 'warn', approval_decision: 'warn' };
  return `<div class="c"><div class="tl">${list.map(r => `<div class="fi"><div><b>${esc(human(r.action))} · ${esc(r.entity)}${r.actor ? ' · by ' + esc(r.actor) : ''}</b><small>${esc(auditSummary(r.details))}</small></div><div class="rt"><span class="badge ${tone[r.action] || ''}">${esc(String(r.at).slice(0, 16).replace('T', ' '))}</span></div></div>`).join('')}</div></div>`;
}
async function records(key) {
  const cfg = RES[key];
  const rows = await api(key);
  currentRows = rows;
  selectMode = false; picked = new Set(); shownIds = [];
  bestIds = new Set();
  if (key === 'quotations') {
    const gk = r => [r.rfq, r.item, r.currency].join('|'), best = {}, n = {};
    rows.forEach(r => { const k = gk(r), p = Number(r.unit_price); n[k] = (n[k] || 0) + 1; if (!isNaN(p) && (!best[k] || p < best[k].p)) best[k] = { p, id: r.id }; });
    Object.keys(best).forEach(k => { if (n[k] > 1) bestIds.add(best[k].id); });
  }
  const phone = matchMedia('(max-width: 760px)').matches;
  const saved = store.get('aos-view-' + key, phone && cfg.views.includes('cards') ? 'cards' : cfg.views[0]);
  let state = { q: '', view: cfg.views.includes(saved) ? saved : cfg.views[0], filter: 'all', sort: null };
  const cmp = key === 'quotations' ? await api('comparison') : null;
  const canCreate = !cfg.readonly && can.write;
  setActions(`${!cfg.readonly && can.write ? '<button class="btn" data-go="imports">Import CSV</button>' : ''}${bulkOps(key).length && rows.length ? '<button class="btn" data-act="selectmode">Select</button>' : ''}<button class="btn" data-act="export">Export CSV</button>${canCreate ? `<button class="btn pri" data-act="new">+ New ${cfg.noun}</button>` : ''}`);
  setBody(`${cmp && cmp.length ? `<div class="c" style="margin-bottom:16px"><div class="hd"><div><h2>Best value comparison</h2><small>Based on total quoted price. Check lead time, scope and terms before deciding; currencies stay separate.</small></div></div>${plainTable(cmp)}</div>` : ''}
    <div class="tools"><div class="sbox"><input id="q" placeholder="Search ${esc(PAGES[key][0].toLowerCase())}…" aria-label="Search"></div>
    ${cfg.views.length > 1 ? `<div class="seg" id="views">${cfg.views.map(v => `<button data-v="${v}">${v}</button>`).join('')}</div>` : ''}<span class="count" id="count"></span></div>
    <div class="chips" id="filters" style="margin:-4px 4px 16px"></div><div id="recs"></div><div class="bulkbar hidden" id="bulkbar"></div>`);
  const paint = () => {
    const q = state.q.toLowerCase();
    let list = rows.filter(r => !q || Object.values(r).some(v => String(v ?? '').toLowerCase().includes(q)));
    $$('#views button').forEach(b => b.classList.toggle('on', b.dataset.v === state.view));
    const mineChip = key === 'approvals' && ME.accounts ? ['awaiting me'] : [];
    const chipList = state.view === 'board' ? (mineChip.length ? ['all', ...mineChip] : []) : ['all', ...(cfg.statuses || []), ...mineChip, ...(cfg.date ? ['overdue'] : [])];
    if (!chipList.includes(state.filter)) state.filter = 'all';
    const showFilters = !!cfg.statuses && chipList.length > 0;
    $('#filters').innerHTML = showFilters ? chipList.map(s => `<button data-f="${s}" class="${state.filter === s ? 'on' : ''}">${human(s)}</button>`).join('') : '';
    if (showFilters && state.filter === 'overdue') list = list.filter(r => r[cfg.date] && r[cfg.date] < isoToday() && r[cfg.status] !== 'done');
    else if (showFilters && state.filter === 'awaiting me') list = list.filter(r => r.mine);
    else if (showFilters && state.filter !== 'all') list = list.filter(r => r[cfg.status] === state.filter);
    if (state.view === 'table' && state.sort) { const { k, dir } = state.sort; list = [...list].sort((a, b) => { const x = a[k], y = b[k], nx = Number(x), ny = Number(y); return (x !== '' && y !== '' && !isNaN(nx) && !isNaN(ny) ? nx - ny : String(x ?? '').localeCompare(String(y ?? ''))) * dir; }); }
    $('#count').textContent = `${list.length} ${list.length === 1 ? 'record' : 'records'}`;
    let html;
    if (!rows.length) html = empty(`No ${PAGES[key][0].toLowerCase()} yet`, canCreate ? `Use “New ${cfg.noun}” to add the first one.` : 'They appear here automatically.');
    else if (state.view === 'board') html = `<div class="board">${cfg.statuses.map(s => { const c = list.filter(r => r[cfg.status] === s); return `<div class="col" data-s="${s}"><h4>${human(s)} <em>${c.length}</em></h4>${c.map(r => cardHtml(key, r, cfg)).join('') || '<div class="mt">Nothing here</div>'}</div>`; }).join('')}</div>`;
    else if (state.view === 'timeline') html = auditHtml(list);
    else if (state.view === 'cards') html = list.length ? `<div class="cards">${list.map(r => cardHtml(key, r, cfg)).join('')}</div>` : empty('No matching records');
    else html = tableHtml(key, list, cfg, state.sort);
    $('#recs').innerHTML = html;
    shownIds = list.map(r => r.id);
    renderBulkBar();
  };
  repaintRecords = paint;
  $('#q').oninput = e => { state.q = e.target.value; paint(); };
  $('#views') && ($('#views').onclick = e => { const b = e.target.closest('[data-v]'); if (b) { state.view = b.dataset.v; store.set('aos-view-' + key, state.view); paint(); } });
  $('#filters').onclick = e => { const b = e.target.closest('[data-f]'); if (b) { state.filter = b.dataset.f; paint(); } };
  $('#recs').addEventListener('click', e => { const th = e.target.closest('th[data-sort]'); if (!th) return; const k = th.dataset.sort; state.sort = state.sort && state.sort.k === k ? { k, dir: -state.sort.dir } : { k, dir: 1 }; paint(); });
  paint();
  if (window._pendingSearch) { state.q = window._pendingSearch; $('#q').value = state.q; window._pendingSearch = null; paint(); }
}

/* drag & drop between board columns */
let dragId = null;
document.addEventListener('dragstart', e => { const c = e.target.closest && e.target.closest('.card[draggable]'); if (c) { dragId = c.dataset.id; c.classList.add('drag'); e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', dragId); } });
document.addEventListener('dragend', () => { $$('.card.drag').forEach(c => c.classList.remove('drag')); $$('.col.over').forEach(c => c.classList.remove('over')); });
document.addEventListener('dragover', e => { const col = e.target.closest && e.target.closest('.col'); if (col && dragId) { e.preventDefault(); $$('.col.over').forEach(c => c !== col && c.classList.remove('over')); col.classList.add('over'); } });
document.addEventListener('drop', async e => {
  const col = e.target.closest && e.target.closest('.col');
  if (!col || !dragId) return;
  e.preventDefault();
  const id = Number(dragId); dragId = null;
  try { await api('status', { method: 'POST', body: JSON.stringify({ table: active, id, status: col.dataset.s }) }); msg('Moved to ' + human(col.dataset.s)); render(active); }
  catch (ex) { msg(ex.message); }
});

/* ---------- drawer (create / edit / decide) ---------- */
function closeLayer() {
  $('#layer').innerHTML = ''; document.removeEventListener('keydown', escClose);
  const o = window._opener; window._opener = null;
  if (o && document.contains(o) && typeof o.focus === 'function') o.focus();
}
function escClose(e) { if (e.key === 'Escape') closeLayer(); }
function drawer(title, inner, submitLabel, onSubmit) {
  window._opener = document.activeElement;
  $('#layer').innerHTML = `<div class="back" id="back"><aside class="drawer" role="dialog" aria-modal="true" aria-label="${esc(title)}"><header><h2>${esc(title)}</h2><button class="ib" data-act="close" aria-label="Close">×</button></header><form id="dform">${inner}<div class="fx"><button type="button" class="btn" data-act="close">Cancel</button><button class="btn pri" type="submit">${esc(submitLabel)}</button></div></form></aside></div>`;
  $('#back').onclick = e => { if (e.target.id === 'back') closeLayer(); };
  document.addEventListener('keydown', escClose);
  $('#back').addEventListener('keydown', e => {
    if (e.key !== 'Tab') return;
    const f = $$('#back button, #back input, #back select, #back textarea');
    if (!f.length) return;
    const first = f[0], last = f[f.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  });
  $('#dform').onsubmit = async e => { e.preventDefault(); try { await onSubmit(Object.fromEntries(new FormData(e.target).entries())); } catch (ex) { msg(ex.message); } };
  const f = $('#dform input,#dform select,#dform textarea'); if (f) f.focus();
}
function fieldHtml([name, label, type = 'text', required], value = '') {
  const id = 'f_' + name, req = required ? '<i>*</i>' : '';
  if (type.startsWith('select:')) return `<div class="field"><label for="${id}">${esc(label)}</label><select id="${id}" name="${name}">${type.slice(7).split(',').map(v => `<option value="${v}" ${String(value) === v ? 'selected' : ''}>${human(v)}</option>`).join('')}</select></div>`;
  if (type === 'area') return `<div class="field"><label for="${id}">${esc(label)}${req}</label><textarea id="${id}" name="${name}" ${required ? 'required' : ''} placeholder="${esc(label)}">${esc(value)}</textarea></div>`;
  return `<div class="field"><label for="${id}">${esc(label)}${req}</label><input id="${id}" name="${name}" type="${type}" ${type === 'number' ? 'step="any"' : ''} ${required ? 'required' : ''} value="${esc(value)}" placeholder="${esc(label)}"></div>`;
}
/* ---------- notifications ---------- */
const dismissed = () => { try { return new Set(JSON.parse(store.get('aos-dismissed', '[]'))); } catch (e) { return new Set(); } };
const saveDismissed = set => store.set('aos-dismissed', JSON.stringify([...set].slice(-400)));
const ukey = k => (ME.user ? ME.user.username : 'local') + '|' + k;
const liveNotes = () => { const d = dismissed(); return NOTES.filter(n => !d.has(ukey(n.key))); };
let seenKeys = null;
function setNotes(list) {
  NOTES = list;
  if (seenKeys && store.get('aos-desktop', '') === '1' && 'Notification' in window && Notification.permission === 'granted') {
    liveNotes().filter(n => !seenKeys.has(n.key)).slice(0, 3).forEach(n => { try { new Notification(n.title, { body: n.detail, tag: n.key }); } catch (e) { /* not supported here */ } });
  }
  seenKeys = new Set(liveNotes().map(n => n.key));
  paintBell();
}
function paintBell() {
  const n = liveNotes().length, b = $('#bell .bn');
  if (!b) return;
  b.textContent = n > 99 ? '99+' : n;
  b.classList.toggle('hidden', !n);
  $('#bell').setAttribute('aria-label', n ? `Notifications, ${n} need attention` : 'Notifications');
}
function drawNotes() {
  const el = $('#notebody');
  if (!el) return;
  const list = liveNotes();
  const alerts = 'Notification' in window && Notification.permission !== 'denied';
  const on = store.get('aos-desktop', '') === '1' && alerts && Notification.permission === 'granted';
  el.innerHTML = (list.length
    ? `<div class="feed">${list.map(n => `<div class="fi nt"><span class="sv ${n.severity === 'high' ? 'high' : ''}"></span><button class="ntmain" data-go="${esc(n.page)}"><b>${esc(n.title)}</b><small>${esc(n.detail)}</small></button><button class="ln" data-act="dismiss" data-key="${esc(n.key)}" aria-label="Dismiss ${esc(n.title)}">Dismiss</button></div>`).join('')}</div>`
    : empty('You are all caught up', 'Nothing needs your attention right now.'))
    + `<div class="acts" style="margin-top:16px">${list.length ? '<button class="btn sm" data-act="dismissall">Dismiss all</button>' : ''}${alerts ? `<button class="btn sm" data-act="desktop">${on ? 'Turn off desktop alerts' : 'Turn on desktop alerts'}</button>` : ''}</div>
    <p style="margin-top:14px;font-size:12.5px;color:var(--muted)">Alerts update every minute while this page is open. Dismissing only hides an alert on this browser; it comes back if something new happens, such as the next approval step.</p>`;
}
async function openNotifications() {
  window._opener = document.activeElement;
  $('#layer').innerHTML = '<div class="back" id="back"><aside class="drawer" role="dialog" aria-modal="true" aria-label="Notifications"><header><h2>Notifications</h2><button class="ib" data-act="close" aria-label="Close">×</button></header><div id="notebody"></div></aside></div>';
  $('#back').onclick = e => { if (e.target.id === 'back') closeLayer(); };
  document.addEventListener('keydown', escClose);
  drawNotes();
  try { setNotes(await api('notifications')); drawNotes(); } catch (e) { /* keep what we have */ }
}
async function loadPeople() { try { PEOPLE = await api('people'); } catch (e) { PEOPLE = []; } }
function personSelect([name, label, , required], value, exclude) {
  const val = String(value || '').toLowerCase(), skip = String(exclude || '').toLowerCase();
  const opts = PEOPLE.filter(p => p.username.toLowerCase() !== skip && p.display_name.toLowerCase() !== skip)
    .map(p => `<option value="${esc(p.username)}" ${p.username.toLowerCase() === val || p.display_name.toLowerCase() === val ? 'selected' : ''}>${esc(p.display_name)} (@${esc(p.username)})</option>`).join('');
  return `<div class="field"><label for="f_${name}">${esc(label)}${required ? '<i>*</i>' : ''}</label><select id="f_${name}" name="${name}" ${required ? 'required' : ''}><option value="">${required ? 'Choose a person…' : '— none —'}</option>${opts}</select></div>`;
}
function formFields(key, src, row) {
  const byUser = key === 'approvals' && ME.accounts;
  return defs[key].filter(f => !(byUser && f[0] === 'requester'))
    .map(f => byUser && (f[0] === 'approver' || f[0] === 'second_approver')
      ? personSelect(f, src ? src[f[0]] : '', row ? row.requester : (ME.user ? ME.user.username : ''))
      : fieldHtml(f, src ? src[f[0]] ?? '' : '')).join('');
}

function openForm(key, row, preset) {
  const cfg = RES[key], src = row || preset;
  const resubmit = !!(preset && preset._resubmit);
  drawer(row ? `Edit ${cfg.noun}` : resubmit ? 'Resubmit request' : preset ? `Duplicate ${cfg.noun}` : `New ${cfg.noun}`, formFields(key, src, row), row ? 'Save changes' : resubmit ? 'Resubmit' : 'Create', async d => {
    if (row) await api(`${key}/${row.id}`, { method: 'PUT', body: JSON.stringify(d) });
    else { if (resubmit) d.previous_id = preset.id; await api(key, { method: 'POST', body: JSON.stringify(d) }); }
    closeLayer(); msg(row ? 'Changes saved' : resubmit ? 'Request resubmitted' : 'Record created'); render(key);
  });
}
function openDecision(id, decision) {
  const ok = decision === 'approved';
  drawer(ok ? 'Approve request' : 'Reject request', `<p>${ok ? 'Confirm approval.' : 'Confirm rejection.'} The decision is final and is written to the audit history.</p><div class="field"><label for="c">Comment (optional)</label><textarea id="c" name="comment" placeholder="Add context for the requester"></textarea></div>`, ok ? 'Approve' : 'Reject', async d => {
    const r = await api('approvals/decision', { method: 'POST', body: JSON.stringify({ id: Number(id), decision, comment: d.comment || '' }) });
    closeLayer(); msg(r.status === 'pending' ? `Step ${r.stage} approved. Waiting for the next approver.` : `Request ${r.status}`); render(active);
  });
}

/* ---------- automation ---------- */
async function automationView() {
  const [c, runs] = await Promise.all([api('automation/settings'), api('automation/runs')]);
  const rule = (n, t, d) => `<label class="rule"><span><b>${t}</b><small>${d}</small></span><span class="sw"><input type="checkbox" name="${n}" ${c[n] ? 'checked' : ''}><span></span></span></label>`;
  setActions(can.write ? '<button class="btn pri" id="runNow" data-act="runrules">Run all active rules</button>' : '');
  setBody(`<div class="bento"><section class="c s7"><div class="hd"><div><h2>Automation rules</h2><small>Choose which controls run every five minutes</small></div></div>
    <form id="aform" class="stack">${rule('task_rule', 'Task deadline monitoring', 'Alerts for overdue and upcoming tasks')}${rule('contract_rule', 'Contract obligation monitoring', 'Tracks upcoming contractual commitments')}${rule('revenue_rule', 'Revenue leakage detection', 'Compares billed amounts with approved tariffs')}${rule('auto_resolve', 'Automatic resolution', 'Closes alerts when the underlying condition clears')}
    <div class="field"><label for="dd">Early-warning window (days)</label><input id="dd" name="due_days" type="number" min="1" max="90" value="${c.due_days}"></div>
    <div class="field"><label for="sat">Require a second approver at or above this amount (0 = off)</label><input id="sat" name="second_approval_threshold" type="number" min="0" step="1" value="${c.second_approval_threshold}"></div>
    <div class="field"><label for="esc">Flag a pending request as stuck after this many days (0 = off)</label><input id="esc" name="approval_escalate_days" type="number" min="0" max="60" step="1" value="${c.approval_escalate_days}"></div><div><button class="btn dark" type="submit">Save automation settings</button></div></form></section>
    <section class="c s5"><div class="hd"><div><h2>Last run</h2><small>Manual and scheduled scans use the same rules</small></div></div><div class="note" id="runResult">${runs[0] ? `${esc(runs[0].started_at.slice(0, 19).replace('T', ' '))} · ${runs[0].detected} detected, ${runs[0].created} new, ${runs[0].resolved} resolved (${esc(runs[0].trigger)})` : 'No scan has run yet.'}</div><p style="margin-top:14px">Automations create reviewable exceptions. They never send messages, approve purchases or move money.</p></section>
    <section class="c s12"><div class="hd"><div><h2>Run history</h2><small>Detection, creation and auto-resolution results</small></div></div>${plainTable(runs)}</section></div>`);
  if (!can.admin) $$('#aform input, #aform button').forEach(x => { x.disabled = true; });
  $('#aform').onsubmit = async e => {
    e.preventDefault();
    const f = new FormData(e.target);
    try { await api('automation/settings', { method: 'POST', body: JSON.stringify({ task_rule: f.has('task_rule'), contract_rule: f.has('contract_rule'), revenue_rule: f.has('revenue_rule'), auto_resolve: f.has('auto_resolve'), due_days: Number(f.get('due_days')), second_approval_threshold: Number(f.get('second_approval_threshold') || 0), approval_escalate_days: Number(f.get('approval_escalate_days') || 0) }) }); msg('Automation settings saved'); }
    catch (ex) { msg(ex.message); }
  };
}

/* ---------- reports ---------- */
async function reportsView() {
  const [r, bks] = await Promise.all([api('reports/executive'), can.admin ? api('backups') : Promise.resolve(null)]);
  const backupCard = !bks ? '' : `<section class="c s12"><div class="hd"><div><h2>Automatic backups</h2><small>A snapshot is saved daily to the data/backups folder. The newest 14 are kept.</small></div><button class="btn sm" data-act="backupnow">Back up now</button></div>${bks.length ? `<div class="feed">${bks.map(b => `<div class="fi"><div><b>${esc(b.name)}</b><small>${(b.size / 1024).toFixed(1)} KB · ${esc(b.modified.slice(0, 16).replace('T', ' '))}</small></div><div class="rt"><button class="btn sm bad" data-act="restorebk" data-name="${esc(b.name)}">Restore</button></div></div>`).join('')}</div>` : empty('No automatic backups yet', 'Use Back up now to create the first one.')}</section>`;
  const money = (o, l, k) => Object.entries(o).map(([cur, v]) => `<div class="c kpi s3" style="--k:${k};cursor:default"><span class="l"><i></i>${l}</span><b style="font-size:32px">${num(v)}</b><span class="n">${esc(cur)}</span></div>`).join('');
  setActions('<button class="btn" data-act="print">Print report</button><button class="btn" data-act="dlreport">Download report</button>' + (can.admin ? '<button class="btn pri" data-act="dlbackup">Download full backup</button>' : ''));
  window._report = r;
  setBody(`<div class="bento">${money(r.potential_leakage, 'Potential leakage', 'var(--bad)') || ''}${money(r.quote_savings_opportunity, 'Quote opportunity', 'var(--good)') || `<div class="c kpi s3" style="--k:var(--good);cursor:default"><span class="l"><i></i>Quote opportunity</span><b>0</b><span class="n">Add comparable quotations</span></div>`}
    <div class="c kpi s3" style="--k:var(--blue);cursor:default"><span class="l"><i></i>Generated</span><b style="font-size:26px">${esc(r.generated_at.slice(0, 10))}</b><span class="n">Live local data</span></div>
    <section class="c s6"><div class="hd"><div><h2>Workload by owner</h2><small>Assignment, completion and overdue exposure</small></div></div>${plainTable(r.workload)}</section>
    <section class="c s6"><div class="hd"><div><h2>Workload by department</h2><small>Total and open task volume</small></div></div>${plainTable(r.departments)}</section>
    <section class="c s6"><div class="hd"><div><h2>Open exception severity</h2><small>Current risk distribution</small></div></div>${plainTable(r.exception_severity)}</section>
    <section class="c s6"><div class="hd"><div><h2>Data backup</h2><small>Portable JSON snapshot of all local records</small></div></div><p>A backup contains operational records, settings, audit history and automation runs. Store it securely because it may include business data.</p>${can.admin ? `<div class="note"><b>Restore</b> replaces current tasks, approvals, quotes, contracts, rates, billing and exceptions with the contents of a backup file. Download a fresh backup first.</div><div class="acts" style="margin-top:12px"><label class="btn bad" for="restoreFile" style="cursor:pointer">Restore from backup…</label><input id="restoreFile" type="file" accept=".json,application/json" class="hidden"></div>` : ''}</section>${backupCard}</div>`);
  if ($('#restoreFile')) $('#restoreFile').onchange = async e => {
    const f = e.target.files[0]; if (!f) return;
    try {
      const data = JSON.parse(await f.text());
      if (!confirm(`Replace the current data with the backup "${f.name}"? This cannot be undone.`)) return;
      const r = await api('restore', { method: 'POST', body: JSON.stringify(data) });
      msg(`Restored ${Object.values(r.restored).reduce((a, b) => a + b, 0)} records`); render('reports');
    } catch (ex) { msg('Restore failed: ' + ex.message); } finally { e.target.value = ''; }
  };
}

/* ---------- tools ---------- */
function assistant() {
  setBody(`<div class="bento"><section class="c s8"><div class="hd"><div><h2>Ask your local model</h2><small>Runs on your computer through Ollama. No cloud account needed.</small></div></div>
    <div class="field"><label for="prompt">Prompt</label><textarea id="prompt" style="min-height:150px" placeholder="Analyze the following supplier terms and identify unclear clauses…"></textarea></div>
    <div class="acts" style="margin:14px 0"><button class="btn pri" id="ask">Generate draft</button></div><pre id="answer" class="aianswer"></pre></section>
    <section class="c s4"><div class="hd"><h2>Setup</h2></div><p>Install Ollama, then run:</p><pre>ollama pull llama3.2:3b</pre><div class="note" style="margin-top:14px">AI output is a draft for analysis and summaries. It is not authorised to approve purchases, issue regulatory findings or make binding financial decisions.</div></section></div>`);
  $('#ask').onclick = async () => {
    const b = $('#ask'); b.disabled = true; b.textContent = 'Processing locally…';
    try { $('#answer').textContent = (await api('ai', { method: 'POST', body: JSON.stringify({ prompt: $('#prompt').value }) })).answer; }
    catch (e) { $('#answer').textContent = 'Error: ' + e.message; }
    finally { b.disabled = false; b.textContent = 'Generate draft'; }
  };
}
function importsView() {
  if (!can.write) return setBody(empty('View-only access', 'Importing needs a member role or higher.'));
  let table = 'tasks';
  setBody(`<div class="bento"><section class="c s7"><div class="hd"><div><h2>Import a spreadsheet</h2><small>Export the sheet as CSV using the column names shown on the right</small></div></div>
    <div class="grp">1 · Destination</div><div class="chips" id="dest" style="margin-bottom:18px">${Object.keys(defs).map(k => `<button data-t="${k}" class="${k === table ? 'on' : ''}">${esc(PAGES[k][0])}</button>`).join('')}</div>
    <div class="grp">2 · CSV file</div><label class="drop" id="drop"><b id="dname">Drop a CSV here or click to browse</b>Other columns are ignored. No deduplication is performed.<input id="file" type="file" accept=".csv,text/csv"></label>
    <div class="acts" style="margin-top:16px"><button class="btn pri" id="upload">Import records</button></div><div id="importResult" style="margin-top:16px"></div></section>
    <section class="c s5"><div class="hd"><div><h2>Column names</h2><small>Required fields are marked *</small></div></div>${Object.entries(defs).map(([k, v]) => `<details ${k === table ? 'open' : ''}><summary>${esc(PAGES[k][0])}</summary><code>${v.map(x => x[0] + (x[3] ? '*' : '')).join(', ')}</code></details>`).join('')}</section></div>`);
  $('#dest').onclick = e => { const b = e.target.closest('[data-t]'); if (b) { table = b.dataset.t; $$('#dest button').forEach(x => x.classList.toggle('on', x === b)); } };
  const file = $('#file'), drop = $('#drop');
  file.onchange = () => { $('#dname').textContent = file.files[0] ? file.files[0].name : 'Drop a CSV here or click to browse'; };
  ['dragenter', 'dragover'].forEach(n => drop.addEventListener(n, e => { e.preventDefault(); drop.classList.add('over'); }));
  ['dragleave', 'drop'].forEach(n => drop.addEventListener(n, e => { e.preventDefault(); drop.classList.remove('over'); }));
  drop.addEventListener('drop', e => { if (e.dataTransfer.files[0]) { file.files = e.dataTransfer.files; file.onchange(); } });
  $('#upload').onclick = async () => {
    const f = file.files[0];
    if (!f) return msg('Select a CSV file');
    try {
      const r = await api('import', { method: 'POST', body: JSON.stringify({ table, csv: await f.text() }) });
      $('#importResult').innerHTML = `<div class="note"><b>${r.inserted}</b> imported · <b>${r.failed}</b> failed</div>${r.errors.length ? `<pre style="margin-top:10px">${esc(r.errors.map(x => `Line ${x.line}: ${x.error}`).join('\n'))}</pre>` : ''}`;
      msg(`Imported ${r.inserted} records`);
    } catch (e) { msg('Import failed: ' + e.message); }
  };
}
async function loadDemo() {
  if (!confirm('Add demonstration records to your local database?')) return;
  const d = new Date(); d.setDate(d.getDate() + 7);
  const due = d.toISOString().slice(0, 10);
  const sample = [
    ['tasks', { title: 'Confirm supplier insurance certificate', department: 'Procurement', owner: 'Operations', due_date: due, priority: 'high' }],
    ['contracts', { contract: 'Example ground handling agreement', counterparty: 'Demo Supplier', obligation: 'Review insurance expiry evidence', owner: 'Legal', due_date: due }],
    ['quotations', { rfq: 'DEMO-RFQ-01', supplier: 'Supplier A', item: 'Sample maintenance consumable', quantity: 5, unit_price: '90', currency: 'USD', lead_days: 4 }],
    ['quotations', { rfq: 'DEMO-RFQ-01', supplier: 'Supplier B', item: 'Sample maintenance consumable', quantity: 5, unit_price: '85', currency: 'USD', lead_days: 10 }],
    ['tariffs', { service: 'DEMO-TRANSIT', customer: '*', currency: 'USD', rate: '80', unit: 'each' }],
    ['transactions', { ref: 'DEMO-INV-01', service: 'DEMO-TRANSIT', customer: 'Demo Customer', billed: '65', units: '1', currency: 'USD' }]
  ];
  try {
    for (const [t, r] of sample) await api(t, { method: 'POST', body: JSON.stringify(r) });
    await api('scan', { method: 'POST', body: '{}' });
    msg('Sample data added and rules scanned'); render('dashboard');
  } catch (e) { msg('Error: ' + e.message); }
}
async function runScan(btn) {
  if (btn) { btn.disabled = true; }
  try {
    const r = await api('scan', { method: 'POST', body: '{}' });
    msg(`Scan complete: ${r.detected} detected, ${r.new} new, ${r.resolved} resolved`);
    render(active);
  } catch (e) { msg(e.message); }
  finally { if (btn) btn.disabled = false; }
}

/* ---------- command palette ---------- */
function openPalette() {
  const cmds = [
    ...Object.keys(PAGES).filter(visible).map(k => ({ icon: k, label: PAGES[k][0], hint: groupOf(k)[0], run: () => go(k) })),
    { icon: 'automation', label: 'Run automation scan', hint: 'Action', run: () => runScan() },
    { icon: 'dashboard', label: 'Toggle light / dark theme', hint: 'Action', run: toggleTheme },
    ...(can.write ? ['tasks', 'approvals', 'contracts', 'quotations'] : []).map(k => ({ icon: k, label: `New ${RES[k].noun}`, hint: 'Create', run: async () => { go(k); await render(k); openForm(k); } }))
  ];
  window._opener = document.activeElement;
  let sel = 0, list = cmds, hits = [], timer = null, seq = 0;
  const all = () => [...list, ...hits];
  $('#layer').innerHTML = `<div class="pal" id="pal"><div class="pbox"><input id="pq" placeholder="Jump to a page, run an action, or find a record…" autocomplete="off" aria-label="Command"><div class="plist" id="pl"></div></div></div>`;
  const paint = () => {
    const items = all();
    $('#pl').innerHTML = items.map((c, i) => `${i === list.length && hits.length ? '<div class="grp" style="padding:10px 12px 4px">Records</div>' : ''}<button data-i="${i}" class="${i === sel ? 'on' : ''}">${svg(c.icon)}${esc(c.label)}<small>${esc(c.hint)}</small></button>`).join('') || '<div class="mt">No matches</div>';
    const on = $('#pl .on'); if (on) on.scrollIntoView({ block: 'nearest' });
  };
  const pick = i => { const c = all()[i]; if (!c) return; closeLayer(); c.run(); };
  $('#pq').oninput = e => {
    const q = e.target.value.trim().toLowerCase();
    list = cmds.filter(c => c.label.toLowerCase().includes(q) || c.hint.toLowerCase().includes(q));
    hits = []; sel = 0; paint(); clearTimeout(timer);
    if (q.length < 2) return;
    const mine = ++seq;
    timer = setTimeout(async () => {
      try {
        const found = await api('search?q=' + encodeURIComponent(q));
        if (mine !== seq || !$('#pq')) return;
        hits = found.map(h => ({ icon: h.table, label: h.title, hint: (PAGES[h.table] ? PAGES[h.table][0] : h.table) + (h.sub ? ' · ' + h.sub : ''), run: () => { window._pendingSearch = h.title; go(h.table); } }));
        paint();
      } catch (ex) { /* search is a convenience */ }
    }, 180);
  };
  $('#pq').onkeydown = e => {
    const n = all().length;
    if (e.key === 'ArrowDown') { sel = Math.min(sel + 1, n - 1); paint(); e.preventDefault(); }
    else if (e.key === 'ArrowUp') { sel = Math.max(sel - 1, 0); paint(); e.preventDefault(); }
    else if (e.key === 'Enter') pick(sel);
  };
  $('#pl').onclick = e => { const b = e.target.closest('[data-i]'); if (b) pick(Number(b.dataset.i)); };
  $('#pal').onclick = e => { if (e.target.id === 'pal') closeLayer(); };
  document.addEventListener('keydown', escClose);
  paint(); $('#pq').focus();
}

/* ---------- accounts, sign-in and users ---------- */
async function refreshMe() {
  ME = await api('auth/me');
  applyChrome();
  if (!visible(active)) go('dashboard');
}
function applyChrome() {
  $('#scan').classList.toggle('hidden', !can.write);
  const chip = $('#userchip');
  if (ME.accounts && ME.user) {
    const n = ME.user.display_name;
    chip.innerHTML = `<span class="av">${esc(n.split(/\s+/).map(w => w[0]).join('').slice(0, 2).toUpperCase())}</span><span class="nm">${esc(n)}</span>`;
    chip.title = `${n} (${ME.user.role})`;
  } else { chip.innerHTML = '<span class="av">L</span><span class="nm">Local mode</span>'; chip.title = 'Single-user mode'; }
  const b = $('#banner');
  if (!ME.accounts && store.get('aos-banner-off', '') !== '1') {
    b.innerHTML = '<span><b>Single-user mode.</b> Anyone who opens this app has full access, and approvals are not tied to a person.</span><span class="row"><button class="btn sm" data-act="setup">Set up accounts</button><button class="btn sm" data-act="hidebanner">Dismiss</button></span>';
    b.classList.remove('hidden');
  } else if (ME.accounts && ME.user && ME.user.delegate_to) {
    b.innerHTML = `<span><b>You are out of office.</b> ${esc(person(ME.user.delegate_to))} is covering your approvals until ${esc(ME.user.delegate_until)}.</span><span class="row"><button class="btn sm" data-act="account">Manage</button></span>`;
    b.classList.remove('hidden');
  } else b.classList.add('hidden');
  nav();
}
async function start() {
  $('#auth').classList.add('hidden');
  $('#auth').innerHTML = '';
  READY = true;
  await loadPeople();
  applyChrome();
  route();
}
function showLogin() {
  READY = false;
  document.body.dataset.rendered = '';
  NOTES = []; seenKeys = null; PEOPLE = []; paintBell();
  closeLayer();
  const a = $('#auth');
  a.classList.remove('hidden');
  a.innerHTML = `<form class="authcard" id="loginForm"><div class="logo"><i></i>Automation OS</div><div><h1>Sign in</h1><p>Use the account your administrator created for you.</p></div>
    <div class="field"><label for="lu">Username</label><input id="lu" name="username" autocomplete="username" required></div>
    <div class="field"><label for="lp">Password</label><input id="lp" name="password" type="password" autocomplete="current-password" required></div>
    <div id="lerr" class="note bad hidden" role="alert"></div><button class="btn pri" type="submit">Sign in</button></form>`;
  $('#loginForm').onsubmit = async e => {
    e.preventDefault();
    const btn = e.target.querySelector('button'); btn.disabled = true;
    try {
      const r = await api('auth/login', { method: 'POST', body: JSON.stringify(Object.fromEntries(new FormData(e.target))) });
      ME = { accounts: true, user: r.user };
      if (!location.hash) location.hash = '#/dashboard';
      start();
    } catch (ex) { const el = $('#lerr'); el.textContent = ex.message; el.classList.remove('hidden'); btn.disabled = false; $('#lp').select(); }
  };
  $('#lu').focus();
}
function openSetup() {
  drawer('Set up accounts', '<p>Create the first administrator. After this, everyone must sign in, roles are enforced, and approvals can only be decided by the person they are assigned to. Your existing data is kept.</p>'
    + fieldHtml(['display_name', 'Your name', 'text', 1]) + fieldHtml(['username', 'Username', 'text', 1])
    + fieldHtml(['password', 'Password (10+ characters)', 'password', 1]) + fieldHtml(['confirm', 'Confirm password', 'password', 1]),
  'Create administrator', async d => {
    if (d.password !== d.confirm) throw Error('Passwords do not match');
    const r = await api('auth/setup', { method: 'POST', body: JSON.stringify({ username: d.username, display_name: d.display_name, password: d.password }) });
    ME = { accounts: true, user: r.user };
    await loadPeople();
    closeLayer(); applyChrome(); msg('Accounts are on. You are signed in as administrator.'); render(active);
  });
}
function openChangePassword() {
  drawer('Change password', fieldHtml(['current', 'Current password', 'password', 1]) + fieldHtml(['new', 'New password (10+ characters)', 'password', 1]) + fieldHtml(['confirm', 'Confirm new password', 'password', 1])
    + '<div class="note">Changing your password signs you out everywhere else.</div>', 'Update password', async d => {
    if (d.new !== d.confirm) throw Error('The new passwords do not match');
    await api('auth/password', { method: 'POST', body: JSON.stringify({ current: d.current, new: d.new }) });
    closeLayer(); msg('Password updated. Other devices were signed out.');
  });
}
function awayHtml() {
  const u = ME.user;
  const on = u.delegate_to && u.delegate_until;
  const options = PEOPLE.filter(p => p.can_decide && p.username.toLowerCase() !== u.username.toLowerCase())
    .map(p => `<option value="${esc(p.username)}">${esc(p.display_name)} (@${esc(p.username)})</option>`).join('');
  const nextWeek = new Date(Date.now() + 7 * 864e5).toISOString().slice(0, 10);
  return `<div class="field"><label>Out of office</label>${on
    ? `<div class="note"><b>${esc(person(u.delegate_to))}</b> is covering your approvals until <b>${esc(u.delegate_until)}</b>.</div><div class="acts"><button type="button" class="btn" data-act="endaway">End cover now</button></div>`
    : `<div class="note">Going away? Hand your approvals to a colleague. They can decide requests assigned to you until the date you choose, then it ends by itself.</div><select id="aw_delegate" aria-label="Who covers for you"><option value="">Choose a colleague…</option>${options}</select><input id="aw_until" type="date" value="${nextWeek}" min="${isoToday()}" aria-label="Back on"><div class="acts"><button type="button" class="btn" data-act="startaway">Start cover</button></div>`}</div>`;
}
function openAccount() {
  if (!ME.accounts) return openSetup();
  const u = ME.user;
  drawer('Account', `<div class="stack"><div class="field"><label>Name</label><div><b>${esc(u.display_name)}</b></div></div><div class="field"><label>Username</label><div>@${esc(u.username)}</div></div><div class="field"><label>Role</label><div><span class="badge blue">${esc(u.role)}</span></div></div>${rank() >= 1 ? awayHtml() : ''}<div class="acts"><button type="button" class="btn" data-act="changepw">Change password</button><button type="button" class="btn bad" data-act="logoutall">Sign out of all devices</button></div><div class="note">Sessions last 12 hours. Approvals assigned to ${u.display_name.toLowerCase() === u.username.toLowerCase() ? `“${esc(u.display_name)}”` : `“${esc(u.display_name)}” or “${esc(u.username)}”`} show up as yours.</div></div>`,
  'Sign out', async () => {
    await api('auth/logout', { method: 'POST', body: '{}' });
    ME.user = null; showLogin();
  });
}
async function usersView() {
  if (!ME.accounts) {
    setBody('<div class="c"><div class="hd"><div><h2>Accounts are not set up</h2><small>Anyone who can open this app currently has full access.</small></div></div><p>Create the first administrator to turn on sign-in, roles and enforced approvals. Your existing data is kept.</p><button class="btn pri" data-act="setup">Set up accounts</button></div>');
    return;
  }
  const users = await api('users');
  window._users = users;
  setActions('<button class="btn pri" data-act="newuser">+ New user</button>');
  setBody(`<div class="cards">${users.map(u => `<article class="card"><div class="top"><h3>${esc(u.display_name)}</h3><span class="badge ${u.active ? 'good' : ''}">${u.active ? 'Active' : 'Disabled'}</span></div><div class="sub">@${esc(u.username)}</div><div class="meta"><span class="badge blue">${esc(u.role)}</span>${ME.user && u.id === ME.user.id ? '<span class="badge">You</span>' : ''}</div><div class="foot"><span class="sp"></span><button class="ln" data-act="edituser" data-id="${u.id}">Edit</button></div></article>`).join('')}</div>
    <div class="c" style="margin-top:16px"><div class="hd"><div><h2>What each role can do</h2></div></div><div class="stack">
    <div><span class="badge">viewer</span> Read-only access to every page.</div>
    <div><span class="badge blue">member</span> Create and edit records, import data, run scans, and decide approvals assigned to them.</div>
    <div><span class="badge warn">manager</span> Everything a member can do, plus deleting records.</div>
    <div><span class="badge good">admin</span> Everything, including users, automation settings, backups and restore. Can step in on any approval, but never on their own request.</div></div></div>`);
}
function openUserForm(u) {
  const f = [];
  if (!u) f.push(fieldHtml(['username', 'Username', 'text', 1]));
  f.push(fieldHtml(['display_name', 'Display name', 'text', 1], u ? u.display_name : ''));
  f.push(fieldHtml(['role', 'Role', 'select:viewer,member,manager,admin'], u ? u.role : 'member'));
  if (u) f.push(fieldHtml(['active', 'Status', 'select:yes,no'], u.active ? 'yes' : 'no'));
  f.push(fieldHtml(['password', u ? 'New password (leave blank to keep)' : 'Password (10+ characters)', 'password', !u]));
  f.push('<div class="note">Approvals match on the username or display name, so keep display names the same as the names people are assigned as approvers.</div>');
  drawer(u ? `Edit ${u.display_name}` : 'New user', f.join(''), u ? 'Save changes' : 'Create user', async d => {
    if (u) {
      const body = { display_name: d.display_name, role: d.role, active: d.active === 'yes' };
      if (d.password) body.password = d.password;
      await api(`users/${u.id}`, { method: 'PUT', body: JSON.stringify(body) });
      if (ME.user && u.id === ME.user.id) await refreshMe();
    } else await api('users', { method: 'POST', body: JSON.stringify(d) });
    await loadPeople();
    closeLayer(); msg(u ? 'User updated' : 'User created'); render('users');
  });
}
async function boot() {
  try { ME = await api('auth/me'); } catch (e) { ME = { accounts: false, user: null }; }
  if (ME.accounts && !ME.user) return showLogin();
  start();
}

/* ---------- global events ---------- */
document.addEventListener('click', async e => {
  const g = e.target.closest('[data-go]');
  if (g) { closeLayer(); return go(g.dataset.go); }
  const a = e.target.closest('[data-act]');
  if (!a) return;
  const act = a.dataset.act, id = a.dataset.id;
  if (act === 'close') return closeLayer();
  if (act === 'setup') return openSetup();
  if (act === 'selectmode') {
    selectMode = !selectMode; picked = new Set();
    const top = $('#pageactions [data-act=selectmode]'); if (top) top.textContent = selectMode ? 'Cancel selecting' : 'Select';
    return repaintRecords && repaintRecords();
  }
  if (act === 'pickall') { shownIds.forEach(id => picked.add(id)); return repaintRecords && repaintRecords(); }
  if (act === 'bulkstatus') return runBulk('status');
  if (act === 'bulkdelete') return runBulk('delete');
  if (act === 'bell') return openNotifications();
  if (act === 'changepw') return openChangePassword();
  if (act === 'account') return openAccount();
  if (act === 'startaway' || act === 'endaway') {
    const start = act === 'startaway';
    try {
      await api('auth/delegate', { method: 'POST', body: JSON.stringify(start ? { delegate: $('#aw_delegate').value, until: $('#aw_until').value } : { delegate: '', until: '' }) });
      await refreshMe(); msg(start ? 'Cover started' : 'Cover ended'); openAccount();
    } catch (ex) { msg(ex.message); }
    return;
  }
  if (act === 'logoutall') {
    if (!confirm('Sign out of every device, including this one?')) return;
    try { await api('auth/logout-all', { method: 'POST', body: '{}' }); closeLayer(); ME.user = null; showLogin(); } catch (ex) { msg(ex.message); }
    return;
  }
  if (act === 'dismiss') { const d = dismissed(); d.add(ukey(a.dataset.key)); saveDismissed(d); paintBell(); return drawNotes(); }
  if (act === 'dismissall') { const d = dismissed(); liveNotes().forEach(n => d.add(ukey(n.key))); saveDismissed(d); paintBell(); return drawNotes(); }
  if (act === 'desktop') {
    if (store.get('aos-desktop', '') === '1') { store.set('aos-desktop', ''); return drawNotes(); }
    const result = await Notification.requestPermission();
    if (result === 'granted') store.set('aos-desktop', '1'); else msg('Desktop alerts were not allowed by the browser');
    return drawNotes();
  }
  if (act === 'hidebanner') { store.set('aos-banner-off', '1'); return applyChrome(); }
  if (act === 'newuser') return openUserForm();
  if (act === 'edituser') { const u = (window._users || []).find(x => Number(x.id) === Number(id)); return u ? openUserForm(u) : msg('User not found'); }
  if (act === 'new') return openForm(active);
  if (act === 'edit') { const row = currentRows.find(r => Number(r.id) === Number(id)); return row ? openForm(active, row) : msg('Record not found'); }
  if (act === 'dup') { const row = currentRows.find(r => Number(r.id) === Number(id)); return row ? openForm(active, null, row) : msg('Record not found'); }
  if (act === 'withdraw') return openWithdraw(id);
  if (act === 'resubmit') { const row = currentRows.find(r => Number(r.id) === Number(id)); return row ? openForm('approvals', null, { ...row, _resubmit: true }) : msg('Record not found'); }
  if (act === 'del') {
    const key = active, row = currentRows.find(r => Number(r.id) === Number(id));
    const undoable = !!(row && defs[key] && !(key === 'approvals' && row.status !== 'pending'));
    if (!undoable && !confirm('Delete this record? A decided approval cannot be restored.')) return;
    try {
      await api(`${key}/${id}`, { method: 'DELETE' });
      if (active === key) render(key);
      msg('Record deleted', undoable ? { label: 'Undo', run: async () => {
        const d = {}; defs[key].forEach(f => { if (row[f[0]] != null) d[f[0]] = row[f[0]]; });
        try { await api(key, { method: 'POST', body: JSON.stringify(d) }); msg('Record restored'); if (active === key) render(key); }
        catch (ex) { msg('Undo failed: ' + ex.message); }
      } } : undefined);
    } catch (ex) { msg('Delete failed: ' + ex.message); }
    return;
  }
  if (act === 'decide') return openDecision(id, a.dataset.d);
  if (act === 'export') return exportCsv(currentRows, active);
  if (act === 'scan') return runScan(a);
  if (act === 'demo') return loadDemo();
  if (act === 'selall') return $$('.exc').forEach(x => x.checked = true);
  if (act === 'resolve') {
    const ids = $$('.exc:checked').map(x => Number(x.value));
    if (!ids.length) return msg('Select at least one exception');
    try { const r = await api('exceptions/bulk', { method: 'POST', body: JSON.stringify({ ids, status: 'done' }) }); msg(`${r.updated} exceptions resolved`); render('today'); } catch (ex) { msg(ex.message); }
    return;
  }
  if (act === 'runrules') return runScan(a);
  if (act === 'print') return window.print();
  if (act === 'backupnow') { try { const r = await api('backups', { method: 'POST', body: '{}' }); msg(r.name ? 'Backup saved: ' + r.name : 'A backup was already made this second'); render('reports'); } catch (ex) { msg(ex.message); } return; }
  if (act === 'restorebk') {
    if (!confirm(`Replace the current data with ${a.dataset.name}? This cannot be undone.`)) return;
    try { const r = await api('backups/restore', { method: 'POST', body: JSON.stringify({ name: a.dataset.name }) }); msg(`Restored ${Object.values(r.restored).reduce((x, y) => x + y, 0)} records`); render('reports'); } catch (ex) { msg('Restore failed: ' + ex.message); }
    return;
  }
  if (act === 'dlreport') return downloadJson(window._report, `automation-os-report-${stamp()}.json`);
  if (act === 'dlbackup') {
    a.disabled = true; a.textContent = 'Preparing…';
    try { downloadJson(await api('backup'), `automation-os-backup-${stamp()}.json`); msg('Backup downloaded'); } catch (ex) { msg(ex.message); }
    finally { a.disabled = false; a.textContent = 'Download full backup'; }
  }
});
document.addEventListener('change', async e => {
  if (e.target.id === 'pickall') { if (e.target.checked) shownIds.forEach(id => picked.add(id)); else picked = new Set(); return repaintRecords && repaintRecords(); }
  if (e.target.classList && e.target.classList.contains('pickbox')) { const id = Number(e.target.dataset.id); if (e.target.checked) picked.add(id); else picked.delete(id); return renderBulkBar(); }
  if (!e.target.matches('select.status')) return;
  try { await api('status', { method: 'POST', body: JSON.stringify({ table: e.target.dataset.table, id: Number(e.target.dataset.id), status: e.target.value }) }); msg('Status updated'); render(active); }
  catch (ex) { msg(ex.message); }
});
document.addEventListener('keydown', e => {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); if (READY) openPalette(); return; }
  if (!READY || e.ctrlKey || e.metaKey || e.altKey || $('#layer').firstChild || /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName || '')) return;
  if (e.key === '/') { const q = $('#q'); if (q) { e.preventDefault(); q.focus(); } }
  else if (e.key === 'n') { const b = $('[data-act=new]'); if (b) { e.preventDefault(); b.click(); } }
  else if (e.key === 'r' && can.write) runScan();
  else if (e.key === 't') toggleTheme();
});
$('#palette').onclick = openPalette;
$('#scan').onclick = e => runScan(e.currentTarget);
$('#themeToggle').onclick = toggleTheme;
$('#userchip').onclick = openAccount;
window.addEventListener('hashchange', route);
setInterval(paintScan, 30000);
setInterval(refreshBadges, 60000);
boot();
