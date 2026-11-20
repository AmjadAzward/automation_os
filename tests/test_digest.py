"""The daily digest: content, outbox, optional email, scheduling and profile settings."""
import http.client
import json
import os
import smtplib
import sqlite3
import threading
import unittest
from datetime import datetime, timedelta
from http.server import ThreadingHTTPServer
from unittest import mock

from test_app import AppTestCase

PW = 'correct-horse-battery'


class DigestMixin:
    def user(self, username, role='member', name=None):
        self.app.create_user({'username': username, 'display_name': name or username.title(), 'role': role, 'password': PW})
        return next(u for u in self.app.list_users() if u['username'] == username)

    def reload(self, user):
        return next(u for u in self.app.list_users() if u['id'] == user['id'])

    def profile(self, user, email='', digest=True):
        return self.app.set_profile(self.app.session_user(self.app.start_session(user['id'])), email, digest)

    def enable_smtp(self):
        c = self.app.config
        c.SMTP_HOST, c.SMTP_PORT, c.SMTP_FROM, c.SMTP_USER, c.SMTP_PASSWORD, c.SMTP_SECURITY = 'mail.example.test', 587, 'ops@example.test', 'mailer', 's3cret', 'starttls'


class BuildTests(DigestMixin, AppTestCase):
    def setUp(self):
        super().setUp()
        self.ann, self.bob = self.user('ann', name='Ann Lee'), self.user('bob')

    def test_nothing_to_report(self):
        digest = self.app.build_digest(self.ann)
        self.assertEqual(digest['count'], 0)
        self.assertIn('nothing needs you', digest['subject'])

    def test_lists_what_needs_the_person_grouped_by_urgency(self):
        self.app.add_row('approvals', self.app.prepare_approval_payload({'title': 'Crane', 'approver': 'bob'}, self.ann))
        yesterday = (datetime.now().date() - timedelta(days=1)).isoformat()
        self.app.add_row('tasks', {'title': 'Pay rent', 'owner': 'bob', 'due_date': yesterday})
        digest = self.app.build_digest(self.bob)
        self.assertEqual(digest['count'], 2)
        self.assertIn('2 items need your attention', digest['subject'])
        self.assertIn('Hi Bob,', digest['body'])
        self.assertIn('URGENT', digest['body'])
        self.assertIn('Pay rent: Overdue by 1 day', digest['body'])
        self.assertIn('Crane: Waiting for your decision', digest['body'])
        self.assertIn(self.app.config.PUBLIC_URL, digest['body'])
        self.assertLess(digest['body'].index('URGENT'), digest['body'].index('NEEDS ATTENTION'))

    def test_wording_for_a_single_item(self):
        self.app.add_row('tasks', {'title': 'Solo', 'owner': 'ann', 'due_date': '2000-01-01'})
        self.assertIn('1 item needs your attention', self.app.build_digest(self.ann)['subject'])

    def test_other_peoples_items_never_appear(self):
        self.app.add_row('tasks', {'title': 'Bobs private task', 'owner': 'bob', 'due_date': '2000-01-01'})
        self.assertNotIn('Bobs private task', self.app.build_digest(self.ann)['body'])

    def test_single_user_mode_still_previews(self):
        self.app.add_row('tasks', {'title': 'Late', 'due_date': '2000-01-01'})
        self.assertEqual(self.app.build_digest({'id': 0, 'username': 'local', 'display_name': 'Local user', 'role': 'admin', 'open': True})['count'], 1)


class DeliveryTests(DigestMixin, AppTestCase):
    def setUp(self):
        super().setUp()
        self.ann = self.user('ann')
        self.digest = {'count': 1, 'subject': 'Subject line', 'body': 'Body text\n'}

    def outbox(self):
        folder = self.app.config.OUTBOX_DIR
        return sorted(p.name for p in folder.glob('digest-*.txt')) if folder.exists() else []

    def test_without_smtp_it_is_only_saved(self):
        result = self.app.deliver(self.reload(self.ann), self.digest)
        self.assertFalse(result['emailed'])
        self.assertIn('not set up', result['reason'])
        text = (self.app.config.OUTBOX_DIR / result['written']).read_text(encoding='utf-8')
        self.assertTrue(text.startswith('To: (no email address)\nSubject: Subject line\n\nBody text'))

    def test_smtp_without_an_address_explains_itself(self):
        self.enable_smtp()
        with mock.patch('aos.digest.smtplib.SMTP') as smtp:
            result = self.app.deliver(self.reload(self.ann), self.digest)
        smtp.assert_not_called()
        self.assertIn('not added an email address', result['reason'])

    def test_email_is_sent_securely(self):
        self.enable_smtp()
        self.profile(self.ann, 'ann@example.test')
        with mock.patch('aos.digest.smtplib.SMTP') as smtp:
            result = self.app.deliver(self.reload(self.ann), self.digest)
        self.assertEqual((result['emailed'], result['reason']), (True, ''))
        smtp.assert_called_once_with('mail.example.test', 587, timeout=20)
        client = smtp.return_value
        client.starttls.assert_called_once()
        client.login.assert_called_once_with('mailer', 's3cret')
        sent = client.send_message.call_args[0][0]
        self.assertEqual((sent['To'], sent['From'], sent['Subject']), ('ann@example.test', 'ops@example.test', 'Subject line'))

    def test_implicit_tls_and_no_login_options(self):
        self.enable_smtp()
        self.app.config.SMTP_SECURITY, self.app.config.SMTP_USER = 'ssl', ''
        self.profile(self.ann, 'ann@example.test')
        with mock.patch('aos.digest.smtplib.SMTP_SSL') as smtp_ssl:
            self.assertTrue(self.app.deliver(self.reload(self.ann), self.digest)['emailed'])
        client = smtp_ssl.return_value
        client.login.assert_not_called()
        client.starttls.assert_not_called()

    def test_a_failure_is_reported_logged_without_details_and_the_outbox_copy_survives(self):
        self.enable_smtp()
        self.profile(self.ann, 'ann@example.test')
        with mock.patch('aos.digest.smtplib.SMTP', side_effect=smtplib.SMTPAuthenticationError(535, b'bad password for mailer on mail.example.test')):
            result = self.app.deliver(self.reload(self.ann), self.digest)
        self.assertFalse(result['emailed'])
        self.assertIn('could not be sent', result['reason'])
        self.assertEqual(len(self.outbox()), 1)
        audit = json.dumps(self.app.read_table('audit'))
        self.assertIn('digest_failed', audit)
        self.assertIn('SMTPAuthenticationError', audit)
        self.assertNotIn('bad password', audit)
        self.assertNotIn('s3cret', audit)
        self.assertNotIn('ann@example.test', audit)

    def test_network_errors_do_not_crash_the_caller(self):
        self.enable_smtp()
        self.profile(self.ann, 'ann@example.test')
        with mock.patch('aos.digest.smtplib.SMTP', side_effect=OSError('network down')):
            self.assertFalse(self.app.deliver(self.reload(self.ann), self.digest)['emailed'])

    def test_header_injection_is_refused(self):
        self.enable_smtp()
        with sqlite3.connect(self.app.DB) as c:                         # bypass validation to prove the second line of defence
            c.execute("UPDATE users SET email='a@example.test\nBcc: victim@example.test' WHERE id=?", (self.ann['id'],))
        with mock.patch('aos.digest.smtplib.SMTP') as smtp:
            result = self.app.deliver(self.reload(self.ann), self.digest)
        self.assertFalse(result['emailed'])
        smtp.return_value.send_message.assert_not_called()

    def test_outbox_keeps_only_the_newest_500(self):
        folder = self.app.config.OUTBOX_DIR
        folder.mkdir(parents=True)
        for i in range(505):
            path = folder / f'digest-old-{i:04d}.txt'
            path.write_text('x')
            os.utime(path, (1000 + i, 1000 + i))
        self.app.write_outbox(self.reload(self.ann), self.digest)
        self.assertEqual(len(self.outbox()), 500)

    def test_unsafe_usernames_cannot_escape_the_folder(self):
        name = self.app.write_outbox({'username': '../../evil', 'email': ''}, self.digest)
        self.assertNotIn('/', name)
        self.assertNotIn('\\', name)
        self.assertTrue((self.app.config.OUTBOX_DIR / name).exists())


class ScheduleTests(DigestMixin, AppTestCase):
    def setUp(self):
        super().setUp()
        self.ann, self.bob, self.cyd = self.user('ann'), self.user('bob'), self.user('cyd')
        self.app.add_row('tasks', {'title': 'Ann task', 'owner': 'ann', 'due_date': '2000-01-01'})
        self.app.add_row('tasks', {'title': 'Bob task', 'owner': 'bob', 'due_date': '2000-01-01'})
        self.at = datetime(2026, 6, 1, 9, 30)

    def test_off_by_default_even_for_people_who_opted_in(self):
        self.profile(self.ann)
        self.assertEqual(self.app.run_digests(self.at), [])
        self.assertEqual(self.app.config.OUTBOX_DIR.exists(), False)

    def test_only_opted_in_active_people_after_the_chosen_hour(self):
        self.app.save_automation_settings({'digest_enabled': True, 'digest_hour': 8})
        self.profile(self.ann)
        self.profile(self.cyd)                                         # opted in but has nothing to report
        self.assertEqual(self.app.run_digests(self.at.replace(hour=7)), [])
        sent = self.app.run_digests(self.at)
        self.assertEqual([s['user'] for s in sent], ['ann'])           # bob never opted in; cyd has nothing

    def test_once_a_day_per_person(self):
        self.app.save_automation_settings({'digest_enabled': True, 'digest_hour': 8})
        self.profile(self.ann)
        self.assertEqual(len(self.app.run_digests(self.at)), 1)
        self.assertEqual(self.app.run_digests(self.at + timedelta(hours=3)), [])
        self.assertEqual(len(self.app.run_digests(self.at + timedelta(days=1))), 1)

    def test_a_quiet_day_is_marked_sent_so_it_is_not_retried_all_day(self):
        self.app.save_automation_settings({'digest_enabled': True, 'digest_hour': 0})
        self.profile(self.cyd)
        self.assertEqual(self.app.run_digests(self.at), [])
        self.app.add_row('tasks', {'title': 'Late arrival', 'owner': 'cyd', 'due_date': '2000-01-01'})
        self.assertEqual(self.app.run_digests(self.at + timedelta(hours=2)), [])      # already handled today

    def test_disabled_accounts_are_skipped(self):
        self.app.save_automation_settings({'digest_enabled': True, 'digest_hour': 0})
        self.profile(self.ann)
        self.user('boss', 'admin')
        self.app.update_user(self.ann['id'], {'active': False})
        self.assertEqual(self.app.run_digests(self.at), [])

    def test_emails_go_out_when_configured(self):
        self.enable_smtp()
        self.app.save_automation_settings({'digest_enabled': True, 'digest_hour': 0})
        self.profile(self.ann, 'ann@example.test')
        with mock.patch('aos.digest.smtplib.SMTP') as smtp:
            sent = self.app.run_digests(self.at)
        self.assertEqual((sent[0]['emailed'], smtp.return_value.send_message.call_count), (True, 1))

    def test_one_failure_does_not_stop_the_others(self):
        self.enable_smtp()
        self.app.save_automation_settings({'digest_enabled': True, 'digest_hour': 0})
        self.profile(self.ann, 'ann@example.test')
        self.profile(self.bob, 'bob@example.test')
        with mock.patch('aos.digest.smtplib.SMTP', side_effect=OSError('down')):
            sent = self.app.run_digests(self.at)
        self.assertEqual(sorted(s['user'] for s in sent), ['ann', 'bob'])
        self.assertTrue(all(not s['emailed'] for s in sent))


class ProfileTests(DigestMixin, AppTestCase):
    def setUp(self):
        super().setUp()
        self.ann = self.user('ann')

    def test_set_and_clear(self):
        result = self.profile(self.ann, 'ann@example.test', True)
        self.assertEqual((result['email'], result['digest_optin']), ('ann@example.test', True))
        result = self.profile(self.ann, '', False)
        self.assertEqual((result['email'], result['digest_optin']), ('', False))

    def test_validation(self):
        for bad in ('plainaddress', 'a@b', '@example.test', 'two words@example.test', 'a@example.test\nBcc: x@y.test', 'x' * 130 + '@example.test'):
            with self.assertRaises(ValueError, msg=bad[:30]):
                self.profile(self.ann, bad)

    def test_the_address_is_not_written_to_the_audit_log(self):
        self.profile(self.ann, 'private@example.test')
        self.assertNotIn('private@example.test', json.dumps(self.app.read_table('audit')))

    def test_admin_can_set_someone_elses_address_with_the_same_checks(self):
        self.app.update_user(self.ann['id'], {'email': 'ann@example.test'})
        self.assertEqual(self.reload(self.ann)['email'], 'ann@example.test')
        with self.assertRaises(ValueError):
            self.app.update_user(self.ann['id'], {'email': 'nope'})

    def test_single_user_mode_has_no_profile(self):
        with self.assertRaises(ValueError):
            self.app.set_profile({'id': 0, 'username': 'local', 'role': 'admin', 'open': True}, 'a@example.test', True)

    def test_old_databases_gain_the_columns(self):
        from test_app import load_app
        old = os.path.join(self.tmp.name, 'old.sqlite3')
        with sqlite3.connect(old) as c:
            c.executescript("CREATE TABLE users(id INTEGER PRIMARY KEY AUTOINCREMENT,username TEXT NOT NULL UNIQUE COLLATE NOCASE,display_name TEXT NOT NULL,role TEXT NOT NULL DEFAULT 'member',password_hash TEXT NOT NULL,active INTEGER NOT NULL DEFAULT 1,created_at TEXT NOT NULL);INSERT INTO users(username,display_name,password_hash,created_at) VALUES('ann','Ann','x','2026-01-01');")
        os.environ['AUTOMATION_DB'] = old
        app = load_app()
        app.init()
        app.init()
        user = app.list_users()[0]
        self.assertEqual((user['email'], user['digest_optin'], user['digest_sent']), ('', False, ''))


class SafeDefaultsTests(AppTestCase):
    def test_nothing_is_configured_out_of_the_box(self):
        c = self.app.config
        self.assertEqual((c.SMTP_HOST, c.SMTP_PASSWORD, self.app.smtp_configured()), ('', '', False))
        self.assertEqual(self.app.automation_settings()['digest_enabled'], False)

    def test_an_unknown_security_mode_falls_back_to_starttls(self):
        os.environ['AUTOMATION_SMTP_SECURITY'] = 'plaintext-please'
        try:
            from test_app import load_app
            self.assertEqual(load_app().config.SMTP_SECURITY, 'starttls')
        finally:
            del os.environ['AUTOMATION_SMTP_SECURITY']

    def test_the_password_is_never_part_of_any_api_response(self):
        self.app.config.SMTP_PASSWORD = 'topsecret-smtp'
        blob = json.dumps([self.app.automation_settings(), self.app.backup_export(), self.app.list_users()])
        self.assertNotIn('topsecret-smtp', blob)


class HttpDigestTests(DigestMixin, AppTestCase):
    def setUp(self):
        super().setUp()
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), self.app.Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.call('POST', '/api/auth/setup', {'username': 'boss', 'password': PW})
        admin = self.login('boss')
        for n, role in (('ann', 'member'), ('vic', 'viewer')):
            self.call('POST', '/api/users', {'username': n, 'role': role, 'password': PW}, admin)
        self.admin, self.ann, self.vic = admin, self.login('ann'), self.login('vic')

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

    def test_profile_preview_and_test_send(self):
        status, user, _ = self.call('POST', '/api/auth/profile', {'email': 'ann@example.test', 'digest': True}, self.ann)
        self.assertEqual((status, user['email'], user['digest_optin']), (200, 'ann@example.test', True))
        self.assertEqual(self.call('GET', '/api/auth/me', cookie=self.ann)[1]['user']['email'], 'ann@example.test')
        self.app.add_row('tasks', {'title': 'Ann late', 'owner': 'ann', 'due_date': '2000-01-01'})
        self.assertIn('Ann late', self.call('GET', '/api/digest/preview', cookie=self.ann)[1]['body'])
        status, result, _ = self.call('POST', '/api/digest/test', {}, self.ann)
        self.assertEqual((status, result['emailed']), (200, False))
        self.assertTrue((self.app.config.OUTBOX_DIR / result['written']).exists())

    def test_viewers_can_manage_their_own_digest(self):
        self.assertEqual(self.call('POST', '/api/auth/profile', {'email': 'v@example.test', 'digest': True}, self.vic)[0], 200)
        self.assertEqual(self.call('POST', '/api/digest/test', {}, self.vic)[0], 200)
        self.assertEqual(self.call('POST', '/api/tasks', {'title': 'x'}, self.vic)[0], 403)        # still read-only elsewhere

    def test_bad_address_is_a_400_and_anonymous_is_refused(self):
        self.assertEqual(self.call('POST', '/api/auth/profile', {'email': 'nope'}, self.ann)[0], 400)
        self.assertEqual(self.call('POST', '/api/auth/profile', {'email': 'a@example.test'})[0], 401)
        self.assertEqual(self.call('GET', '/api/digest/preview')[0], 401)

    def test_status_never_reveals_server_credentials(self):
        self.enable_smtp()
        status, data, _ = self.call('GET', '/api/digest/status', cookie=self.ann)
        self.assertEqual((status, data), (200, {'enabled': False, 'hour': 8, 'smtp': True}))
        self.assertNotIn('s3cret', json.dumps(data))

    def test_admin_settings_control_the_schedule(self):
        status, data, _ = self.call('POST', '/api/automation/settings', {'digest_enabled': True, 'digest_hour': 6}, self.admin)
        self.assertEqual((status, data['digest_enabled'], data['digest_hour']), (200, True, 6))
        self.assertEqual(self.call('POST', '/api/automation/settings', {'digest_enabled': False}, self.ann)[0], 403)


if __name__ == '__main__':
    unittest.main()
