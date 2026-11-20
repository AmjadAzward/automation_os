"""Approver identity, request ownership, 'awaiting me' counts and notifications."""
import http.client
import json
import sqlite3
import threading
import unittest
from datetime import datetime, timedelta
from http.server import ThreadingHTTPServer

from test_app import AppTestCase

PW = 'correct-horse-battery'


class PeopleMixin:
    def user(self, username, display=None, role='member'):
        self.app.create_user({'username': username, 'display_name': display or username.title(), 'role': role, 'password': PW})
        return next(u for u in self.app.list_users() if u['username'] == username)

    def backdate(self, table, ident, column, days):
        moment = (datetime.now().astimezone() - timedelta(days=days)).isoformat(timespec='seconds')
        with sqlite3.connect(self.app.DB) as c:
            c.execute(f'UPDATE {table} SET {column}=? WHERE id=?', (moment, ident))


class ApproverIdentityTests(PeopleMixin, AppTestCase):
    def test_people_directory_lists_only_active_users_without_secrets(self):
        self.user('ann')
        bob = self.user('bob')
        self.user('boss', role='admin')
        self.app.update_user(bob['id'], {'active': False})
        listing = self.app.people()
        self.assertEqual({p['username'] for p in listing}, {'ann', 'boss'})
        self.assertEqual(set(listing[0]), {'username', 'display_name'})

    def test_requester_is_forced_to_the_signed_in_user(self):
        ann = self.user('ann')
        self.user('bob')
        payload = self.app.prepare_approval_payload({'title': 'T', 'requester': 'someone-else', 'approver': 'bob'}, ann)
        self.assertEqual(payload['requester'], 'ann')

    def test_display_names_are_stored_as_usernames(self):
        ann = self.user('ann')
        self.user('rjones', 'Robert Jones')
        payload = self.app.prepare_approval_payload({'title': 'T', 'approver': 'robert jones', 'second_approver': 'RJONES'}, ann)
        self.assertEqual((payload['approver'], payload['second_approver']), ('rjones', 'rjones'))

    def test_unknown_or_disabled_approvers_are_rejected(self):
        ann = self.user('ann')
        bob = self.user('bob')
        self.app.update_user(bob['id'], {'active': False})
        for name in ('nobody', 'bob'):
            with self.assertRaises(ValueError):
                self.app.prepare_approval_payload({'title': 'T', 'approver': name}, ann)
        with self.assertRaises(ValueError) as ctx:
            self.app.prepare_approval_payload({'title': 'T', 'approver': 'ann', 'second_approver': 'ghost'}, ann)
        self.assertIn('Second approver', str(ctx.exception))

    def test_single_user_mode_leaves_the_payload_alone(self):
        open_user = {'id': 0, 'username': 'local', 'display_name': 'Local user', 'role': 'admin', 'open': True}
        payload = self.app.prepare_approval_payload({'title': 'T', 'requester': 'Ann', 'approver': 'Whoever'}, open_user)
        self.assertEqual((payload['requester'], payload['approver']), ('Ann', 'Whoever'))

    def test_only_requester_or_admin_can_edit_or_delete(self):
        ann, bob, boss = self.user('ann'), self.user('bob'), self.user('boss', role='admin')
        self.user('cyd')
        rid = self.app.add_row('approvals', self.app.prepare_approval_payload({'title': 'T', 'approver': 'cyd'}, ann))['id']
        with self.assertRaises(self.app.Forbidden):
            self.app.edit_approval_guard(rid, {'approver': 'bob'}, bob)        # the hijack this guard exists to stop
        with self.assertRaises(self.app.Forbidden):
            self.app.delete_approval_guard(rid, bob)
        self.app.edit_approval_guard(rid, {'approver': 'bob'}, ann)
        self.app.edit_approval_guard(rid, {'approver': 'bob'}, boss)
        self.app.delete_approval_guard(rid, ann)

    def test_requester_cannot_be_relabelled_except_by_admin(self):
        ann, boss = self.user('ann'), self.user('boss', role='admin')
        self.user('bob')
        rid = self.app.add_row('approvals', self.app.prepare_approval_payload({'title': 'T', 'approver': 'bob'}, ann))['id']
        body = {'requester': 'bob', 'title': 'x'}
        self.app.edit_approval_guard(rid, body, ann)
        self.assertNotIn('requester', body)
        body = {'requester': 'bob'}
        self.app.edit_approval_guard(rid, body, boss)
        self.assertIn('requester', body)

    def test_editing_to_an_unknown_approver_is_rejected(self):
        ann = self.user('ann')
        self.user('bob')
        rid = self.app.add_row('approvals', self.app.prepare_approval_payload({'title': 'T', 'approver': 'bob'}, ann))['id']
        with self.assertRaises(ValueError):
            self.app.edit_approval_guard(rid, {'approver': 'ghost'}, ann)

    def test_decision_still_works_for_a_username_approver(self):
        ann, bob = self.user('ann'), self.user('bob', 'Bob Brown')
        rid = self.app.add_row('approvals', self.app.prepare_approval_payload({'title': 'T', 'approver': 'Bob Brown'}, ann))['id']
        self.assertEqual(self.app.approvals_list(bob)[0]['approver'], 'bob')
        self.assertTrue(self.app.approvals_list(bob)[0]['can_decide'])
        self.assertEqual(self.app.decide_approval(rid, 'approved', '', bob)['status'], 'approved')

    def test_escalation_setting_is_clamped(self):
        self.app.save_automation_settings({'approval_escalate_days': 999})
        self.assertEqual(self.app.automation_settings()['approval_escalate_days'], 60)
        self.app.save_automation_settings({'approval_escalate_days': -5})
        self.assertEqual(self.app.automation_settings()['approval_escalate_days'], 0)


class NotificationTests(PeopleMixin, AppTestCase):
    def setUp(self):
        super().setUp()
        self.ann, self.bob, self.cyd = self.user('ann'), self.user('bob'), self.user('cyd')
        self.boss = self.user('boss', role='admin')
        self.rid = self.app.add_row('approvals', self.app.prepare_approval_payload({'title': 'Crane', 'approver': 'bob', 'second_approver': 'cyd'}, self.ann))['id']

    def kinds(self, user):
        return [(n['kind'], n['title']) for n in self.app.notifications(user)]

    def test_approver_is_told_when_it_is_their_turn(self):
        self.assertIn(('approval', 'Crane'), self.kinds(self.bob))
        self.assertNotIn(('approval', 'Crane'), self.kinds(self.cyd))     # not step 2's turn yet
        self.app.decide_approval(self.rid, 'approved', '', self.bob)
        self.assertIn(('approval', 'Crane'), self.kinds(self.cyd))
        self.assertNotIn(('approval', 'Crane'), self.kinds(self.bob))

    def test_next_step_gets_a_new_notification_key(self):
        before = {n['key'] for n in self.app.notifications(self.bob)}
        self.app.decide_approval(self.rid, 'approved', '', self.bob)
        after = {n['key'] for n in self.app.notifications(self.cyd)}
        self.assertTrue(after and not (after & before))   # a dismissed earlier alert cannot hide the new one

    def test_requester_sees_the_outcome(self):
        self.app.decide_approval(self.rid, 'rejected', 'too expensive', self.bob)
        self.assertIn(('outcome', 'Crane'), self.kinds(self.ann))
        self.assertNotIn(('outcome', 'Crane'), self.kinds(self.cyd))

    def test_stuck_requests_escalate_to_requester_and_admin_only(self):
        self.backdate('approvals', self.rid, 'created_at', 10)
        stuck = lambda u: ('stuck', 'Crane') in self.kinds(u)
        self.assertTrue(stuck(self.ann) and stuck(self.boss))
        self.assertFalse(stuck(self.cyd))
        detail = next(n['detail'] for n in self.app.notifications(self.boss) if n['kind'] == 'stuck')
        self.assertIn('Bob', detail)                       # shows the display name, not the username
        self.assertIn('10 days', detail)
        high = next(n for n in self.app.notifications(self.bob) if n['kind'] == 'approval')
        self.assertEqual(high['severity'], 'high')

    def test_escalation_can_be_switched_off(self):
        self.backdate('approvals', self.rid, 'created_at', 10)
        self.app.save_automation_settings({'approval_escalate_days': 0})
        self.assertNotIn(('stuck', 'Crane'), self.kinds(self.ann))
        self.assertEqual(next(n for n in self.app.notifications(self.bob) if n['kind'] == 'approval')['severity'], 'medium')

    def test_tasks_and_contracts_are_assigned_by_owner(self):
        yesterday = (datetime.now().date() - timedelta(days=1)).isoformat()
        self.app.add_row('tasks', {'title': 'Ann overdue', 'owner': 'ann', 'due_date': yesterday})
        self.app.add_row('tasks', {'title': 'Bob overdue', 'owner': 'Bob', 'due_date': yesterday})
        self.app.add_row('tasks', {'title': 'Done already', 'owner': 'ann', 'due_date': yesterday, 'status': 'done'})
        self.app.add_row('tasks', {'title': 'Far away', 'owner': 'ann', 'due_date': (datetime.now().date() + timedelta(days=30)).isoformat()})
        self.app.add_row('contracts', {'contract': 'MSA', 'obligation': 'Review', 'owner': 'Ann', 'due_date': (datetime.now().date() + timedelta(days=2)).isoformat()})
        mine = self.kinds(self.ann)
        self.assertIn(('task', 'Ann overdue'), mine)
        self.assertIn(('contract', 'MSA'), mine)
        for hidden in ('Bob overdue', 'Done already', 'Far away'):
            self.assertNotIn(('task', hidden), mine)
        self.assertIn('Overdue by 1 day', next(n['detail'] for n in self.app.notifications(self.ann) if n['title'] == 'Ann overdue'))

    def test_admin_override_does_not_flood_the_admin_with_everyone_elses_requests(self):
        self.assertNotIn(('approval', 'Crane'), self.kinds(self.boss))
        self.assertTrue(self.app.approvals_list(self.boss)[0]['can_decide'])    # may still step in
        self.assertFalse(self.app.approvals_list(self.boss)[0]['mine'])
        self.assertTrue(self.app.approvals_list(self.bob)[0]['mine'])

    def test_most_urgent_first(self):
        yesterday = (datetime.now().date() - timedelta(days=1)).isoformat()
        self.app.add_row('tasks', {'title': 'Late', 'owner': 'bob', 'due_date': yesterday})
        severities = [n['severity'] for n in self.app.notifications(self.bob)]
        self.assertEqual(severities, sorted(severities, key={'high': 0, 'medium': 1, 'low': 2}.get))

    def test_open_mode_shows_everything_without_outcomes(self):
        items = self.app.notifications(None)
        self.assertIn(('approval', 'Crane'), [(n['kind'], n['title']) for n in items])


class HttpPeopleTests(PeopleMixin, AppTestCase):
    def setUp(self):
        super().setUp()
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), self.app.Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.call('POST', '/api/auth/setup', {'username': 'boss', 'display_name': 'Big Boss', 'password': PW})
        self.admin = self.login('boss')
        for n in ('ann', 'bob', 'cyd'):
            self.call('POST', '/api/users', {'username': n, 'display_name': n.title(), 'role': 'member', 'password': PW}, self.admin)
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
        cookie_out = r.getheader('Set-Cookie')
        conn.close()
        try:
            data = json.loads(raw)
        except ValueError:
            data = raw
        return r.status, data, cookie_out

    def login(self, name):
        status, data, cookie = self.call('POST', '/api/auth/login', {'username': name, 'password': PW})
        self.assertEqual(status, 200, data)
        return cookie.split(';')[0]

    def create(self, cookie, **over):
        body = {'title': 'Crane', 'approver': 'bob', 'amount': '10'}
        body.update(over)
        return self.call('POST', '/api/approvals', body, cookie)

    def test_people_directory_for_any_signed_in_user(self):
        status, data, _ = self.call('GET', '/api/people', cookie=self.ann)
        self.assertEqual(status, 200)
        self.assertEqual({p['username'] for p in data}, {'boss', 'ann', 'bob', 'cyd'})
        self.assertEqual(self.call('GET', '/api/people')[0], 401)

    def test_requester_cannot_be_spoofed_over_http(self):
        status, data, _ = self.create(self.ann, requester='cyd')
        self.assertEqual(status, 200, data)
        listing = self.call('GET', '/api/approvals', cookie=self.ann)[1]
        self.assertEqual(listing[0]['requester'], 'ann')

    def test_unknown_approver_is_a_400(self):
        status, data, _ = self.create(self.ann, approver='ghost')
        self.assertEqual(status, 400)
        self.assertIn('active user', data['error'])

    def test_member_cannot_hijack_someone_elses_request(self):
        rid = self.create(self.ann)[1]['id']
        self.assertEqual(self.call('PUT', f'/api/approvals/{rid}', {'approver': 'cyd'}, self.cyd)[0], 403)
        self.assertEqual(self.call('PUT', f'/api/approvals/{rid}', {'approver': 'cyd'}, self.ann)[0], 200)
        self.assertEqual(self.call('PUT', f'/api/approvals/{rid}', {'amount': '20'}, self.admin)[0], 200)

    def test_overview_counts_what_is_waiting_on_me(self):
        self.create(self.ann)
        self.create(self.ann, title='Second', approver='cyd')
        count = lambda cookie: self.call('GET', '/api/overview', cookie=cookie)[1]['awaiting_me']
        self.assertEqual((count(self.bob), count(self.cyd), count(self.ann)), (1, 1, 0))
        self.assertEqual(self.call('GET', '/api/overview', cookie=self.bob)[1]['pending_approvals'], 2)

    def test_notifications_endpoint(self):
        self.create(self.ann)
        status, data, _ = self.call('GET', '/api/notifications', cookie=self.bob)
        self.assertEqual((status, [n['kind'] for n in data]), (200, ['approval']))
        self.assertEqual(self.call('GET', '/api/notifications', cookie=self.ann)[1], [])
        self.assertEqual(self.call('GET', '/api/notifications')[0], 401)


if __name__ == '__main__':
    unittest.main()
