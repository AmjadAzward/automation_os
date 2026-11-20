"""Changing your own password, signing out everywhere, and the Secure cookie flag."""
import http.client
import json
import threading
import unittest
from http.server import ThreadingHTTPServer

from test_app import AppTestCase

PW = 'correct-horse-battery'
NEW = 'a-completely-new-passphrase'


class PasswordTests(AppTestCase):
    def setUp(self):
        super().setUp()
        self.app.create_user({'username': 'ann', 'password': PW, 'role': 'viewer'})
        self.ann = self.app.list_users()[0]

    def test_change_password_end_to_end(self):
        keep, other = self.app.start_session(self.ann['id']), self.app.start_session(self.ann['id'])
        result = self.app.change_password(self.ann, PW, NEW, keep)
        self.assertEqual(result['ended'], 1)
        self.assertEqual(self.app.authenticate('ann', NEW)['username'], 'ann')
        with self.assertRaises(ValueError):
            self.app.authenticate('ann', PW)
        self.assertIsNotNone(self.app.session_user(keep))     # the session that made the change stays
        self.assertIsNone(self.app.session_user(other))       # every other device is signed out

    def test_wrong_current_password(self):
        with self.assertRaises(ValueError) as ctx:
            self.app.change_password(self.ann, 'not-my-password', NEW)
        self.assertIn('current password', str(ctx.exception))
        self.assertEqual(self.app.authenticate('ann', PW)['username'], 'ann')   # unchanged

    def test_new_password_rules(self):
        with self.assertRaises(ValueError):
            self.app.change_password(self.ann, PW, 'short')
        with self.assertRaises(ValueError) as ctx:
            self.app.change_password(self.ann, PW, PW)
        self.assertIn('already using', str(ctx.exception))

    def test_guessing_the_current_password_is_throttled(self):
        for _ in range(5):
            with self.assertRaises(ValueError):
                self.app.change_password(self.ann, 'wrong-wrong-wrong', NEW)
        with self.assertRaises(ValueError) as ctx:
            self.app.change_password(self.ann, PW, NEW)       # even the right one is refused while locked
        self.assertIn('Too many', str(ctx.exception))

    def test_single_user_mode_has_no_password_to_change(self):
        open_user = {'id': 0, 'username': 'local', 'display_name': 'Local user', 'role': 'admin', 'open': True}
        with self.assertRaises(ValueError):
            self.app.change_password(open_user, PW, NEW)
        with self.assertRaises(ValueError):
            self.app.logout_all(open_user)

    def test_logout_all_ends_every_session(self):
        tokens = [self.app.start_session(self.ann['id']) for _ in range(3)]
        self.assertEqual(self.app.logout_all(self.ann), 3)
        self.assertTrue(all(self.app.session_user(t) is None for t in tokens))

    def test_audit_records_it_without_secrets(self):
        self.app.change_password(self.ann, PW, NEW)
        blob = json.dumps(self.app.read_table('audit'))
        self.assertIn('password_change', blob)
        self.assertNotIn(NEW, blob)
        self.assertNotIn(PW, blob)


class HttpSelfServiceTests(AppTestCase):
    def setUp(self):
        super().setUp()
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), self.app.Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        super().tearDown()

    def call(self, method, path, body=None, cookie=None, extra=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)
        headers = {'Host': f'127.0.0.1:{self.port}', 'Content-Type': 'application/json'}
        if cookie:
            headers['Cookie'] = cookie
        headers.update(extra or {})
        conn.request(method, path, body=json.dumps(body) if body is not None else None, headers=headers)
        r = conn.getresponse()
        raw = r.read()
        set_cookie = r.getheader('Set-Cookie')
        conn.close()
        return r.status, json.loads(raw), set_cookie

    def setup_accounts(self):
        self.call('POST', '/api/auth/setup', {'username': 'boss', 'password': PW})
        self.admin = self.login('boss')
        self.call('POST', '/api/users', {'username': 'vic', 'role': 'viewer', 'password': PW}, self.admin)

    def login(self, name, password=PW, extra=None):
        status, data, cookie = self.call('POST', '/api/auth/login', {'username': name, 'password': password}, extra=extra)
        self.assertEqual(status, 200, data)
        return cookie.split(';')[0]

    def test_even_a_viewer_can_change_their_own_password(self):
        self.setup_accounts()
        viewer = self.login('vic')
        self.assertEqual(self.call('POST', '/api/tasks', {'title': 'x'}, viewer)[0], 403)   # still read-only
        status, data, _ = self.call('POST', '/api/auth/password', {'current': PW, 'new': NEW}, viewer)
        self.assertEqual((status, data['ok']), (200, True))
        self.login('vic', NEW)

    def test_wrong_current_password_is_a_400_not_a_sign_out(self):
        self.setup_accounts()
        viewer = self.login('vic')
        status, data, _ = self.call('POST', '/api/auth/password', {'current': 'nope-nope-nope', 'new': NEW}, viewer)
        self.assertEqual(status, 400)
        self.assertNotIn('login', data)
        self.assertEqual(self.call('GET', '/api/tasks', cookie=viewer)[0], 200)

    def test_requires_a_signed_in_account(self):
        self.assertEqual(self.call('POST', '/api/auth/password', {'current': PW, 'new': NEW})[0], 400)  # single-user mode
        self.setup_accounts()
        self.assertEqual(self.call('POST', '/api/auth/password', {'current': PW, 'new': NEW})[0], 401)  # anonymous

    def test_other_devices_are_signed_out_when_the_password_changes(self):
        self.setup_accounts()
        phone, laptop = self.login('vic'), self.login('vic')
        self.call('POST', '/api/auth/password', {'current': PW, 'new': NEW}, laptop)
        self.assertEqual(self.call('GET', '/api/tasks', cookie=laptop)[0], 200)
        self.assertEqual(self.call('GET', '/api/tasks', cookie=phone)[0], 401)

    def test_logout_all_over_http(self):
        self.setup_accounts()
        a, b = self.login('vic'), self.login('vic')
        status, data, cleared = self.call('POST', '/api/auth/logout-all', {}, a)
        self.assertEqual((status, data['ended']), (200, 2))
        self.assertIn('Max-Age=0', cleared)
        self.assertEqual(self.call('GET', '/api/tasks', cookie=b)[0], 401)

    def test_cookie_is_marked_secure_only_behind_https(self):
        self.call('POST', '/api/auth/setup', {'username': 'boss', 'password': PW})
        _, _, plain = self.call('POST', '/api/auth/login', {'username': 'boss', 'password': PW})
        _, _, tls = self.call('POST', '/api/auth/login', {'username': 'boss', 'password': PW}, extra={'X-Forwarded-Proto': 'https'})
        self.assertNotIn('Secure', plain)
        self.assertIn('; Secure', tls)
        self.assertIn('HttpOnly', tls)


if __name__ == '__main__':
    unittest.main()
