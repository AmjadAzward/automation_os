// Browser smoke test. No npm packages: it drives Chrome/Edge over the DevTools protocol.
//
//   node tests/ui_smoke.mjs
//
// Needs Node 22+ (built-in WebSocket) and Chrome or Edge. Set BROWSER=/path/to/browser if it is not found.
// It starts its own server on a temporary database, so your real data is never touched.
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const PORT = 8800 + Math.floor(Math.random() * 90);
const CDP = 9500 + Math.floor(Math.random() * 90);
const BASE = `http://127.0.0.1:${PORT}`;
const PW = 'correct-horse-battery';
const SHOTS = process.env.SHOTS || '';

const candidates = [
  process.env.BROWSER,
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  '/usr/bin/google-chrome', '/usr/bin/chromium', '/usr/bin/chromium-browser', '/usr/bin/microsoft-edge',
].filter(Boolean);
const browser = candidates.find(p => fs.existsSync(p));
if (!browser) { console.error('No Chrome/Edge found. Set BROWSER=/path/to/browser'); process.exit(2); }

const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'aos-ui-'));
const sleep = ms => new Promise(r => setTimeout(r, ms));
const results = [];
const check = (name, ok, extra = '') => { results.push(ok); console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${ok || !extra ? '' : '  -> ' + extra}`); };

const server = spawn(process.platform === 'win32' ? 'python' : 'python3', [path.join(ROOT, 'app.py')], {
  cwd: ROOT, stdio: 'ignore', env: { ...process.env, AUTOMATION_DB: path.join(tmp, 'ui.sqlite3'), AUTOMATION_PORT: String(PORT) },
});
const chrome = spawn(browser, ['--headless=new', `--remote-debugging-port=${CDP}`, `--user-data-dir=${path.join(tmp, 'profile')}`, '--window-size=1440,900', ...(process.env.CI ? ['--no-sandbox', '--disable-dev-shm-usage'] : []), 'about:blank'], { stdio: 'ignore' });
const cleanup = () => { try { server.kill(); } catch {} try { chrome.kill(); } catch {} };
process.on('exit', cleanup);

async function until(fn, ms = 20000) { const t = Date.now(); while (Date.now() - t < ms) { try { const v = await fn(); if (v) return v; } catch {} await sleep(100); } return null; }
await until(async () => (await fetch(BASE + '/api/health')).ok, 15000) || (console.error('server did not start'), process.exit(2));
const tabs = await until(async () => { const t = await (await fetch(`http://127.0.0.1:${CDP}/json`)).json(); return t.find(x => x.type === 'page') ? t : null; }, 15000);
const ws = new WebSocket(tabs.find(t => t.type === 'page').webSocketDebuggerUrl);
await new Promise(r => { ws.onopen = r; });
let seq = 0; const pending = {}; const errors = [];
ws.onmessage = m => {
  const o = JSON.parse(m.data);
  if (o.id && pending[o.id]) { pending[o.id](o); delete pending[o.id]; }
  if (o.method === 'Runtime.exceptionThrown') errors.push(o.params.exceptionDetails.exception?.description || o.params.exceptionDetails.text);
  if (o.method === 'Runtime.consoleAPICalled' && o.params.type === 'error') errors.push('console.error ' + o.params.args.map(a => a.value || a.description).join(' '));
};
const send = (method, params = {}) => new Promise(r => { const id = ++seq; pending[id] = r; ws.send(JSON.stringify({ id, method, params })); });
const ev = async expr => { const r = await send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true }); if (r.result.exceptionDetails) throw new Error(r.result.exceptionDetails.exception?.description || 'eval failed'); return r.result.result.value; };
const shot = async name => { if (!SHOTS) return; fs.mkdirSync(SHOTS, { recursive: true }); fs.writeFileSync(path.join(SHOTS, name + '.png'), Buffer.from((await send('Page.captureScreenshot', { format: 'png' })).result.data, 'base64')); };
const waitFor = (expr, ms) => until(() => ev(expr), ms);
const goto = async hash => {
  await ev(`location.hash='${hash}'`);
  await waitFor(`document.body.dataset.rendered === '${hash.replace('#/', '')}'`, 40000);   // the app marks a page as drawn
  await sleep(150);
};
const setVal = (sel, v) => ev(`(()=>{const e=document.querySelector(${JSON.stringify(sel)});e.value=${JSON.stringify(v)};e.dispatchEvent(new Event('input',{bubbles:true}))})()`);
const click = sel => ev(`document.querySelector(${JSON.stringify(sel)}).click()`);
const submitDrawer = () => ev(`document.querySelector('#dform').requestSubmit()`);
const text = sel => ev(`document.querySelector(${JSON.stringify(sel)})?.innerText||''`);
const api = (method, p, body) => ev(`fetch('/api/${p}',{method:'${method}',headers:{'Content-Type':'application/json'},body:${body ? JSON.stringify(JSON.stringify(body)) : 'undefined'}}).then(async r=>({status:r.status,body:await r.json()}))`);

async function signIn(username, password = PW) {
  await waitFor(`!!document.querySelector('#loginForm')`);
  await setVal('#lu', username); await setVal('#lp', password);
  await ev(`document.querySelector('#loginForm').requestSubmit()`);
  // finished = signed in (login screen hidden) or the error message is showing
  await waitFor(`document.querySelector('#auth').classList.contains('hidden') || (document.querySelector('#lerr') && !document.querySelector('#lerr').classList.contains('hidden'))`, 40000);
}
async function signOut() {
  await click('#userchip'); await waitFor(`!!document.querySelector('#dform')`);
  await ev(`document.querySelector('#dform button[type=submit]').click()`);
  await waitFor(`!!document.querySelector('#loginForm')`);
}

try {
  await send('Page.enable'); await send('Runtime.enable');
  await send('Page.navigate', { url: BASE + '/' });
  await waitFor(`document.querySelector('#userchip')?.innerText.length>0`);

  // ---- single-user (open) mode
  check('tab title names the page', (await ev('document.title')).includes('Command Center · Automation OS'), await ev('document.title'));
  check('favicon is linked and served', (await ev(`document.querySelector('link[rel=icon]').href`)).includes('/favicon.svg') && (await ev(`fetch('/favicon.ico').then(r=>r.status+r.headers.get('content-type'))`)) === '200image/png');
  check('open mode shows setup banner and Local mode chip', (await ev(`!document.querySelector('#banner').classList.contains('hidden')`)) && (await text('#userchip')).includes('Local mode'));
  await goto('#/tasks');
  await click('[data-act=new]'); await waitFor(`!!document.querySelector('#f_title')`);
  await setVal('#f_title', 'Smoke test task'); await submitDrawer();
  check('create a task through the drawer', !!(await waitFor(`document.body.innerText.includes('Smoke test task')`)));
  await goto('#/approvals'); await shot('open-approvals');

  // ---- turn on accounts
  await click('[data-act=setup]'); await waitFor(`!!document.querySelector('#f_username')`);
  await setVal('#f_display_name', 'Olive Owner'); await setVal('#f_username', 'olive'); await setVal('#f_password', PW); await setVal('#f_confirm', PW); await submitDrawer();
  check('first administrator is created and signed in', !!(await waitFor(`document.querySelector('#userchip').innerText.includes('Olive Owner')`)));
  check('banner disappears once accounts exist', await ev(`document.querySelector('#banner').classList.contains('hidden')`));
  await goto('#/tasks');
  check('existing data survives turning on accounts', (await text('#content')).includes('Smoke test task'));

  // ---- users page
  await goto('#/users');
  check('admin sees Users & Roles', (await text('#title')) === 'Users & Roles');
  await click('[data-act=newuser]'); await waitFor(`!!document.querySelector('#f_username')`);
  await setVal('#f_username', 'ann'); await setVal('#f_display_name', 'Ann'); await setVal('#f_password', PW); await submitDrawer();
  check('create a user through the UI', !!(await waitFor(`document.body.innerText.includes('@ann')`)));
  for (const [u, n, role] of [['bob', 'Bob', 'member'], ['cyd', 'Cyd', 'member'], ['vic', 'Vic', 'viewer']]) {
    const r = await api('POST', 'users', { username: u, display_name: n, role, password: PW });
    if (r.status !== 200) check(`seed user ${u}`, false, JSON.stringify(r));
  }
  await goto('#/users'); await shot('users');
  await api('POST', 'automation/settings', { second_approval_threshold: 5000 });

  // ---- ann files a two-step request; the threshold forces a second approver
  await signOut(); await signIn('ann');
  await waitFor(`document.querySelector('#userchip').innerText.includes('Ann')`);
  check('member does not see Users & Roles', !(await ev(`[...document.querySelectorAll('#groups button,#subnav button')].some(b=>b.innerText.includes('Users'))`)));
  await goto('#/approvals'); await click('[data-act=new]'); await waitFor(`!!document.querySelector('#f_title')`);
  check('request form has no requester field once accounts exist', !(await ev(`!!document.querySelector('#f_requester')`)));
  check('approver is picked from a list of real people (not yourself)', await ev(`(() => { const o = [...document.querySelectorAll('#f_approver option')].map(x => x.value); return o.includes('bob') && o.includes('cyd') && !o.includes('ann'); })()`));
  await setVal('#f_title', 'Buy a crane'); await setVal('#f_approver', 'bob'); await setVal('#f_amount', '9000'); await submitDrawer();
  await sleep(600);
  check('threshold blocks a large request without a second approver', (await text('#message')).includes('second approver'), await text('#message'));
  await setVal('#f_second_approver', 'cyd'); await submitDrawer();
  await waitFor(`document.body.innerText.includes('Buy a crane')`);
  check('two-step request is created and shows both steps', (await text('#content')).includes('Bob') && (await text('#content')).includes('Cyd'));
  check('requester sees no bell alert for their own pending request', await ev(`document.querySelector('#bell .bn').classList.contains('hidden')`));
  check('requester cannot approve their own request', !(await ev(`!!document.querySelector('[data-act=decide]')`)) && (await text('#content')).includes('Waiting for Bob'));
  await shot('approval-ann');

  // ---- bob approves step 1
  await signOut(); await signIn('bob'); await waitFor(`document.querySelector('#userchip').innerText.includes('Bob')`);
  await goto('#/approvals');
  check('assigned approver sees Approve / Reject', !!(await waitFor(`!!document.querySelector('[data-act=decide]')`)));
  check('approvals tab badge counts what is waiting on me', (await waitFor(`document.querySelector('#subnav .dot')?.innerText === '1'`)) === true);
  check('bell shows the waiting request', !!(await waitFor(`document.querySelector('#bell .bn') && !document.querySelector('#bell .bn').classList.contains('hidden')`)));
  await click('#bell'); await waitFor(`!!document.querySelector('#notebody')`);
  check('notification panel explains what is needed', (await text('#notebody')).includes('Buy a crane') && (await text('#notebody')).includes('Waiting for your decision'));
  await shot('notifications');
  await ev(`document.querySelector('[data-act=dismiss]').click()`); await sleep(300);
  check('dismissing clears the alert', await ev(`document.querySelector('#bell .bn').classList.contains('hidden')`));
  await ev(`document.querySelector('[data-act=close]').click()`);
  check('someone else cannot edit or delete the request', !(await ev(`!!document.querySelector('[data-act=edit],[data-act=del]')`)));
  check('assigned approver sees "awaiting me" filter on cards', await ev(`(async () => { document.querySelector('#views [data-v=cards]').click(); await new Promise(r => setTimeout(r, 200)); return [...document.querySelectorAll('#filters button')].some(b => b.innerText.toLowerCase().includes('awaiting me')); })()`));
  await ev(`document.querySelector('#views [data-v=board]').click()`);
  await click('[data-act=decide][data-d=approved]'); await waitFor(`!!document.querySelector('#f_c')||!!document.querySelector('#dform')`);
  await ev(`document.querySelector('#c').value='Looks fine'`); await submitDrawer();
  check('step 1 approval keeps the request pending', !!(await waitFor(`document.querySelector('#message')?.innerText.includes('Step 1 approved')`)));
  await sleep(500);
  check('step 2 approver is shown by display name', (await text('#content')).includes('Cyd'));
  check('bob cannot also approve step 2', !(await ev(`!!document.querySelector('[data-act=decide]')`)) && (await text('#content')).includes('Waiting for Cyd'));

  // ---- cyd approves step 2
  await signOut(); await signIn('cyd'); await waitFor(`document.querySelector('#userchip').innerText.includes('Cyd')`);
  await goto('#/approvals'); await waitFor(`!!document.querySelector('[data-act=decide]')`);
  await click('[data-act=decide][data-d=approved]'); await waitFor(`!!document.querySelector('#dform')`); await submitDrawer();
  check('final approval completes the request', !!(await waitFor(`document.querySelector('#message')?.innerText.includes('Request approved')`)));
  await sleep(500); await shot('approval-done');
  check('approved card moves to the Approved column', await ev(`document.querySelector('.col[data-s=approved]')?.innerText.includes('Buy a crane')`));

  // ---- the requester is told the outcome
  await signOut(); await signIn('ann'); await waitFor(`document.querySelector('#userchip').innerText.includes('Ann')`);
  check('requester is notified of the outcome', !!(await waitFor(`!document.querySelector('#bell .bn').classList.contains('hidden')`)));
  await click('#bell'); await waitFor(`!!document.querySelector('#notebody')`);
  check('outcome message says it was approved', (await text('#notebody')).includes('was approved'));
  await ev(`document.querySelector('[data-act=close]').click()`);

  // ---- out-of-office cover
  const filed = await api('POST', 'approvals', { title: 'Cover test', approver: 'bob' });     // filed by ann, who is signed in
  check('requester files a request for bob', filed.status === 200, JSON.stringify(filed));
  await signOut(); await signIn('bob'); await waitFor(`document.querySelector('#userchip').innerText.includes('Bob')`);
  await click('#userchip'); await waitFor(`!!document.querySelector('#aw_delegate')`);
  check('colleague list only offers people who can decide (not viewers or yourself)', await ev(`(() => { const o = [...document.querySelectorAll('#aw_delegate option')].map(x => x.value); return o.includes('cyd') && !o.includes('bob') && !o.includes('vic'); })()`));
  await setVal('#aw_delegate', 'cyd'); await click('[data-act=startaway]');
  check('approver can start out-of-office cover', !!(await waitFor(`document.querySelector('#layer')?.innerText.includes('is covering your approvals')`)));
  await shot('away-drawer');
  await ev(`document.querySelector('[data-act=close]').click()`);
  check('banner reminds them while away', !!(await waitFor(`!document.querySelector('#banner').classList.contains('hidden') && document.querySelector('#banner').innerText.includes('out of office')`)));
  await signOut(); await signIn('cyd'); await waitFor(`document.querySelector('#userchip').innerText.includes('Cyd')`);
  await goto('#/approvals'); await waitFor(`!!document.querySelector('[data-act=decide]')`);
  check('the delegate sees the request marked as covering', (await text('#content')).toLowerCase().includes('covering for bob'), (await text('#content')).slice(0, 300));
  await click('[data-act=decide][data-d=approved]'); await waitFor(`!!document.querySelector('#dform')`); await submitDrawer();
  check('the delegate can approve it', !!(await waitFor(`document.querySelector('#message')?.innerText.includes('Request approved')`)));
  await sleep(500);
  const record = (await api('GET', 'approvals')).body.find(a => a.title === 'Cover test');
  check('the record shows who really decided and for whom', record && record.steps[0].decided_by === 'Cyd' && record.steps[0].acting_for === 'bob', JSON.stringify(record && record.steps));

  // ---- withdraw and resubmit
  await signOut(); await signIn('ann'); await waitFor(`document.querySelector('#userchip').innerText.includes('Ann')`);
  const w = await api('POST', 'approvals', { title: 'Withdraw me', approver: 'bob', amount: '25' });
  check('requester files another request', w.status === 200, JSON.stringify(w));
  await goto('#/approvals');
  await ev(`render(active)`);   // the request was filed behind the page's back (API), so redraw it
  const cardJs = `[...document.querySelectorAll('.card')].find(c => c.innerText.includes('Withdraw me'))`;
  check('requester sees a Withdraw button on their pending request', await ev(`!!${cardJs}?.querySelector('[data-act=withdraw]')`));
  await ev(`${cardJs}.querySelector('[data-act=withdraw]').click()`); await waitFor(`!!document.querySelector('#wr')`);
  await setVal('#wr', 'filed by mistake'); await submitDrawer();
  check('withdrawing works and says so', !!(await waitFor(`document.querySelector('#message')?.innerText.includes('Request withdrawn')`)));
  check('it moves to the Withdrawn column (history kept)', !!(await waitFor(`document.querySelector('.col[data-s=withdrawn]')?.innerText.includes('Withdraw me')`)));
  check('a withdrawn request offers Resubmit, not Withdraw', await ev(`(() => { const c = ${cardJs}; return !!c.querySelector('[data-act=resubmit]') && !c.querySelector('[data-act=withdraw]'); })()`));
  await ev(`${cardJs}.querySelector('[data-act=resubmit]').click()`); await waitFor(`!!document.querySelector('#f_title')`);
  check('resubmission form is pre-filled with the original', (await ev(`document.querySelector('#f_title').value`)) === 'Withdraw me' && (await ev(`document.querySelector('#f_approver').value`)) === 'bob');
  await submitDrawer();
  check('resubmitting creates a new pending request linked to the old one', !!(await waitFor(`(() => { const p = document.querySelector('.col[data-s=pending]')?.innerText.toLowerCase() || ''; return p.includes('withdraw me') && p.includes('resubmission of #'); })()`)));
  await shot('resubmitted');

  // ---- viewer is read-only
  await signOut(); await signIn('vic'); await waitFor(`document.querySelector('#userchip').innerText.includes('Vic')`);
  await goto('#/tasks');
  check('viewer cannot create, edit or delete', !(await ev(`!!document.querySelector('[data-act=new],[data-act=edit],[data-act=del]')`)));
  check('viewer cannot drag cards', !(await ev(`!!document.querySelector('.card[draggable=true]')`)));
  const blocked = await api('POST', 'tasks', { title: 'sneaky' });
  check('server rejects a viewer write (403)', blocked.status === 403, JSON.stringify(blocked));
  await goto('#/reports');
  check('viewer sees no backup or restore controls', !(await ev(`/Restore|full backup/.test(document.body.innerText)`)));

  // ---- bad login
  await signOut();
  await signIn('olive', 'definitely-wrong-password');
  check('wrong password shows an error and stays on login', !!(await waitFor(`!document.querySelector('#lerr').classList.contains('hidden')`)) && !!(await ev(`!!document.querySelector('#loginForm')`)));
  await shot('login-error');
  await signIn('olive'); await waitFor(`document.querySelector('#userchip').innerText.includes('Olive')`);
  await goto('#/audit');
  const audited = await waitFor(`document.querySelector('#content').innerText.includes('by ann') && document.querySelector('#content').innerText.includes('by bob')`);
  check('audit trail records who did what', !!audited, (await text('#content')).slice(0, 200));
  // ---- bulk actions
  for (const t of ['Bulk A', 'Bulk B', 'Bulk C']) await api('POST', 'tasks', { title: t });
  await goto('#/tasks'); await click('#pageactions [data-act=selectmode]');
  await waitFor(`document.querySelectorAll('.pickbox').length >= 3`);
  await ev(`[...document.querySelectorAll('.card')].filter(c => /Bulk [AB]/.test(c.innerText)).forEach(c => c.querySelector('.pickbox').click())`);
  check('bulk bar counts the selection', (await text('#bulkbar')).includes('2 selected'), await text('#bulkbar'));
  await shot('bulkbar');
  await ev(`document.querySelector('#bulkstatus').value = 'done'`); await click('[data-act=bulkstatus]');
  check('bulk status change moves exactly the selected cards', !!(await waitFor(`(() => { const d = document.querySelector('.col[data-s=done]')?.innerText || ''; return d.includes('Bulk A') && d.includes('Bulk B') && !d.includes('Bulk C'); })()`)));
  await click('#pageactions [data-act=selectmode]'); await waitFor(`document.querySelectorAll('.pickbox').length >= 1`);
  await ev(`window.confirm = () => true; [...document.querySelectorAll('.card')].find(c => c.innerText.includes('Bulk C')).querySelector('.pickbox').click()`);
  await click('[data-act=bulkdelete]');
  check('bulk delete removes the selected card only', !!(await waitFor(`!document.body.innerText.includes('Bulk C') && document.body.innerText.includes('Bulk A')`)));

  // ---- self-service: change your own password
  await click('#userchip'); await waitFor(`!!document.querySelector('[data-act=changepw]')`);
  await click('[data-act=changepw]'); await waitFor(`!!document.querySelector('#f_current')`);
  await setVal('#f_current', PW); await setVal('#f_new', 'a-completely-new-passphrase'); await setVal('#f_confirm', 'a-completely-new-passphrase'); await submitDrawer();
  check('user can change their own password', !!(await waitFor(`document.querySelector('#message')?.innerText.includes('Password updated')`)));
  await signOut(); await signIn('olive', 'a-completely-new-passphrase');
  check('the new password signs in', !!(await waitFor(`document.querySelector('#userchip')?.innerText.includes('Olive')`)));

  // ---- responsive layout: realistic, awkward content at phone, tablet and desktop sizes
  const seed = [
    ['quotations', { rfq: 'RFQ-LONG-REFERENCE-0001', supplier: 'A Very Long Supplier Name Incorporated International', item: 'Heavy duty industrial pallet wrap with an extended description', quantity: 200, unit_price: '3.9', currency: 'USD', lead_days: 9, terms: 'Net 30, FOB destination, 2% early payment discount, subject to quality inspection on arrival' }],
    ['quotations', { rfq: 'RFQ-LONG-REFERENCE-0001', supplier: 'Second Supplier', item: 'Heavy duty industrial pallet wrap with an extended description', quantity: 200, unit_price: '4.4', currency: 'USD', lead_days: 4 }],
    ['contracts', { contract: 'Master services agreement with an unusually long counterparty name', counterparty: 'International Logistics and Freight Holdings Limited', obligation: 'Annual rate review and renegotiation of fuel surcharge', owner: 'Olive', due_date: '2026-12-01' }],
    ['tariffs', { service: 'STORAGE-PALLET-LONG-CODE', rate: '120', currency: 'USD' }],
    ['transactions', { ref: 'INV-2026-000001', service: 'STORAGE-PALLET-LONG-CODE', customer: 'Acme Corporation', billed: '90', currency: 'USD' }],
    ['recurring_tasks', { title: 'Weekly review of open purchase orders and supplier confirmations', frequency: 'weekly', next_due: '2026-12-01' }],
    ['tasks', { title: 'A very long task title that should wrap neatly on small screens without breaking the layout', department: 'Procurement and Supply Chain', owner: 'Olive Owner', due_date: '2026-11-01', priority: 'high' }],
  ];
  for (const [t, body] of seed) { const r = await api('POST', t, body); if (r.status !== 200) check(`seed ${t}`, false, JSON.stringify(r)); }
  await api('POST', 'scan', {});
  const setSize = (w, h) => send('Emulation.setDeviceMetricsOverride', { width: w, height: h, deviceScaleFactor: 2, mobile: w < 800 });
  const PAGES = ['dashboard', 'today', 'insights', 'tasks', 'recurring_tasks', 'approvals', 'contracts', 'quotations', 'tariffs', 'transactions', 'automation', 'exceptions', 'reports', 'audit', 'ai', 'imports', 'users'];
  const overflowProbe = `(() => {
    const w = document.documentElement.clientWidth;
    const scroller = '.tw,.board,.chips,.subnav,.groups,.plist,pre,.tabbar';
    const bad = [...document.querySelectorAll('body *')].filter(e => {
      const r = e.getBoundingClientRect();
      if (!r.width || getComputedStyle(e).position === 'fixed' && e.closest('.back,.pal')) return false;
      if (e.closest(scroller) && !e.matches(scroller)) return false;
      return r.right > w + 1 || r.left < -1;
    }).slice(0, 3).map(e => e.tagName.toLowerCase() + '.' + String(e.className).split(' ')[0] + '@' + Math.round(e.getBoundingClientRect().right));
    return { scroll: document.documentElement.scrollWidth, w, bad };
  })()`;
  const smallTargets = `[...document.querySelectorAll('.btn,.ib,.userchip,.tabbar button,.subnav button,.seg button,.chips button,select.status,.ln')]
    .filter(e => e.getClientRects().length).map(e => ({ c: String(e.className).split(' ')[0] || e.tagName, h: Math.round(e.getBoundingClientRect().height), t: (e.innerText || '').trim().slice(0, 14) }))
    .filter(o => o.h < (o.c === 'ln' ? 32 : 36)).slice(0, 3)`;
  for (const [w, h] of [[360, 740], [390, 844], [768, 1024], [1024, 768], [1440, 900]]) {
    await setSize(w, h);
    const problems = [], tiny = [];
    for (const p of PAGES) {
      await goto('#/' + p); await sleep(350);
      const o = await ev(overflowProbe);
      if (o.scroll > o.w + 1 || o.bad.length) problems.push(`${p}: scroll ${o.scroll}>${o.w} ${o.bad.join(',')}`);
      if (w <= 760) { const t = await ev(smallTargets); if (t.length) tiny.push(`${p}: ${t.map(x => `${x.c}(${x.t})=${x.h}px`).join(', ')}`); }
      if (SHOTS && [360, 768].includes(w) && ['dashboard', 'tasks', 'approvals', 'quotations', 'reports'].includes(p)) await shot(`r${w}-${p}`);
    }
    check(`${w}px: no page scrolls sideways`, problems.length === 0, problems.slice(0, 4).join(' | '));
    if (w <= 760) check(`${w}px: tap targets are at least 36px`, tiny.length === 0, tiny.slice(0, 3).join(' | '));
    const tab = await ev(`getComputedStyle(document.querySelector('#tabbar')).display + '/' + getComputedStyle(document.querySelector('#groups')).display`);
    check(`${w}px: ${w <= 760 ? 'bottom tab bar replaces top groups' : 'top groups shown, no tab bar'}`, w <= 760 ? tab.startsWith('grid/none') : tab.startsWith('none/'), tab);
  }
  await setSize(390, 844);
  await goto('#/tasks'); await click('[data-act=new]'); await waitFor(`!!document.querySelector('#f_title')`); await sleep(300);
  check('phone: form fields use 16px text (prevents iOS zoom)', await ev(`parseFloat(getComputedStyle(document.querySelector('#f_title')).fontSize) >= 16`));
  check('phone: drawer fits the screen and has no sideways scroll', await ev(`document.querySelector('.drawer').getBoundingClientRect().width <= innerWidth && document.documentElement.scrollWidth <= innerWidth + 1`));
  await shot('r390-drawer');
  await ev(`document.querySelector('[data-act=close]').click()`);
  await click('#palette'); await waitFor(`!!document.querySelector('#pq')`);
  check('phone: palette fits the screen', await ev(`document.querySelector('.pbox').getBoundingClientRect().width <= innerWidth`));
  await shot('r390-palette');
  await ev(`document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape'}))`);
  await signOut();
  check('phone: login screen fits without scrolling sideways', await ev(`document.querySelector('.authcard').getBoundingClientRect().width <= innerWidth && document.documentElement.scrollWidth <= innerWidth + 1`));
  await shot('r390-login');
  await setSize(1440, 900);
  check('no JavaScript errors during the whole run', errors.length === 0, errors.slice(0, 3).join(' | '));
} catch (e) {
  check('test run completed without crashing', false, e.stack || String(e));
  try {
    const state = await ev(`[location.hash, document.querySelector('#userchip')?.innerText, 'toast: ' + document.querySelector('#message')?.innerText, (document.querySelector('#content')?.innerText || '').slice(0, 700)].join('\n')`);
    console.log('--- page state at failure ---\n' + state);
    await shot('failure');
  } catch { /* best effort */ }
} finally {
  ws.close(); cleanup();
  const failed = results.filter(r => !r).length;
  console.log(`\n${results.length - failed}/${results.length} checks passed`);
  process.exit(failed ? 1 : 0);
}
