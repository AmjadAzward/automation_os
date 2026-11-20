"""Comments on tasks, approvals and contracts, and the notifications they raise."""
import http.client
import json
import sqlite3
import threading
import unittest
from datetime import datetime, timedelta
from http.server import ThreadingHTTPServer

from test_app import AppTestCase

PW = 'correct-horse-battery'


class CommentMixin:
    def user(self, username, role='member', name=None):
        self.app.create_user({'username': username, 'display_name': name or username.title(), 'role': role, 'password': PW})
        return next(u for u in self.app.list_users() if u['username'] == username)

    def request(self, who, approver='bob'):
        return self.app.add_row('approvals', self.app.prepare_approval_payload({'title': 'Crane', 'approver': approver}, who))['id']

    def backdate(self, comment_id, days):
        moment = (datetime.now().astimezone() - timedelta(days=days)).isoformat(timespec='seconds')
        with sqlite3.connect(self.app.DB) as c:
            c.execute('UPDATE comments SET at=? WHERE id=?', (moment, comment_id))


class CommentTests(CommentMixin, AppTestCase):
    def setUp(self):
        super().setUp()
        self.ann, self.bob, self.cyd = self.user('ann', name='Ann Lee'), self.user('bob'), self.user('cyd')
        self.boss = self.user('boss', 'admin')
        self.rid = self.request(self.ann)

    def test_add_and_list_in_order_with_display_names(self):
        self.app.add_comment('approvals', self.rid, 'Is this the final quote?', self.bob)
        self.app.add_comment('approvals', self.rid, 'Yes, attached to the email.', self.ann)
        thread = self.app.list_comments('approvals', self.rid)
        self.assertEqual([c['body'] for c in thread], ['Is this the final quote?', 'Yes, attached to the email.'])
        self.assertEqual([c['author_name'] for c in thread], ['Bob', 'Ann Lee'])

    def test_threads_are_per_record_and_per_type(self):
        task = self.app.add_row('tasks', {'title': 'T'})['id']
        self.app.add_comment('tasks', task, 'on the task', self.ann)
        self.app.add_comment('approvals', self.rid, 'on the request', self.ann)
        self.assertEqual([c['body'] for c in self.app.list_comments('tasks', task)], ['on the task'])
        self.assertEqual(self.app.list_comments('contracts', 1), [])
        self.assertEqual(self.app.comment_counts('tasks'), {str(task): 1})

    def test_validation(self):
        for entity in ('users', 'audit', 'settings', '', None, 'tasks; DROP TABLE tasks'):
            with self.assertRaises(ValueError):
                self.app.add_comment(entity, 1, 'x', self.ann)
        for bad in ('', '   ', None):
            with self.assertRaises(ValueError):
                self.app.add_comment('approvals', self.rid, bad, self.ann)
        with self.assertRaises(ValueError):
            self.app.add_comment('approvals', self.rid, 'x' * 2001, self.ann)
        with self.assertRaises(ValueError):
            self.app.add_comment('approvals', 9999, 'orphan', self.ann)
        self.assertEqual(self.app.list_comments('approvals', self.rid), [])

    def test_text_is_trimmed_and_not_copied_into_the_audit_log(self):
        self.app.add_comment('approvals', self.rid, '  secret supplier price is 4.20  ', self.ann)
        self.assertEqual(self.app.list_comments('approvals', self.rid)[0]['body'], 'secret supplier price is 4.20')
        self.assertNotIn('4.20', json.dumps(self.app.read_table('audit')))
        self.assertIn('comment_id', json.dumps(self.app.read_table('audit')))    # only ids and the length are recorded

    def test_only_the_author_or_an_admin_can_delete(self):
        mine = self.app.add_comment('approvals', self.rid, 'mine', self.bob)['id']
        with self.assertRaises(self.app.Forbidden):
            self.app.delete_comment(mine, self.cyd)
        self.app.delete_comment(mine, self.bob)
        again = self.app.add_comment('approvals', self.rid, 'again', self.bob)['id']
        self.app.delete_comment(again, self.boss)
        self.assertEqual(self.app.list_comments('approvals', self.rid), [])
        with self.assertRaises(ValueError):
            self.app.delete_comment(again, self.boss)

    def test_comments_go_when_the_record_goes(self):
        task = self.app.add_row('tasks', {'title': 'T'})['id']
        task2 = self.app.add_row('tasks', {'title': 'T2'})['id']
        self.app.add_comment('tasks', task, 'a', self.ann)
        self.app.add_comment('tasks', task2, 'b', self.ann)
        self.app.add_comment('approvals', self.rid, 'c', self.ann)
        self.app.delete_row('tasks', task)
        self.app.bulk_action('tasks', [task2], 'delete')
        self.app.delete_row('approvals', self.rid)
        with sqlite3.connect(self.app.DB) as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM comments').fetchone()[0], 0)

    def test_survive_a_backup_round_trip(self):
        self.app.add_comment('approvals', self.rid, 'keep me', self.ann)
        backup = self.app.backup_export()
        self.app.delete_comment(1, self.boss)
        self.app.restore_backup(backup)
        self.assertEqual(self.app.list_comments('approvals', self.rid)[0]['body'], 'keep me')

    def test_single_user_mode_uses_a_local_author(self):
        task = self.app.add_row('tasks', {'title': 'T'})['id']
        self.app.add_comment('tasks', task, 'solo', None)
        self.assertEqual(self.app.list_comments('tasks', task)[0]['author'], 'local')


class CommentNotificationTests(CommentMixin, AppTestCase):
    def setUp(self):
        super().setUp()
        self.ann, self.bob, self.cyd, self.dee = (self.user(n) for n in ('ann', 'bob', 'cyd', 'dee'))
        self.rid = self.request(self.ann, 'bob')

    def comments_for(self, user):
        return [n for n in self.app.all_notifications(user) if n['kind'] == 'comment']

    def test_the_other_party_is_told(self):
        self.app.add_comment('approvals', self.rid, 'Which supplier is this?', self.bob)
        told = self.comments_for(self.ann)
        self.assertEqual(len(told), 1)
        self.assertIn('Bob commented', told[0]['detail'])
        self.assertIn('Which supplier is this?', told[0]['detail'])
        self.assertEqual((told[0]['title'], told[0]['page'], told[0]['severity']), ('Crane', 'approvals', 'low'))
        self.app.add_comment('approvals', self.rid, 'Acme, quote attached', self.ann)
        self.assertEqual(len(self.comments_for(self.bob)), 1)

    def test_you_are_never_told_about_your_own_comment(self):
        self.app.add_comment('approvals', self.rid, 'mine', self.ann)
        self.assertEqual(self.comments_for(self.ann), [])

    def test_uninvolved_people_hear_nothing(self):
        self.app.add_comment('approvals', self.rid, 'hello', self.ann)
        self.assertEqual(self.comments_for(self.cyd) + self.comments_for(self.dee), [])

    def test_a_later_approver_in_the_chain_is_included(self):
        rid = self.app.add_row('approvals', self.app.prepare_approval_payload({'title': 'Two step', 'approver': 'bob', 'second_approver': 'cyd'}, self.ann))['id']
        self.app.add_comment('approvals', rid, 'context for both approvers', self.ann)
        self.assertEqual(len(self.comments_for(self.cyd)), 1)

    def test_a_covering_colleague_is_included(self):
        from datetime import date
        self.app.set_delegation(self.app.session_user(self.app.start_session(self.bob['id'])), 'dee', (date.today() + timedelta(days=3)).isoformat())
        self.app.add_comment('approvals', self.rid, 'while you cover', self.ann)
        dee = self.app.session_user(self.app.start_session(self.dee['id']))
        self.assertEqual(len(self.comments_for(dee)), 1)

    def test_old_comments_stop_notifying(self):
        cid = self.app.add_comment('approvals', self.rid, 'old news', self.bob)['id']
        self.backdate(cid, 5)
        self.assertEqual(self.comments_for(self.ann), [])

    def test_task_and_contract_owners_are_told(self):
        task = self.app.add_row('tasks', {'title': 'Mine', 'owner': 'ann'})['id']
        contract = self.app.add_row('contracts', {'contract': 'MSA', 'obligation': 'O', 'due_date': '2027-01-01', 'owner': 'Ann Lee'})['id']
        self.app.add_comment('tasks', task, 'status?', self.bob)
        self.app.add_comment('contracts', contract, 'renewal date?', self.bob)
        pages = sorted(n['page'] for n in self.comments_for(self.ann))
        self.assertEqual(pages, ['tasks'])      # this Ann's display name is "Ann", so a contract owned by "Ann Lee" is someone else's

    def test_long_comments_are_shortened_in_the_alert(self):
        self.app.add_comment('approvals', self.rid, 'word ' * 60, self.bob)
        self.assertLessEqual(len(self.comments_for(self.ann)[0]['detail']), 110)

    def test_single_user_mode_has_none(self):
        self.app.add_comment('approvals', self.rid, 'x', self.bob)
        self.assertEqual([n for n in self.app.all_notifications(None) if n['kind'] == 'comment'], [])

    def test_ordering_keeps_urgent_items_first(self):
        self.app.add_comment('approvals', self.rid, 'fyi', self.ann)
        kinds = [n['kind'] for n in self.app.all_notifications(self.bob)]
        self.assertEqual(kinds, ['approval', 'comment'])


class HttpCommentTests(CommentMixin, AppTestCase):
    def setUp(self):
        super().setUp()
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), self.app.Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.call('POST', '/api/auth/setup', {'username': 'boss', 'password': PW})
        admin = self.login('boss')
        for n, role in (('ann', 'member'), ('bob', 'member'), ('vic', 'viewer')):
            self.call('POST', '/api/users', {'username': n, 'role': role, 'password': PW}, admin)
        self.admin, self.ann, self.bob, self.vic = admin, self.login('ann'), self.login('bob'), self.login('vic')

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

    def test_roles_and_flow(self):
        rid = self.call('POST', '/api/approvals', {'title': 'Crane', 'approver': 'bob'}, self.ann)[1]['id']
        self.assertEqual(self.call('POST', '/api/comments', {'entity': 'approvals', 'id': rid, 'body': 'hi'}, self.vic)[0], 403)   # viewers read only
        status, data, _ = self.call('POST', '/api/comments', {'entity': 'approvals', 'id': rid, 'body': 'Is this urgent?'}, self.bob)
        self.assertEqual(status, 200, data)
        thread = self.call('GET', f'/api/comments?entity=approvals&id={rid}', cookie=self.vic)[1]        # but they can read
        self.assertEqual((thread[0]['author'], thread[0]['author_name'], thread[0]['body']), ('bob', 'bob', 'Is this urgent?'))   # no display name was set, so it defaults to the username
        self.assertEqual(self.call('GET', '/api/comments/counts?entity=approvals', cookie=self.vic)[1], {str(rid): 1})
        self.assertEqual(self.call('GET', '/api/comments?entity=approvals&id=1')[0], 401)
        note = self.call('GET', '/api/notifications', cookie=self.ann)[1]
        self.assertIn('comment', [n['kind'] for n in note])

    def test_deleting_over_http_follows_ownership(self):
        rid = self.call('POST', '/api/approvals', {'title': 'Crane', 'approver': 'bob'}, self.ann)[1]['id']
        cid = self.call('POST', '/api/comments', {'entity': 'approvals', 'id': rid, 'body': 'x'}, self.ann)[1]['id']
        self.assertEqual(self.call('DELETE', f'/api/comments/{cid}', cookie=self.bob)[0], 403)
        self.assertEqual(self.call('DELETE', f'/api/comments/{cid}', cookie=self.ann)[0], 200)         # a member may delete their own
        self.assertEqual(self.call('DELETE', f'/api/comments/{cid}', cookie=self.ann)[0], 400)

    def test_bad_requests(self):
        self.assertEqual(self.call('POST', '/api/comments', {'entity': 'users', 'id': 1, 'body': 'x'}, self.ann)[0], 400)
        self.assertEqual(self.call('GET', '/api/comments?entity=users&id=1', cookie=self.ann)[0], 400)
        self.assertEqual(self.call('POST', '/api/comments', {'entity': 'tasks', 'id': 99, 'body': 'x'}, self.ann)[0], 400)


if __name__ == '__main__':
    unittest.main()
