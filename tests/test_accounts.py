"""Accounts, roles and multi-stage approvals.  Run: python -m unittest discover -s tests -v"""
import http.client
import json
import sqlite3
import threading
import unittest
from http.server import ThreadingHTTPServer

from test_app import AppTestCase

PW = 'correct-horse-battery'


class UserTests(AppTestCase):
    def make(self, username, role='member', name=None):
        return self.app.create_user({'username': username, 'display_name': name or username.title(), 'role': role, 'password': PW})

    def test_password_hashing(self):
        h = self.app.hash_password(PW)
        self.assertNotIn(PW, h)
        self.assertTrue(self.app.verify_password(PW, h))
        self.assertFalse(self.app.verify_password('wrong-password!', h))
        self.assertNotEqual(h, self.app.hash_password(PW))  # unique salt
        self.assertFalse(self.app.verify_password(PW, 'garbage'))

    def test_create_validation(self):
        for bad in ({'username': 'ab', 'password': PW}, {'username': 'has space', 'password': PW}, {'username': 'okname', 'password': 'short'}, {'username': 'okname', 'password': PW, 'role': 'root'}):
            with self.assertRaises(ValueError):
                self.app.create_user(bad)
        self.make('ann')
        with self.assertRaises(ValueError):
            self.make('ANN')  # usernames are case-insensitive unique

    def test_bootstrap_only_once_and_forces_admin(self):
        u = self.app.create_user({'username': 'owner', 'password': PW, 'role': 'viewer'}, bootstrap=True)
        self.assertEqual(u['role'], 'admin')
        with self.assertRaises(ValueError):
            self.app.create_user({'username': 'second', 'password': PW}, bootstrap=True)

    def test_login_and_sessions(self):
        u = self.make('ann')
        self.assertEqual(self.app.authenticate('ANN', PW)['id'], u['id'])
        token = self.app.start_session(u['id'])
        self.assertEqual(self.app.session_user(token)['username'], 'ann')
        self.assertIsNone(self.app.session_user('not-a-token'))
        self.app.end_session(token)
        self.assertIsNone(self.app.session_user(token))

    def test_bad_credentials_and_throttle(self):
        self.make('ann')
        for _ in range(5):
            with self.assertRaises(ValueError) as ctx:
                self.app.authenticate('ann', 'nope-nope-nope', '1.2.3.4')
            self.assertEqual(str(ctx.exception), 'Invalid username or password')
        with self.assertRaises(ValueError) as ctx:
            self.app.authenticate('ann', PW, '1.2.3.4')  # even the right password is refused while locked
        self.assertIn('Too many', str(ctx.exception))
        self.assertEqual(self.app.authenticate('ann', PW, '9.9.9.9')['username'], 'ann')  # other client unaffected

    def test_unknown_user_same_error(self):
        with self.assertRaises(ValueError) as ctx:
            self.app.authenticate('ghost', PW)
        self.assertEqual(str(ctx.exception), 'Invalid username or password')

    def test_deactivation_ends_sessions(self):
        u = self.make('ann')
        token = self.app.start_session(u['id'])
        self.make('boss', 'admin')
        self.app.update_user(u['id'], {'active': False})
        self.assertIsNone(self.app.session_user(token))
        with self.assertRaises(ValueError):
            self.app.authenticate('ann', PW)

    def test_password_reset_ends_sessions(self):
        u = self.make('ann')
        token = self.app.start_session(u['id'])
        self.app.update_user(u['id'], {'password': 'a-brand-new-passphrase'})
        self.assertIsNone(self.app.session_user(token))
        self.assertEqual(self.app.authenticate('ann', 'a-brand-new-passphrase')['username'], 'ann')

    def test_last_admin_protected(self):
        admin = self.make('boss', 'admin')
        with self.assertRaises(ValueError):
            self.app.update_user(admin['id'], {'role': 'member'})
        with self.assertRaises(ValueError):
            self.app.update_user(admin['id'], {'active': False})
        other = self.make('deputy', 'admin')
        self.app.update_user(admin['id'], {'role': 'member'})  # fine once another admin exists
        with self.assertRaises(ValueError):
            self.app.update_user(other['id'], {'active': False})

    def test_audit_never_stores_passwords(self):
        self.make('ann')
        u = self.app.list_users()[0]
        self.app.update_user(u['id'], {'password': 'another-long-passphrase'})
        blob = json.dumps(self.app.read_table('audit'))
        self.assertNotIn('passphrase', blob)
        self.assertNotIn(PW, blob)
        self.assertNotIn('scrypt', blob)

    def test_users_excluded_from_backups(self):
        self.make('ann')
        blob = json.dumps(self.app.backup_export())
        self.assertNotIn('scrypt', blob)
        self.assertNotIn('password_hash', blob)

    def test_role_matrix(self):
        user = lambda role: {'role': role}
        allowed = [
            ('viewer', 'GET', '/api/tasks'), ('member', 'POST', '/api/tasks'), ('member', 'PUT', '/api/tasks/1'),
            ('manager', 'DELETE', '/api/tasks/1'), ('admin', 'GET', '/api/users'), ('admin', 'POST', '/api/restore'),
            ('member', 'POST', '/api/approvals/decision'), ('admin', 'GET', '/api/backup'),
        ]
        denied = [
            ('viewer', 'POST', '/api/tasks'), ('viewer', 'POST', '/api/scan'), ('member', 'DELETE', '/api/tasks/1'),
            ('member', 'GET', '/api/users'), ('manager', 'POST', '/api/users'), ('manager', 'POST', '/api/restore'),
            ('member', 'POST', '/api/automation/settings'), ('manager', 'GET', '/api/backup'), ('viewer', 'POST', '/api/import'),
        ]
        for role, method, path in allowed:
            self.app.check_access(method, path, user(role))
        for role, method, path in denied:
            with self.assertRaises(self.app.Forbidden, msg=f'{role} {method} {path}'):
                self.app.check_access(method, path, user(role))

    def test_anonymous_access_rules(self):
        for method, path in (('GET', '/api/tasks'), ('POST', '/api/tasks'), ('GET', '/api/users'), ('GET', '/api/backup')):
            with self.assertRaises(self.app.AuthError):
                self.app.check_access(method, path, None)
        for method, path in (('GET', '/api/health'), ('GET', '/api/auth/me'), ('POST', '/api/auth/login'), ('GET', '/'), ('GET', '/app.js')):
            self.app.check_access(method, path, None)


class MultiStageApprovalTests(AppTestCase):
    def req(self, **over):
        row = {'title': 'Forklift', 'requester': 'Ann', 'approver': 'Bob', 'second_approver': 'Cyd', 'amount': '500'}
        row.update(over)
        return self.app.add_row('approvals', row)['id']

    def acct(self, username, role='member'):
        self.app.create_user({'username': username, 'display_name': username.title(), 'role': role, 'password': PW})
        return next(u for u in self.app.list_users() if u['username'] == username)

    def test_two_stages_must_both_approve(self):
        i = self.req()
        r = self.app.decide_approval(i, 'approved', 'ok')
        self.assertEqual((r['status'], r['stage'], r['stages']), ('pending', 1, 2))
        self.assertEqual(self.app.read_table('approvals')[0]['status'], 'pending')
        r = self.app.decide_approval(i, 'approved')
        self.assertEqual(r['status'], 'approved')
        self.assertEqual([s['status'] for s in self.app.approvals_list()[0]['steps']], ['approved', 'approved'])

    def test_rejection_ends_request_and_skips_rest(self):
        i = self.req()
        self.assertEqual(self.app.decide_approval(i, 'rejected', 'no')['status'], 'rejected')
        self.assertEqual([s['status'] for s in self.app.approvals_list()[0]['steps']], ['rejected', 'skipped'])
        with self.assertRaises(ValueError):
            self.app.decide_approval(i, 'approved')

    def test_second_stage_rejection(self):
        i = self.req()
        self.app.decide_approval(i, 'approved')
        self.assertEqual(self.app.decide_approval(i, 'rejected')['status'], 'rejected')

    def test_progress_and_awaiting(self):
        i = self.req()
        self.app.decide_approval(i, 'approved')
        row = self.app.approvals_list()[0]
        self.assertEqual((row['progress'], row['awaiting']), ('1/2 approved', 'Cyd'))

    def test_distinct_people_required(self):
        with self.assertRaises(ValueError):
            self.req(second_approver='bob')
        with self.assertRaises(ValueError):
            self.req(second_approver='ANN')

    def test_threshold_requires_second_approver(self):
        self.app.save_automation_settings({'second_approval_threshold': 1000})
        self.assertEqual(self.app.automation_settings()['second_approval_threshold'], 1000)
        with self.assertRaises(ValueError) as ctx:
            self.req(second_approver='', amount='1,000')
        self.assertIn('second approver', str(ctx.exception))
        self.req(second_approver='', amount='999.99')       # below the limit
        self.req(second_approver='Cyd', amount='5000')       # above, but has a second approver

    def test_threshold_enforced_on_edit(self):
        self.app.save_automation_settings({'second_approval_threshold': 1000})
        i = self.req(second_approver='', amount='10')
        with self.assertRaises(ValueError):
            self.app.update_row('approvals', i, {'amount': '2000'})
        self.app.update_row('approvals', i, {'amount': '2000', 'second_approver': 'Cyd'})
        self.assertEqual(len(self.app.approvals_list()[0]['steps']), 2)

    def test_editing_approvers_rebuilds_steps_until_decided(self):
        i = self.req(second_approver='')
        self.app.update_row('approvals', i, {'approver': 'Dee', 'second_approver': 'Eve'})
        self.assertEqual([s['approver'] for s in self.app.approvals_list()[0]['steps']], ['Dee', 'Eve'])
        self.app.decide_approval(i, 'approved')
        with self.assertRaises(ValueError):
            self.app.update_row('approvals', i, {'approver': 'Zed'})

    def test_delete_removes_steps(self):
        i = self.req()
        self.app.delete_row('approvals', i)
        with sqlite3.connect(self.app.DB) as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM approval_steps').fetchone()[0], 0)

    def test_only_assigned_approver_can_decide_when_accounts_exist(self):
        ann, bob, cy, dan = self.acct('ann'), self.acct('bob'), self.acct('cyd'), self.acct('dan')
        i = self.req()
        with self.assertRaises(self.app.Forbidden):
            self.app.decide_approval(i, 'approved', '', dan)             # not assigned
        with self.assertRaises(self.app.Forbidden):
            self.app.decide_approval(i, 'approved', '', cy)              # assigned to step 2, not step 1
        self.assertEqual(self.app.decide_approval(i, 'approved', '', bob)['status'], 'pending')
        with self.assertRaises(self.app.Forbidden):
            self.app.decide_approval(i, 'approved', '', bob)             # bob cannot also do step 2
        self.assertEqual(self.app.decide_approval(i, 'approved', '', cy)['status'], 'approved')
        self.assertEqual(self.app.approvals_list()[0]['steps'][0]['decided_by'], 'Bob')

    def test_cannot_decide_own_request_even_as_admin(self):
        admin = self.acct('ann', 'admin')
        i = self.req(requester='Ann', approver='Bob')
        with self.assertRaises(self.app.Forbidden):
            self.app.decide_approval(i, 'approved', '', admin)

    def test_admin_can_override_assignment(self):
        admin = self.acct('boss', 'admin')
        i = self.req()
        self.assertEqual(self.app.decide_approval(i, 'approved', '', admin)['stage'], 1)
        with self.assertRaises(self.app.Forbidden):  # but not both steps
            self.app.decide_approval(i, 'approved', '', admin)

    def test_matching_works_on_display_name_too(self):
        self.app.create_user({'username': 'rjones', 'display_name': 'Robert Jones', 'role': 'member', 'password': PW})
        rj = next(u for u in self.app.list_users() if u['username'] == 'rjones')
        i = self.req(approver='Robert Jones', second_approver='')
        self.assertTrue(next(a for a in self.app.approvals_list(rj) if a['id'] == i)['can_decide'])

    def test_can_decide_flag(self):
        bob, cy = self.acct('bob'), self.acct('cyd')
        self.req()
        self.assertTrue(self.app.approvals_list(bob)[0]['can_decide'])
        self.assertFalse(self.app.approvals_list(cy)[0]['can_decide'])   # step 2 is not active yet
        self.assertTrue(self.app.approvals_list(None)[0]['can_decide'])  # open (single-user) mode

    def test_restore_does_not_leave_orphan_steps(self):
        self.req()
        backup = self.app.backup_export()
        backup['data'].pop('approval_steps')       # an older backup format
        self.app.restore_backup(backup)
        with sqlite3.connect(self.app.DB) as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM approval_steps').fetchone()[0], 0)
        i = self.app.read_table('approvals')[0]['id']
        self.assertEqual(self.app.decide_approval(i, 'approved')['status'], 'pending')  # steps rebuilt on demand

    def test_full_backup_round_trip_keeps_progress(self):
        i = self.req()
        self.app.decide_approval(i, 'approved')
        backup = self.app.backup_export()
        self.app.delete_row('approvals', i)
        self.app.restore_backup(backup)
        self.assertEqual(self.app.approvals_list()[0]['progress'], '1/2 approved')


class MigrationTests(AppTestCase):
    def test_old_database_is_upgraded(self):
        import os
        import importlib
        import sys
        old = os.path.join(self.tmp.name, 'old.sqlite3')
        with sqlite3.connect(old) as c:
            c.executescript("""
                CREATE TABLE audit(id INTEGER PRIMARY KEY AUTOINCREMENT,action TEXT NOT NULL,entity TEXT NOT NULL,details TEXT NOT NULL,at TEXT NOT NULL);
                CREATE TABLE approvals(id INTEGER PRIMARY KEY AUTOINCREMENT,title TEXT NOT NULL,category TEXT NOT NULL DEFAULT 'Operational',requester TEXT DEFAULT '',approver TEXT DEFAULT '',amount TEXT DEFAULT '0',currency TEXT NOT NULL DEFAULT 'USD',rationale TEXT DEFAULT '',status TEXT NOT NULL DEFAULT 'pending',decision_comment TEXT DEFAULT '',created_at TEXT NOT NULL,decided_at TEXT DEFAULT '');
                INSERT INTO approvals(title,requester,approver,created_at) VALUES('Legacy','Ann','Bob','2026-01-01');
                INSERT INTO audit(action,entity,details,at) VALUES('create','tasks','{}','2026-01-01');
            """)
        os.environ['AUTOMATION_DB'] = old
        sys.modules.pop('app', None)
        app = importlib.import_module('app')
        app.init()
        app.init()  # idempotent
        row = app.approvals_list()[0]
        self.assertEqual((row['title'], row['awaiting'], row['second_approver']), ('Legacy', 'Bob', ''))
        self.assertEqual(app.read_table('audit')[0]['actor'], '')
        self.assertEqual(app.decide_approval(row['id'], 'approved')['status'], 'approved')


class HttpAccountTests(AppTestCase):
    def setUp(self):
        super().setUp()
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), self.app.Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        super().tearDown()

    def call(self, method, path, body=None, cookie=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)
        h = {'Host': f'127.0.0.1:{self.port}', 'Content-Type': 'application/json'}
        if cookie:
            h['Cookie'] = cookie
        conn.request(method, path, body=json.dumps(body) if body is not None else None, headers=h)
        r = conn.getresponse()
        raw = r.read()
        set_cookie = r.getheader('Set-Cookie')
        conn.close()
        try:
            data = json.loads(raw)
        except ValueError:
            data = raw
        return r.status, data, set_cookie

    def login(self, username, password=PW):
        status, data, cookie = self.call('POST', '/api/auth/login', {'username': username, 'password': password})
        self.assertEqual(status, 200, data)
        return cookie.split(';')[0]

    def test_open_mode_then_setup_then_login_required(self):
        status, data, _ = self.call('GET', '/api/auth/me')
        self.assertEqual((status, data['accounts']), (200, False))
        self.assertEqual(self.call('POST', '/api/tasks', {'title': 'open mode works'})[0], 200)
        status, data, cookie = self.call('POST', '/api/auth/setup', {'username': 'owner', 'display_name': 'Olive Owner', 'password': PW})
        self.assertEqual((status, data['user']['role']), (200, 'admin'))
        self.assertIn('HttpOnly', cookie)
        self.assertIn('SameSite=Strict', cookie)
        status, data, _ = self.call('POST', '/api/auth/setup', {'username': 'other', 'password': PW})
        self.assertEqual((status, data['error']), (400, 'Accounts are already set up'))  # setup is one-time
        status, data, _ = self.call('GET', '/api/tasks')
        self.assertEqual((status, data.get('login')), (401, True))
        self.assertEqual(self.call('GET', '/api/health')[0], 200)
        self.assertEqual(self.call('GET', '/')[0], 200)

    def test_role_enforcement_over_http(self):
        self.call('POST', '/api/auth/setup', {'username': 'owner', 'password': PW})
        admin = self.login('owner')
        for name, role in (('viewer1', 'viewer'), ('member1', 'member'), ('manager1', 'manager')):
            self.assertEqual(self.call('POST', '/api/users', {'username': name, 'role': role, 'password': PW}, admin)[0], 200)
        viewer, member, manager = self.login('viewer1'), self.login('member1'), self.login('manager1')
        self.assertEqual(self.call('GET', '/api/tasks', cookie=viewer)[0], 200)
        self.assertEqual(self.call('POST', '/api/tasks', {'title': 'x'}, viewer)[0], 403)
        self.assertEqual(self.call('POST', '/api/tasks', {'title': 'x'}, member)[0], 200)
        self.assertEqual(self.call('DELETE', '/api/tasks/1', cookie=member)[0], 403)
        self.assertEqual(self.call('DELETE', '/api/tasks/1', cookie=manager)[0], 200)
        self.assertEqual(self.call('GET', '/api/users', cookie=manager)[0], 403)
        self.assertEqual(self.call('GET', '/api/backup', cookie=manager)[0], 403)
        self.assertEqual(self.call('POST', '/api/restore', {'format': 'x'}, manager)[0], 403)
        self.assertEqual(self.call('POST', '/api/automation/settings', {'due_days': 3}, member)[0], 403)
        self.assertEqual(self.call('GET', '/api/users', cookie=admin)[0], 200)
        self.assertEqual(self.call('GET', '/api/backup', cookie=admin)[0], 200)

    def test_audit_records_the_actor(self):
        self.call('POST', '/api/auth/setup', {'username': 'owner', 'password': PW})
        admin = self.login('owner')
        self.call('POST', '/api/tasks', {'title': 'audited'}, admin)
        actors = {(a['action'], a['actor']) for a in self.app.read_table('audit')}
        self.assertIn(('create', 'owner'), actors)
        self.assertIn(('login', 'owner'), actors)

    def test_logout_invalidates_cookie(self):
        self.call('POST', '/api/auth/setup', {'username': 'owner', 'password': PW})
        cookie = self.login('owner')
        self.assertEqual(self.call('GET', '/api/tasks', cookie=cookie)[0], 200)
        status, _, cleared = self.call('POST', '/api/auth/logout', {}, cookie)
        self.assertEqual(status, 200)
        self.assertIn('Max-Age=0', cleared)
        self.assertEqual(self.call('GET', '/api/tasks', cookie=cookie)[0], 401)

    def test_approval_flow_over_http(self):
        self.call('POST', '/api/auth/setup', {'username': 'owner', 'password': PW})
        admin = self.login('owner')
        for n in ('ann', 'bob', 'cyd'):
            self.call('POST', '/api/users', {'username': n, 'display_name': n.title(), 'role': 'member', 'password': PW}, admin)
        ann, bob, cy = self.login('ann'), self.login('bob'), self.login('cyd')
        status, data, _ = self.call('POST', '/api/approvals', {'title': 'Crane', 'requester': 'Ann', 'approver': 'Bob', 'second_approver': 'Cyd', 'amount': '9000'}, ann)
        self.assertEqual(status, 200, data)
        rid = data['id']
        decide = lambda cookie, d='approved': self.call('POST', '/api/approvals/decision', {'id': rid, 'decision': d}, cookie)
        self.assertEqual(decide(ann)[0], 403)                      # requester
        self.assertEqual(decide(cy)[0], 403)                       # not their turn
        self.assertEqual(decide(bob)[1]['status'], 'pending')
        listing = self.call('GET', '/api/approvals', cookie=cy)[1]
        self.assertTrue(listing[0]['can_decide'])
        self.assertFalse(self.call('GET', '/api/approvals', cookie=bob)[1][0]['can_decide'])
        self.assertEqual(decide(cy)[1]['status'], 'approved')

    def test_login_failure_is_a_400_not_a_login_redirect(self):
        self.call('POST', '/api/auth/setup', {'username': 'owner', 'password': PW})
        status, data, _ = self.call('POST', '/api/auth/login', {'username': 'owner', 'password': 'wrong-password'})
        self.assertEqual(status, 400)
        self.assertNotIn('login', data)


if __name__ == '__main__':
    unittest.main()
