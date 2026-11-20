"""Out-of-office cover: handing approvals to a colleague for a limited time."""
import http.client
import importlib
import json
import os
import sqlite3
import sys
import threading
import unittest
from datetime import datetime, timedelta
from http.server import ThreadingHTTPServer

from test_app import AppTestCase

PW = 'correct-horse-battery'
day = lambda n: (datetime.now().date() + timedelta(days=n)).isoformat()


class CoverMixin:
    def user(self, username, role='member'):
        self.app.create_user({'username': username, 'display_name': username.title(), 'role': role, 'password': PW})
        return next(u for u in self.app.list_users() if u['username'] == username)

    def fresh(self, user):
        """Reload a user the way a request would (so cover status is current)."""
        return next(self.app.session_user(self.app.start_session(u['id'])) for u in self.app.list_users() if u['id'] == user['id'])

    def request(self, requester, approver, second=''):
        payload = {'title': 'Crane', 'approver': approver, 'second_approver': second}
        return self.app.add_row('approvals', self.app.prepare_approval_payload(payload, requester))['id']


class DelegationRuleTests(CoverMixin, AppTestCase):
    def setUp(self):
        super().setUp()
        self.ann, self.bob, self.cyd, self.dee = (self.user(n) for n in ('ann', 'bob', 'cyd', 'dee'))
        self.viewer = self.user('vic', 'viewer')

    def away(self, who, to, days=5):
        return self.app.set_delegation(self.fresh(who), to, day(days))

    def test_delegate_can_decide_and_it_is_recorded(self):
        rid = self.request(self.ann, 'bob')
        self.away(self.bob, 'cyd')
        cyd = self.fresh(self.cyd)
        self.assertTrue(self.app.approvals_list(cyd)[0]['can_decide'])
        self.assertEqual(self.app.decide_approval(rid, 'approved', 'on it', cyd)['status'], 'approved')
        step = self.app.approvals_list()[0]['steps'][0]
        self.assertEqual((step['decided_by'], step['acting_for']), ('Cyd', 'bob'))

    def test_without_cover_a_colleague_is_still_blocked(self):
        rid = self.request(self.ann, 'bob')
        with self.assertRaises(self.app.Forbidden):
            self.app.decide_approval(rid, 'approved', '', self.cyd)

    def test_only_the_named_delegate_gets_the_right(self):
        rid = self.request(self.ann, 'bob')
        self.away(self.bob, 'cyd')
        with self.assertRaises(self.app.Forbidden):
            self.app.decide_approval(rid, 'approved', '', self.fresh(self.dee))

    def test_cover_expires(self):
        rid = self.request(self.ann, 'bob')
        self.away(self.bob, 'cyd')
        with sqlite3.connect(self.app.DB) as c:
            c.execute('UPDATE users SET delegate_until=? WHERE username=?', (day(-1), 'bob'))
        cyd = self.fresh(self.cyd)
        self.assertFalse(self.app.approvals_list(cyd)[0]['can_decide'])
        with self.assertRaises(self.app.Forbidden):
            self.app.decide_approval(rid, 'approved', '', cyd)
        self.assertEqual(self.fresh(self.bob)['delegate_to'], '')          # an expired cover is not shown as active

    def test_cover_lasts_through_the_return_date(self):
        rid = self.request(self.ann, 'bob')
        self.app.set_delegation(self.fresh(self.bob), 'cyd', day(0))       # "until today" still counts today
        self.assertEqual(self.app.decide_approval(rid, 'approved', '', self.fresh(self.cyd))['status'], 'approved')

    def test_the_person_away_can_still_decide_themselves(self):
        rid = self.request(self.ann, 'bob')
        self.away(self.bob, 'cyd')
        self.assertEqual(self.app.decide_approval(rid, 'approved', '', self.fresh(self.bob))['status'], 'approved')

    def test_cover_never_lets_someone_decide_their_own_request(self):
        rid = self.request(self.ann, 'bob')
        self.away(self.bob, 'ann')                                          # bob hands his approvals to the requester
        ann = self.fresh(self.ann)
        self.assertFalse(self.app.approvals_list(ann)[0]['can_decide'])
        with self.assertRaises(self.app.Forbidden):
            self.app.decide_approval(rid, 'approved', '', ann)

    def test_one_person_cannot_approve_both_steps_via_cover(self):
        rid = self.request(self.ann, 'bob', 'cyd')
        self.away(self.bob, 'cyd')                                          # cyd covers step 1 and owns step 2
        cyd = self.fresh(self.cyd)
        self.assertEqual(self.app.decide_approval(rid, 'approved', '', cyd)['status'], 'pending')
        with self.assertRaises(self.app.Forbidden):
            self.app.decide_approval(rid, 'approved', '', cyd)

    def test_listing_marks_covering_requests_as_mine(self):
        self.request(self.ann, 'bob')
        self.away(self.bob, 'cyd')
        row = self.app.approvals_list(self.fresh(self.cyd))[0]
        self.assertEqual((row['mine'], row['covering'], row['can_decide']), (True, True, True))
        own = self.app.approvals_list(self.fresh(self.bob))[0]
        self.assertEqual((own['mine'], own['covering']), (True, False))

    def test_admin_override_is_unchanged_and_not_marked_covering(self):
        boss = self.user('boss', 'admin')
        self.request(self.ann, 'bob')
        row = self.app.approvals_list(boss)[0]
        self.assertEqual((row['can_decide'], row['mine'], row['covering']), (True, False, False))

    def test_delegate_is_notified_with_context(self):
        self.request(self.ann, 'bob')
        self.away(self.bob, 'cyd')
        items = self.app.notifications(self.fresh(self.cyd))
        detail = next(n['detail'] for n in items if n['kind'] == 'approval')
        self.assertIn('Covering for Bob', detail)
        self.assertEqual(self.app.automation_settings()['approval_escalate_days'], 3)
        self.assertEqual(self.app.notifications(self.fresh(self.dee)), [])

    def test_awaiting_me_count_follows_the_cover(self):
        self.request(self.ann, 'bob')
        self.away(self.bob, 'cyd')
        self.assertEqual(sum(a['mine'] for a in self.app.approvals_list(self.fresh(self.cyd))), 1)

    def test_next_step_after_cover_goes_to_the_next_approver(self):
        rid = self.request(self.ann, 'bob', 'dee')
        self.away(self.bob, 'cyd')
        self.app.decide_approval(rid, 'approved', '', self.fresh(self.cyd))
        self.assertEqual(self.app.approvals_list(self.fresh(self.dee))[0]['mine'], True)
        self.assertEqual(self.app.approvals_list(self.fresh(self.cyd))[0]['can_decide'], False)


class SetDelegationValidationTests(CoverMixin, AppTestCase):
    def setUp(self):
        super().setUp()
        self.bob, self.cyd = self.user('bob'), self.user('cyd')
        self.viewer = self.user('vic', 'viewer')

    def test_validation(self):
        bob = self.fresh(self.bob)
        for delegate, until, fragment in (
            ('ghost', day(3), 'active user'),
            ('bob', day(3), 'yourself'),
            ('vic', day(3), 'member role'),
            ('cyd', '', 'YYYY-MM-DD'),
            ('cyd', 'tomorrow', 'YYYY-MM-DD'),
            ('cyd', '2026-02-30', 'real date'),
            ('cyd', day(-1), 'past'),
            ('cyd', day(91), '90 days'),
        ):
            with self.assertRaises(ValueError, msg=f'{delegate} {until}') as ctx:
                self.app.set_delegation(bob, delegate, until)
            self.assertIn(fragment, str(ctx.exception))
        self.assertEqual(self.fresh(self.bob)['delegate_to'], '')

    def test_disabled_users_cannot_be_chosen(self):
        self.user('boss', 'admin')
        self.app.update_user(self.cyd['id'], {'active': False})
        with self.assertRaises(ValueError):
            self.app.set_delegation(self.fresh(self.bob), 'cyd', day(3))

    def test_accepts_a_display_name_and_stores_the_username(self):
        result = self.app.set_delegation(self.fresh(self.bob), 'CYD', day(3))
        self.assertEqual(result['delegate_to'], 'cyd')

    def test_can_be_ended_and_renewed(self):
        bob = self.fresh(self.bob)
        self.app.set_delegation(bob, 'cyd', day(3))
        self.assertEqual(self.fresh(self.bob)['delegate_to'], 'cyd')
        self.app.set_delegation(bob, '', '')
        self.assertEqual((self.fresh(self.bob)['delegate_to'], self.fresh(self.bob)['delegate_until']), ('', ''))
        self.app.set_delegation(bob, 'cyd', day(90))                          # exactly 90 days is allowed

    def test_needs_an_account(self):
        with self.assertRaises(ValueError):
            self.app.set_delegation({'id': 0, 'username': 'local', 'role': 'admin', 'open': True}, 'cyd', day(3))

    def test_people_directory_says_who_can_take_approvals(self):
        listing = {p['username']: p['can_decide'] for p in self.app.people()}
        self.assertEqual((listing['bob'], listing['vic']), (True, False))

    def test_audit_trail(self):
        self.app.set_delegation(self.fresh(self.bob), 'cyd', day(3))
        entries = [e for e in self.app.read_table('audit') if e['action'] == 'delegation_set']
        self.assertEqual(json.loads(entries[0]['details'])['delegate'], 'cyd')


class CoverDataTests(CoverMixin, AppTestCase):
    def test_acting_for_survives_a_backup_round_trip(self):
        ann, bob, cyd = self.user('ann'), self.user('bob'), self.user('cyd')
        rid = self.request(ann, 'bob')
        self.app.set_delegation(self.fresh(bob), 'cyd', day(3))
        self.app.decide_approval(rid, 'approved', '', self.fresh(cyd))
        backup = self.app.backup_export()
        self.app.delete_row('approvals', rid)
        self.app.restore_backup(backup)
        self.assertEqual(self.app.approvals_list()[0]['steps'][0]['acting_for'], 'bob')

    def test_old_databases_gain_the_new_columns(self):
        old = os.path.join(self.tmp.name, 'old.sqlite3')
        with sqlite3.connect(old) as c:
            c.executescript("""
                CREATE TABLE users(id INTEGER PRIMARY KEY AUTOINCREMENT,username TEXT NOT NULL UNIQUE COLLATE NOCASE,display_name TEXT NOT NULL,role TEXT NOT NULL DEFAULT 'member',password_hash TEXT NOT NULL,active INTEGER NOT NULL DEFAULT 1,created_at TEXT NOT NULL);
                CREATE TABLE approval_steps(id INTEGER PRIMARY KEY AUTOINCREMENT,approval_id INTEGER NOT NULL,stage INTEGER NOT NULL,approver TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'pending',comment TEXT DEFAULT '',decided_by TEXT DEFAULT '',decided_at TEXT DEFAULT '');
                INSERT INTO users(username,display_name,password_hash,created_at) VALUES('ann','Ann','x','2026-01-01');
            """)
        os.environ['AUTOMATION_DB'] = old
        sys.modules.pop('app', None)
        app = importlib.import_module('app')
        app.init()
        app.init()
        self.assertEqual(app.list_users()[0]['delegate_to'], '')
        with sqlite3.connect(old) as c:
            self.assertIn('acting_for', [r[1] for r in c.execute('PRAGMA table_info(approval_steps)')])


class HttpCoverTests(CoverMixin, AppTestCase):
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

    def test_full_flow_over_http(self):
        self.call('POST', '/api/auth/setup', {'username': 'boss', 'password': PW})
        admin = self.login('boss')
        for n in ('ann', 'bob', 'cyd'):
            self.call('POST', '/api/users', {'username': n, 'display_name': n.title(), 'role': 'member', 'password': PW}, admin)
        ann, bob, cyd = self.login('ann'), self.login('bob'), self.login('cyd')
        rid = self.call('POST', '/api/approvals', {'title': 'Crane', 'approver': 'bob'}, ann)[1]['id']
        decide = lambda cookie: self.call('POST', '/api/approvals/decision', {'id': rid, 'decision': 'approved'}, cookie)[0]
        self.assertEqual(decide(cyd), 403)
        status, data, _ = self.call('POST', '/api/auth/delegate', {'delegate': 'cyd', 'until': day(7)}, bob)
        self.assertEqual((status, data['delegate_to']), (200, 'cyd'))
        self.assertEqual(self.call('GET', '/api/auth/me', cookie=bob)[1]['user']['delegate_to'], 'cyd')
        self.assertEqual(self.call('GET', '/api/overview', cookie=cyd)[1]['awaiting_me'], 1)
        self.assertEqual(decide(cyd), 200)
        step = self.call('GET', '/api/approvals', cookie=ann)[1][0]['steps'][0]
        self.assertEqual((step['decided_by'], step['acting_for']), ('Cyd', 'bob'))

    def test_validation_errors_are_400s(self):
        self.call('POST', '/api/auth/setup', {'username': 'boss', 'password': PW})
        admin = self.login('boss')
        self.call('POST', '/api/users', {'username': 'bob', 'role': 'member', 'password': PW}, admin)
        bob = self.login('bob')
        self.assertEqual(self.call('POST', '/api/auth/delegate', {'delegate': 'ghost', 'until': day(3)}, bob)[0], 400)
        self.assertEqual(self.call('POST', '/api/auth/delegate', {'delegate': 'boss', 'until': day(300)}, bob)[0], 400)
        self.assertEqual(self.call('POST', '/api/auth/delegate', {'delegate': 'boss', 'until': day(3)})[0], 401)


if __name__ == '__main__':
    unittest.main()
