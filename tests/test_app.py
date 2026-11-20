"""Backend tests. Run from the project folder with:  python -m unittest discover -s tests -v

Each test uses its own temporary SQLite file, so real data is never touched.
"""
import base64
import gc
import http.client
import importlib
import json
import threading
import os
import sys
import tempfile
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def load_app():
    """Import a fresh copy of `app` and the whole `aos` package (config is read once, at import)."""
    for name in [m for m in sys.modules if m == 'app' or m == 'aos' or m.startswith('aos.')]:
        del sys.modules[name]
    return importlib.import_module('app')


def unload_app():
    for name in [m for m in sys.modules if m == 'app' or m == 'aos' or m.startswith('aos.')]:
        del sys.modules[name]


class AppTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        os.environ['AUTOMATION_DB'] = str(Path(self.tmp.name) / 'test.sqlite3')
        self.app = load_app()
        self.app.init()

    def tearDown(self):
        unload_app()
        gc.collect()  # release SQLite handles so Windows can delete the file
        self.tmp.cleanup()

    def approval(self, **over):
        row = {'title': 'Buy laptops', 'requester': 'Ann', 'approver': 'Bob', 'amount': '1,200'}
        row.update(over)
        return self.app.add_row('approvals', row)['id']


class ApprovalTests(AppTestCase):
    def test_defaults_are_applied(self):
        self.approval(amount='', currency='', category='')
        row = self.app.read_table('approvals')[0]
        self.assertEqual((row['amount'], row['currency'], row['category'], row['status']), ('0', 'USD', 'Operational', 'pending'))

    def test_amount_is_normalised(self):
        self.approval()
        self.assertEqual(self.app.read_table('approvals')[0]['amount'], '1200')

    def test_invalid_amount_rejected(self):
        with self.assertRaises(ValueError):
            self.approval(amount='abc')

    def test_requester_cannot_be_approver(self):
        with self.assertRaises(ValueError):
            self.approval(requester='Ann', approver=' ann ')

    def test_decision_is_final(self):
        ident = self.approval()
        self.assertEqual(self.app.decide_approval(ident, 'approved', 'ok')['status'], 'approved')
        with self.assertRaises(ValueError):
            self.app.decide_approval(ident, 'rejected')
        with self.assertRaises(ValueError):
            self.app.update_row('approvals', ident, {'title': 'changed'})

    def test_bad_decision_and_missing_request(self):
        ident = self.approval()
        with self.assertRaises(ValueError):
            self.app.decide_approval(ident, 'maybe')
        with self.assertRaises(ValueError):
            self.app.decide_approval(9999, 'approved')

    def test_edit_pending_request(self):
        ident = self.approval()
        self.app.update_row('approvals', ident, {'amount': '5,000', 'title': 'Buy monitors'})
        row = self.app.read_table('approvals')[0]
        self.assertEqual((row['amount'], row['title']), ('5000', 'Buy monitors'))

    def test_overview_counts_pending_only(self):
        a, _ = self.approval(), self.approval(title='Second')
        self.app.decide_approval(a, 'approved')
        self.assertEqual(self.app.overview()['pending_approvals'], 1)

    def test_csv_import(self):
        result = self.app.import_csv('approvals', 'title,requester,approver,amount\nA,X,Y,10\nB,X,X,1\n')
        self.assertEqual((result['inserted'], result['failed']), (1, 1))


class BackupTests(AppTestCase):
    def test_restore_round_trip(self):
        self.app.add_row('tasks', {'title': 'Keep me', 'due_date': '2026-01-01'})
        self.approval()
        backup = self.app.backup_export()
        self.app.delete_row('tasks', self.app.read_table('tasks')[0]['id'])
        self.assertEqual(self.app.read_table('tasks'), [])
        result = self.app.restore_backup(backup)
        self.assertEqual(result['restored']['tasks'], 1)
        self.assertEqual(self.app.read_table('tasks')[0]['title'], 'Keep me')
        self.assertEqual(len(self.app.read_table('approvals')), 1)

    def test_rejects_foreign_files(self):
        for bad in ({}, {'format': 'other'}, {'format': 'automation-os-backup', 'data': []}, 'text'):
            with self.assertRaises(ValueError):
                self.app.restore_backup(bad)

    def test_malformed_table_leaves_data_untouched(self):
        self.app.add_row('tasks', {'title': 'Keep me'})
        with self.assertRaises(ValueError):
            self.app.restore_backup({'format': 'automation-os-backup', 'data': {'tasks': 'nope'}})
        self.assertEqual(len(self.app.read_table('tasks')), 1)

    def test_unknown_columns_are_ignored(self):
        backup = {'format': 'automation-os-backup', 'data': {'tasks': [{'title': 'X', 'created_at': '2026-01-01', 'evil; DROP TABLE tasks': 1}]}}
        self.app.restore_backup(backup)
        self.assertEqual(self.app.read_table('tasks')[0]['title'], 'X')


    def test_invalid_row_rolls_back_cleanly(self):
        self.app.add_row('tasks', {'title': 'Keep me'})
        bad = {'format': 'automation-os-backup', 'data': {'tasks': [{'title': 'no created_at'}]}}
        with self.assertRaises(ValueError) as ctx:
            self.app.restore_backup(bad)
        self.assertIn('nothing was changed', str(ctx.exception))
        self.assertEqual(self.app.read_table('tasks')[0]['title'], 'Keep me')


class GeneralTests(AppTestCase):
    def test_resource_whitelist(self):
        with self.assertRaises(ValueError):
            self.app.read_table('sqlite_master')
        with self.assertRaises(ValueError):
            self.app.add_row('settings', {'key': 'x'})

    def test_task_status_validation(self):
        with self.assertRaises(ValueError):
            self.app.add_row('tasks', {'title': 'T', 'status': 'bogus'})

    def test_revenue_leakage_detected(self):
        self.app.add_row('tariffs', {'service': 'STORE', 'rate': '120', 'currency': 'USD'})
        self.app.add_row('transactions', {'ref': 'INV-1', 'service': 'STORE', 'customer': 'Acme', 'billed': '90', 'currency': 'USD'})
        self.app.scan()
        kinds = [e['kind'] for e in self.app.read_table('exceptions')]
        self.assertIn('revenue_leakage', kinds)


class BackupFileTests(AppTestCase):
    def test_backup_created_once_per_day_and_listed(self):
        self.app.add_row('tasks', {'title': 'T'})
        self.assertTrue(self.app.auto_backup())
        self.assertIsNone(self.app.auto_backup())
        self.assertEqual(len(self.app.list_backups()), 1)

    def test_retention_keeps_newest(self):
        self.app.config.BACKUP_KEEP = 3
        for i in range(6):
            (self.app.BACKUP_DIR).mkdir(parents=True, exist_ok=True)
            p = self.app.BACKUP_DIR / f'backup-2026-01-0{i + 1}.json'
            p.write_text('{}')
            os.utime(p, (1000 + i, 1000 + i))
        self.app.auto_backup(force=True)
        self.assertEqual(len(self.app.list_backups()), 3)

    def test_restore_from_stored_backup(self):
        self.app.add_row('tasks', {'title': 'Original'})
        name = self.app.auto_backup(force=True)
        self.app.delete_row('tasks', self.app.read_table('tasks')[0]['id'])
        self.app.restore_stored_backup(name)
        self.assertEqual(self.app.read_table('tasks')[0]['title'], 'Original')

    def test_stored_backup_name_is_validated(self):
        for bad in ('../app.py', 'backup-1.json/../../x', 'evil.json', '', None, 'backup-1.json'):
            with self.assertRaises(ValueError):
                self.app.restore_stored_backup(bad)


class SearchTests(AppTestCase):
    def test_finds_across_tables_and_escapes_wildcards(self):
        self.app.add_row('tasks', {'title': 'Renew insurance'})
        self.approval(title='Insurance for forklift')
        self.app.add_row('tasks', {'title': '100% done'})
        found = self.app.search('insurance')
        self.assertEqual({r['table'] for r in found}, {'tasks', 'approvals'})
        self.assertEqual(self.app.search('%%'), [])  # wildcards are literal, not match-all
        self.assertEqual([r['title'] for r in self.app.search('100%')], ['100% done'])
        self.assertEqual(self.app.search('a'), [])
        self.assertEqual(self.app.search('x' * 101), [])


class HttpGuardTests(AppTestCase):
    def setUp(self):
        super().setUp()
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), self.app.Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        super().tearDown()

    def call(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)
        h = {'Host': f'127.0.0.1:{self.port}'}
        h.update(headers or {})
        conn.request(method, path, body=body, headers=h)
        r = conn.getresponse()
        data = r.read()
        conn.close()
        return r.status, data

    def post_task(self, headers):
        return self.call('POST', '/api/tasks', json.dumps({'title': 'T'}), headers)[0]

    def test_normal_json_write_works(self):
        self.assertEqual(self.post_task({'Content-Type': 'application/json'}), 200)

    def test_same_origin_write_works(self):
        self.assertEqual(self.post_task({'Content-Type': 'application/json', 'Origin': f'http://127.0.0.1:{self.port}'}), 200)

    def test_cross_site_write_blocked(self):
        self.assertEqual(self.post_task({'Content-Type': 'application/json', 'Origin': 'http://evil.example'}), 403)
        self.assertEqual(self.app.read_table('tasks'), [])

    def test_text_plain_form_style_write_blocked(self):
        self.assertEqual(self.post_task({'Content-Type': 'text/plain'}), 415)
        self.assertEqual(self.app.read_table('tasks'), [])

    def test_foreign_host_header_blocked(self):
        self.assertEqual(self.call('GET', '/api/health', headers={'Host': 'evil.example'})[0], 403)

    def test_password_protection(self):
        self.app.config.AUTH = 'secret'
        try:
            self.assertEqual(self.call('GET', '/api/health')[0], 401)
            wrong = base64.b64encode(b'user:nope').decode()
            self.assertEqual(self.call('GET', '/api/health', headers={'Authorization': 'Basic ' + wrong})[0], 401)
            good = base64.b64encode(b'anyone:secret').decode()
            self.assertEqual(self.call('GET', '/api/health', headers={'Authorization': 'Basic ' + good})[0], 200)
        finally:
            self.app.config.AUTH = ''

    def test_search_and_backup_endpoints(self):
        self.app.add_row('tasks', {'title': 'Findable'})
        status, data = self.call('GET', '/api/search?q=find')
        self.assertEqual((status, json.loads(data)[0]['title']), (200, 'Findable'))
        status, data = self.call('POST', '/api/backups', '{}', {'Content-Type': 'application/json'})
        self.assertEqual(status, 200)
        self.assertEqual(len(json.loads(self.call('GET', '/api/backups')[1])), 1)


if __name__ == '__main__':
    unittest.main()
