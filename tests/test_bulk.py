"""Bulk status changes and bulk deletes."""
import http.client
import json
import threading
import unittest
from http.server import ThreadingHTTPServer

from test_app import AppTestCase

PW = 'correct-horse-battery'


class BulkActionTests(AppTestCase):
    def tasks(self, n=3):
        return [self.app.add_row('tasks', {'title': f'T{i}'})['id'] for i in range(n)]

    def statuses(self, table='tasks'):
        return {r['title' if table == 'tasks' else 'id']: r['status'] for r in self.app.read_table(table)}

    def test_bulk_status_changes_only_the_selected_records(self):
        a, b, c = self.tasks()
        result = self.app.bulk_action('tasks', [a, b], 'status', 'done')
        self.assertEqual(result['affected'], 2)
        self.assertEqual(self.statuses(), {'T0': 'done', 'T1': 'done', 'T2': 'open'})

    def test_bulk_status_on_contracts_and_exceptions(self):
        self.app.add_row('contracts', {'contract': 'C', 'obligation': 'O', 'due_date': '2026-01-01'})
        self.assertEqual(self.app.bulk_action('contracts', [1], 'status', 'blocked')['affected'], 1)
        self.assertEqual(self.app.read_table('contracts')[0]['status'], 'blocked')

    def test_bulk_delete(self):
        a, b, c = self.tasks()
        self.assertEqual(self.app.bulk_action('tasks', [a, c], 'delete')['affected'], 2)
        self.assertEqual([r['title'] for r in self.app.read_table('tasks')], ['T1'])

    def test_bulk_delete_works_for_the_other_record_types(self):
        self.app.add_row('tariffs', {'service': 'S', 'rate': '1'})
        self.app.add_row('quotations', {'rfq': 'R', 'supplier': 'S', 'item': 'I', 'unit_price': '1'})
        self.assertEqual(self.app.bulk_action('tariffs', [1], 'delete')['affected'], 1)
        self.assertEqual(self.app.bulk_action('quotations', [1], 'delete')['affected'], 1)

    def test_approvals_and_other_tables_are_off_limits(self):
        rid = self.app.add_row('approvals', {'title': 'T', 'requester': 'a', 'approver': 'b'})['id']
        for table in ('approvals', 'audit', 'users', 'settings', 'sqlite_master'):
            with self.assertRaises(ValueError):
                self.app.bulk_action(table, [rid], 'delete')
        for table in ('approvals', 'quotations', 'tariffs'):
            with self.assertRaises(ValueError):
                self.app.bulk_action(table, [rid], 'status', 'done')
        self.assertEqual(len(self.app.read_table('approvals')), 1)

    def test_validation(self):
        ids = self.tasks()
        for bad in ([], None, 'abc', list(range(201)), ['x'], [None]):
            with self.assertRaises(ValueError):
                self.app.bulk_action('tasks', bad, 'delete')
        with self.assertRaises(ValueError):
            self.app.bulk_action('tasks', ids, 'status', 'bogus')
        with self.assertRaises(ValueError):
            self.app.bulk_action('tasks', ids, 'explode')
        self.assertEqual(len(self.app.read_table('tasks')), 3)

    def test_ids_are_never_interpolated_into_sql(self):
        self.tasks()
        with self.assertRaises(ValueError):
            self.app.bulk_action('tasks', ['1 OR 1=1'], 'delete')
        with self.assertRaises(ValueError):
            self.app.bulk_action('tasks; DROP TABLE tasks', [1], 'delete')
        self.assertEqual(len(self.app.read_table('tasks')), 3)

    def test_duplicates_are_collapsed_and_unknown_ids_ignored(self):
        a = self.tasks(1)[0]
        self.assertEqual(self.app.bulk_action('tasks', [a, a, 999], 'status', 'blocked')['affected'], 1)

    def test_one_audit_entry_lists_everything(self):
        a, b, _ = self.tasks()
        self.app.bulk_action('tasks', [a, b], 'status', 'done')
        entry = next(e for e in self.app.read_table('audit') if e['action'] == 'bulk_status')
        details = json.loads(entry['details'])
        self.assertEqual((details['ids'], details['affected'], details['status']), ([a, b], 2, 'done'))


class HttpBulkTests(AppTestCase):
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

    def test_single_user_mode_allows_everything(self):
        self.app.add_row('tasks', {'title': 'T'})
        self.assertEqual(self.call('POST', '/api/bulk', {'table': 'tasks', 'ids': [1], 'action': 'delete'})[0], 200)

    def test_roles_over_http(self):
        self.call('POST', '/api/auth/setup', {'username': 'boss', 'password': PW})
        cookies = {}
        for name, role in (('boss', 'admin'), ('man', 'manager'), ('mem', 'member'), ('vic', 'viewer')):
            if name != 'boss':
                self.call('POST', '/api/users', {'username': name, 'role': role, 'password': PW}, cookies['boss'])
            _, _, cookie = self.call('POST', '/api/auth/login', {'username': name, 'password': PW})
            cookies[name] = cookie.split(';')[0]
        for i in range(4):
            self.app.add_row('tasks', {'title': f'T{i}'})
        bulk = lambda who, action, ids, status=None: self.call('POST', '/api/bulk', {'table': 'tasks', 'ids': ids, 'action': action, 'status': status}, cookies[who])[0]
        self.assertEqual(bulk('vic', 'status', [1], 'done'), 403)       # read-only
        self.assertEqual(bulk('mem', 'status', [1], 'done'), 200)       # members can move work along
        self.assertEqual(bulk('mem', 'delete', [2]), 403)               # but not delete
        self.assertEqual(bulk('man', 'delete', [2]), 200)               # managers can
        self.assertEqual(bulk('boss', 'delete', [3]), 200)
        self.assertEqual(len(self.app.read_table('tasks')), 2)
        self.assertEqual(self.call('POST', '/api/bulk', {'table': 'tasks', 'ids': [1], 'action': 'delete'})[0], 401)


if __name__ == '__main__':
    unittest.main()
