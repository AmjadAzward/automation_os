"""Per-category approval limits, write rate limiting, backup permissions and settings restore."""
import http.client
import json
import os
import stat
import threading
import unittest
from http.server import ThreadingHTTPServer

from test_app import AppTestCase


class CategoryLimitTests(AppTestCase):
    def file(self, **over):
        row = {'title': 'T', 'requester': 'ann', 'approver': 'bob', 'amount': '150', 'category': 'Purchase'}
        row.update(over)
        return self.app.add_row('approvals', row)['id']

    def test_a_category_limit_applies_only_to_that_category(self):
        self.app.save_automation_settings({'category_thresholds': {'Purchase': 100}})
        with self.assertRaises(ValueError) as ctx:
            self.file()
        self.assertIn('Purchase', str(ctx.exception))
        self.assertIn('second approver', str(ctx.exception))
        self.file(category='Operational')                          # no general limit, so nothing required
        self.file(second_approver='cyd')                           # satisfied by naming one

    def test_a_category_limit_overrides_the_general_one_in_both_directions(self):
        self.app.save_automation_settings({'second_approval_threshold': 1000, 'category_thresholds': {'Payment': 50, 'Contract': 0}})
        with self.assertRaises(ValueError):
            self.file(category='Payment', amount='60')             # stricter than the general limit
        self.file(category='Contract', amount='99999')             # 0 switches the rule off for this category
        with self.assertRaises(ValueError):
            self.file(category='Other', amount='1000')             # falls back to the general limit

    def test_editing_is_held_to_the_same_rule(self):
        self.app.save_automation_settings({'category_thresholds': {'Purchase': 100}})
        rid = self.file(amount='50')
        with self.assertRaises(ValueError):
            self.app.update_row('approvals', rid, {'amount': '500'})
        self.app.update_row('approvals', rid, {'amount': '500', 'second_approver': 'cyd'})

    def test_validation_and_cleaning(self):
        for bad in ({'Nonsense': 5}, {'Purchase': 'lots'}, ['x'], 'not json'):
            with self.assertRaises(ValueError):
                self.app.save_automation_settings({'category_thresholds': bad})
        self.app.save_automation_settings({'category_thresholds': {'Purchase': '2500.9', 'Payment': '', 'Other': None, 'Contract': -4}})
        self.assertEqual(self.app.automation_settings()['category_thresholds'], {'Purchase': 2500, 'Contract': 0})

    def test_accepts_json_text_and_clears(self):
        self.app.save_automation_settings({'category_thresholds': '{"Purchase": 10}'})
        self.assertEqual(self.app.automation_settings()['category_thresholds'], {'Purchase': 10})
        self.app.save_automation_settings({'category_thresholds': {}})
        self.assertEqual(self.app.automation_settings()['category_thresholds'], {})

    def test_digest_settings_are_clamped(self):
        self.app.save_automation_settings({'digest_hour': 99, 'digest_enabled': True})
        settings = self.app.automation_settings()
        self.assertEqual((settings['digest_hour'], settings['digest_enabled']), (23, True))
        self.app.save_automation_settings({'digest_hour': -3})
        self.assertEqual(self.app.automation_settings()['digest_hour'], 0)


class SettingsRestoreTests(AppTestCase):
    def test_settings_come_back_with_a_backup(self):
        self.app.save_automation_settings({'due_days': 30, 'approval_escalate_days': 9, 'category_thresholds': {'Purchase': 700}, 'task_rule': False})
        backup = self.app.backup_export()
        self.app.save_automation_settings({'due_days': 5, 'approval_escalate_days': 1, 'category_thresholds': {}, 'task_rule': True})
        result = self.app.restore_backup(backup)
        settings = self.app.automation_settings()
        self.assertEqual((settings['due_days'], settings['approval_escalate_days'], settings['task_rule']), (30, 9, False))
        self.assertEqual(settings['category_thresholds'], {'Purchase': 700})
        self.assertGreaterEqual(result['settings_restored'], 4)

    def test_unknown_and_invalid_settings_never_block_the_data(self):
        self.app.add_row('tasks', {'title': 'Keep me'})
        backup = self.app.backup_export()
        backup['settings'].update({'bogus_key': 1, 'due_days': 'abc', 'category_thresholds': {'Nope': 1}})
        result = self.app.restore_backup(backup)
        self.assertEqual(len(self.app.read_table('tasks')), 1)
        self.assertIn('due_days', result['settings_skipped'])
        self.assertIn('category_thresholds', result['settings_skipped'])
        self.assertNotIn('bogus_key', result['settings_skipped'])
        self.assertEqual(self.app.automation_settings()['due_days'], 14)       # untouched

    def test_old_backups_without_settings_still_restore(self):
        backup = self.app.backup_export()
        backup.pop('settings')
        self.assertEqual(self.app.restore_backup(backup)['settings_restored'], 0)


class BackupPermissionTests(AppTestCase):
    @unittest.skipIf(os.name == 'nt', 'POSIX permission bits do not apply on Windows')
    def test_backups_are_owner_only(self):
        name = self.app.auto_backup(force=True)
        mode = stat.S_IMODE(os.stat(self.app.config.BACKUP_DIR / name).st_mode)
        self.assertEqual(mode, 0o600)
        self.assertEqual(stat.S_IMODE(os.stat(self.app.config.BACKUP_DIR).st_mode), 0o700)

    def test_backup_still_works_when_permissions_cannot_be_changed(self):
        self.assertTrue(self.app.auto_backup(force=True))


class WriteRateLimitTests(AppTestCase):
    def setUp(self):
        super().setUp()
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), self.app.Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        super().tearDown()

    def call(self, method, path, body=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)
        conn.request(method, path, body=json.dumps(body) if body is not None else None,
                     headers={'Host': f'127.0.0.1:{self.port}', 'Content-Type': 'application/json'})
        r = conn.getresponse()
        r.read()
        retry = r.getheader('Retry-After')
        conn.close()
        return r.status, retry

    def test_a_flood_of_changes_is_refused_but_reading_is_not(self):
        self.app.config.WRITE_LIMIT = 4
        statuses = [self.call('POST', '/api/tasks', {'title': f'T{i}'})[0] for i in range(6)]
        self.assertEqual(statuses, [200, 200, 200, 200, 429, 429])
        status, retry = self.call('POST', '/api/tasks', {'title': 'x'})
        self.assertEqual((status, retry), (429, '30'))
        self.assertEqual(self.call('GET', '/api/tasks')[0], 200)
        self.assertEqual(len(self.app.read_table('tasks')), 4)

    def test_zero_turns_the_limit_off(self):
        self.app.config.WRITE_LIMIT = 0
        self.assertTrue(all(self.call('POST', '/api/tasks', {'title': 'x'})[0] == 200 for _ in range(8)))

    def test_window_slides(self):
        self.app.config.WRITE_LIMIT = 2
        key = ('1.2.3.4', '')
        server = importlib_server(self.app)
        self.assertTrue(server.allow_write(key) and server.allow_write(key))
        self.assertFalse(server.allow_write(key))
        server._WRITES[key] = [t - 61 for t in server._WRITES[key]]      # a minute later
        self.assertTrue(server.allow_write(key))

    def test_clients_are_counted_separately(self):
        self.app.config.WRITE_LIMIT = 1
        server = importlib_server(self.app)
        self.assertTrue(server.allow_write(('1.1.1.1', 'a')))
        self.assertTrue(server.allow_write(('1.1.1.1', 'b')))
        self.assertTrue(server.allow_write(('2.2.2.2', 'a')))
        self.assertFalse(server.allow_write(('1.1.1.1', 'a')))


def importlib_server(app):
    import sys
    return sys.modules['aos.server']


if __name__ == '__main__':
    unittest.main()
