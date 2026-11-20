"""Withdrawing a pending approval request, and resubmitting a rejected or withdrawn one."""
import http.client
import json
import sqlite3
import threading
import unittest
from http.server import ThreadingHTTPServer

from test_app import AppTestCase, load_app

PW = 'correct-horse-battery'


class WithdrawMixin:
    def user(self, username, role='member'):
        self.app.create_user({'username': username, 'display_name': username.title(), 'role': role, 'password': PW})
        return next(u for u in self.app.list_users() if u['username'] == username)

    def file(self, who, approver='bob', second='', **extra):
        payload = {'title': 'Crane', 'approver': approver, 'second_approver': second, **extra}
        return self.app.add_row('approvals', self.app.prepare_approval_payload(payload, who))['id']


class WithdrawTests(WithdrawMixin, AppTestCase):
    def setUp(self):
        super().setUp()
        self.ann, self.bob, self.cyd = self.user('ann'), self.user('bob'), self.user('cyd')
        self.boss = self.user('boss', 'admin')

    def row(self):
        return self.app.approvals_list(self.boss)[0]

    def test_requester_can_withdraw_and_history_is_kept(self):
        rid = self.file(self.ann, second='cyd')
        self.assertEqual(self.app.withdraw_approval(rid, self.ann, 'plans changed')['status'], 'withdrawn')
        row = self.row()
        self.assertEqual((row['status'], row['decision_comment'], row['can_decide']), ('withdrawn', 'plans changed', False))
        self.assertEqual([s['status'] for s in row['steps']], ['skipped', 'skipped'])
        self.assertEqual(len(self.app.read_table('approvals')), 1)      # still on file, unlike a delete

    def test_nobody_can_decide_a_withdrawn_request(self):
        rid = self.file(self.ann)
        self.app.withdraw_approval(rid, self.ann)
        with self.assertRaises(ValueError):
            self.app.decide_approval(rid, 'approved', '', self.bob)

    def test_only_the_requester_or_an_admin_can_withdraw(self):
        rid = self.file(self.ann)
        for stranger in (self.bob, self.cyd):
            with self.assertRaises(self.app.Forbidden):
                self.app.withdraw_approval(rid, stranger)
        self.assertEqual(self.row()['status'], 'pending')
        self.assertEqual(self.app.withdraw_approval(rid, self.boss)['status'], 'withdrawn')

    def test_only_pending_requests_can_be_withdrawn(self):
        rid = self.file(self.ann)
        self.app.decide_approval(rid, 'approved', '', self.bob)
        with self.assertRaises(ValueError):
            self.app.withdraw_approval(rid, self.ann)
        other = self.file(self.ann)
        self.app.withdraw_approval(other, self.ann)
        with self.assertRaises(ValueError):
            self.app.withdraw_approval(other, self.ann)                  # not twice

    def test_partial_approval_is_preserved_when_withdrawn(self):
        rid = self.file(self.ann, second='cyd')
        self.app.decide_approval(rid, 'approved', 'fine', self.bob)
        self.app.withdraw_approval(rid, self.ann)
        self.assertEqual([s['status'] for s in self.row()['steps']], ['approved', 'skipped'])

    def test_unknown_request_and_long_reason(self):
        with self.assertRaises(ValueError):
            self.app.withdraw_approval(999, self.ann)
        rid = self.file(self.ann)
        with self.assertRaises(ValueError):
            self.app.withdraw_approval(rid, self.ann, 'x' * 2001)

    def test_single_user_mode_allows_it(self):
        rid = self.app.add_row('approvals', {'title': 'T', 'requester': 'A', 'approver': 'B'})['id']
        self.assertEqual(self.app.withdraw_approval(rid)['status'], 'withdrawn')

    def test_it_disappears_from_the_approvers_notifications_and_counts(self):
        rid = self.file(self.ann)
        self.assertEqual(len(self.app.notifications(self.bob)), 1)
        self.app.withdraw_approval(rid, self.ann)
        self.assertEqual(self.app.notifications(self.bob), [])
        self.assertEqual(self.app.notifications(self.ann), [])          # no "was withdrawn" outcome for your own action
        self.assertEqual(self.app.overview()['pending_approvals'], 0)

    def test_audit_trail(self):
        rid = self.file(self.ann)
        self.app.withdraw_approval(rid, self.ann, 'dup')
        entry = next(e for e in self.app.read_table('audit') if e['action'] == 'approval_withdrawn')
        self.assertEqual(json.loads(entry['details'])['reason'], 'dup')

    def test_survives_a_backup_round_trip(self):
        rid = self.file(self.ann)
        self.app.withdraw_approval(rid, self.ann, 'later')
        backup = self.app.backup_export()
        self.app.delete_row('approvals', rid)
        self.app.restore_backup(backup)
        self.assertEqual((self.row()['status'], self.row()['decision_comment']), ('withdrawn', 'later'))


class ResubmitTests(WithdrawMixin, AppTestCase):
    def setUp(self):
        super().setUp()
        self.ann, self.bob, self.cyd = self.user('ann'), self.user('bob'), self.user('cyd')

    def test_resubmission_links_to_the_earlier_request(self):
        first = self.file(self.ann)
        self.app.decide_approval(first, 'rejected', 'too expensive', self.bob)
        second = self.file(self.ann, amount='400', previous_id=first)
        rows = {r['id']: r for r in self.app.approvals_list(self.ann)}
        self.assertEqual((rows[second]['previous_id'], rows[first]['previous_id']), (first, 0))
        self.assertEqual(rows[second]['status'], 'pending')

    def test_withdrawn_requests_can_be_resubmitted_too(self):
        first = self.file(self.ann)
        self.app.withdraw_approval(first, self.ann)
        self.assertEqual(self.app.approvals_list(self.ann)[0]['previous_id'], 0)
        self.assertTrue(self.file(self.ann, previous_id=first))

    def test_only_rejected_or_withdrawn_requests_can_be_resubmitted(self):
        pending = self.file(self.ann)
        with self.assertRaises(ValueError):
            self.file(self.ann, previous_id=pending)
        approved = self.file(self.ann)
        self.app.decide_approval(approved, 'approved', '', self.bob)
        with self.assertRaises(ValueError):
            self.file(self.ann, previous_id=approved)

    def test_bad_links_are_rejected(self):
        for bad in (9999, 'abc', -5):
            with self.assertRaises(ValueError):
                self.file(self.ann, previous_id=bad)
        self.assertEqual(len(self.app.read_table('approvals')), 0)

    def test_empty_link_is_ignored(self):
        for blank in ('', None, 0, '0'):
            self.file(self.ann, previous_id=blank)
        self.assertEqual({r['previous_id'] for r in self.app.read_table('approvals')}, {0})

    def test_you_cannot_resubmit_someone_elses_request(self):
        first = self.file(self.ann)
        self.app.decide_approval(first, 'rejected', '', self.bob)
        with self.assertRaises(self.app.Forbidden):
            self.file(self.cyd, previous_id=first)
        boss = self.user('boss', 'admin')
        self.assertTrue(self.file(boss, previous_id=first))             # an admin may

    def test_old_databases_gain_the_link_column(self):
        import os
        old = os.path.join(self.tmp.name, 'old.sqlite3')
        with sqlite3.connect(old) as c:
            c.executescript("CREATE TABLE approvals(id INTEGER PRIMARY KEY AUTOINCREMENT,title TEXT NOT NULL,category TEXT NOT NULL DEFAULT 'Operational',requester TEXT DEFAULT '',approver TEXT DEFAULT '',amount TEXT DEFAULT '0',currency TEXT NOT NULL DEFAULT 'USD',rationale TEXT DEFAULT '',status TEXT NOT NULL DEFAULT 'pending',decision_comment TEXT DEFAULT '',created_at TEXT NOT NULL,decided_at TEXT DEFAULT '');")
        os.environ['AUTOMATION_DB'] = old
        app = load_app()
        app.init()
        app.init()
        with sqlite3.connect(old) as c:
            self.assertIn('previous_id', [r[1] for r in c.execute('PRAGMA table_info(approvals)')])


class HttpWithdrawTests(WithdrawMixin, AppTestCase):
    def setUp(self):
        super().setUp()
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), self.app.Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.call('POST', '/api/auth/setup', {'username': 'boss', 'password': PW})
        admin = self.login('boss')
        for n in ('ann', 'bob', 'cyd'):
            self.call('POST', '/api/users', {'username': n, 'display_name': n.title(), 'role': 'member', 'password': PW}, admin)
        self.ann, self.bob, self.cyd = self.login('ann'), self.login('bob'), self.login('cyd')

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        super().tearDown()

    def call(self, method, path, body=None, cookie=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)
        headers = {'Host': f'127.0.0.1:{self.port}', 'Content-Type': 'application/json'}
        if cookie:
            headers['Cookie'] = cookie
        conn.request(method, path, body=json.dumps(body) if body is not None else None, headers=headers)
        r = conn.getresponse()
        raw = r.read()
        set_cookie = r.getheader('Set-Cookie')
        conn.close()
        return r.status, json.loads(raw), set_cookie

    def login(self, name):
        status, data, cookie = self.call('POST', '/api/auth/login', {'username': name, 'password': PW})
        self.assertEqual(status, 200, data)
        return cookie.split(';')[0]

    def test_withdraw_and_resubmit_over_http(self):
        rid = self.call('POST', '/api/approvals', {'title': 'Crane', 'approver': 'bob', 'amount': '900'}, self.ann)[1]['id']
        self.assertEqual(self.call('POST', '/api/approvals/withdraw', {'id': rid}, self.cyd)[0], 403)
        self.assertEqual(self.call('POST', '/api/approvals/withdraw', {'id': rid, 'reason': 'oops'}, self.ann)[0], 200)
        self.assertEqual(self.call('POST', '/api/approvals/decision', {'id': rid, 'decision': 'approved'}, self.bob)[0], 400)
        self.assertEqual(self.call('GET', '/api/overview', cookie=self.bob)[1]['awaiting_me'], 0)
        status, data, _ = self.call('POST', '/api/approvals', {'title': 'Crane', 'approver': 'bob', 'amount': '500', 'previous_id': rid}, self.ann)
        self.assertEqual(status, 200, data)
        listing = self.call('GET', '/api/approvals', cookie=self.bob)[1]
        self.assertEqual({(a['status'], a['previous_id']) for a in listing}, {('withdrawn', 0), ('pending', rid)})
        self.assertEqual(self.call('POST', '/api/approvals', {'title': 'x', 'approver': 'bob', 'previous_id': rid}, self.cyd)[0], 403)

    def test_resubmitting_a_pending_request_is_a_400(self):
        rid = self.call('POST', '/api/approvals', {'title': 'Crane', 'approver': 'bob'}, self.ann)[1]['id']
        status, data, _ = self.call('POST', '/api/approvals', {'title': 'Again', 'approver': 'bob', 'previous_id': rid}, self.ann)
        self.assertEqual(status, 400)
        self.assertIn('rejected or withdrawn', data['error'])


if __name__ == '__main__':
    unittest.main()
