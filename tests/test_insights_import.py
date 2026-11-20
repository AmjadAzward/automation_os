"""Audit search, weekly trends, and CSV import preview with duplicate detection."""
import http.client
import json
import sqlite3
import threading
import unittest
from datetime import datetime, timedelta
from http.server import ThreadingHTTPServer

from test_app import AppTestCase


class AuditSearchTests(AppTestCase):
    def setUp(self):
        super().setUp()
        self.app.add_row('tasks', {'title': 'T1'})
        self.app.add_row('contracts', {'contract': 'C', 'obligation': 'O', 'due_date': '2026-01-01'})
        self.app.add_row('tasks', {'title': 'T2'})
        with sqlite3.connect(self.app.DB) as c:
            c.execute("UPDATE audit SET actor='ann' WHERE id=1")
            c.execute("UPDATE audit SET actor='bob' WHERE id=2")
            c.execute("UPDATE audit SET at='2026-03-05T10:00:00+00:00' WHERE id=1")
            c.execute("UPDATE audit SET at='2026-03-20T10:00:00+00:00' WHERE id=2")

    def ids(self, **kw):
        return [r['id'] for r in self.app.audit_query(**kw)]

    def test_filters_combine(self):
        self.assertEqual(self.ids(actor='ann'), [1])
        self.assertEqual(self.ids(entity='tasks'), [3, 1])
        self.assertEqual(self.ids(action='create', entity='contracts'), [2])
        self.assertEqual(self.ids(actor='ann', entity='contracts'), [])

    def test_date_range_is_inclusive_of_both_days(self):
        self.assertEqual(self.ids(since='2026-03-05', until='2026-03-05'), [1])
        self.assertEqual(self.ids(since='2026-03-06', until='2026-03-20'), [2])
        self.assertEqual(self.ids(until='2026-03-31', since='2026-03-01').count(3), 0)

    def test_newest_first_and_limits(self):
        self.assertEqual(self.ids(), [3, 2, 1])
        self.assertEqual(len(self.app.audit_query(limit=2)), 2)
        self.assertEqual(len(self.app.audit_query(limit='junk')), 3)
        self.assertEqual(len(self.app.audit_query(limit=-5)), 1)          # clamped to at least one row

    def test_bad_dates_are_rejected_not_executed(self):
        for bad in ('yesterday', "2026-01-01' OR '1'='1", '2026-13-40'):
            with self.assertRaises(ValueError):
                self.app.audit_query(since=bad)

    def test_values_are_bound_as_parameters(self):
        self.assertEqual(self.app.audit_query(actor="x' OR 1=1 --"), [])
        self.assertEqual(len(self.app.read_table('audit')), 3)

    def test_facets_list_what_exists(self):
        facets = self.app.audit_facets()
        self.assertEqual(facets['actors'], ['ann', 'bob'])
        self.assertEqual(facets['entities'], ['contracts', 'tasks'])
        self.assertEqual(facets['actions'], ['create'])


class TrendTests(AppTestCase):
    def monday(self, weeks_ago=0):
        today = datetime.now().date()
        return today - timedelta(days=today.weekday()) - timedelta(weeks=weeks_ago)

    def stamp(self, weeks_ago, day=2):
        return (self.monday(weeks_ago) + timedelta(days=day)).isoformat() + 'T09:00:00+00:00'

    def set_time(self, table, column, ident, value):
        with sqlite3.connect(self.app.DB) as c:
            c.execute(f'UPDATE {table} SET {column}=? WHERE id=?', (value, ident))

    def test_shape_and_week_boundaries(self):
        data = self.app.trends(6)
        self.assertEqual(len(data['weeks']), 6)
        starts = [w['start'] for w in data['weeks']]
        self.assertEqual(starts, sorted(starts))
        self.assertEqual(starts[-1], self.monday().isoformat())
        self.assertTrue(all(datetime.fromisoformat(s).weekday() == 0 for s in starts))
        self.assertEqual(self.app.trends('junk')['weeks'].__len__(), 8)
        self.assertEqual(len(self.app.trends(500)['weeks']), 26)
        self.assertEqual(len(self.app.trends(1)['weeks']), 2)

    def test_counts_land_in_the_right_week(self):
        self.app.add_row('approvals', {'title': 'A', 'requester': 'a', 'approver': 'b'})
        self.app.add_row('approvals', {'title': 'B', 'requester': 'a', 'approver': 'b'})
        self.set_time('approvals', 'created_at', 1, self.stamp(2))
        self.app.decide_approval(1, 'approved')
        self.set_time('approvals', 'decided_at', 1, self.stamp(1))
        weeks = {w['start']: w for w in self.app.trends(8)['weeks']}
        self.assertEqual(weeks[self.monday(2).isoformat()]['approvals_filed'], 1)
        self.assertEqual(weeks[self.monday(0).isoformat()]['approvals_filed'], 1)      # the second one is from this week
        self.assertEqual(weeks[self.monday(1).isoformat()]['approvals_decided'], 1)

    def test_old_activity_is_left_out(self):
        self.app.add_row('tasks', {'title': 'Ancient'})
        self.set_time('tasks', 'created_at', 1, self.stamp(40))
        self.assertEqual(self.app.trends(8)['totals']['tasks_created'], 0)

    def test_completed_tasks_count_single_and_bulk_changes(self):
        ids = [self.app.add_row('tasks', {'title': f'T{i}'})['id'] for i in range(4)]
        self.app.update_status('tasks', ids[0], 'done')
        self.app.bulk_action('tasks', ids[1:3], 'status', 'done')
        self.app.update_status('tasks', ids[3], 'blocked')                  # not a completion
        self.assertEqual(self.app.trends(4)['totals']['tasks_completed'], 3)

    def test_resolved_exceptions_count_manual_bulk_and_automatic(self):
        self.app.add_row('tariffs', {'service': 'S', 'rate': '100'})
        for i in range(3):
            self.app.add_row('transactions', {'ref': f'INV{i}', 'service': 'S', 'customer': 'A', 'billed': '10'})
        self.app.scan()
        ids = [e['id'] for e in self.app.read_table('exceptions')]
        self.assertEqual(self.app.trends(4)['totals']['exceptions_opened'], 3)
        self.app.update_status('exceptions', ids[0], 'done')
        self.app.bulk_exception_status(ids[1:], 'done')
        self.assertEqual(self.app.trends(4)['totals']['exceptions_resolved'], 3)

    def test_empty_database(self):
        totals = self.app.trends(8)['totals']
        self.assertEqual(sum(totals.values()), 0)


class ImportPreviewTests(AppTestCase):
    TASKS = 'title,owner,due_date\nPay rent,ann,2026-02-01\nCall bank,bob,2026-02-02\nPay rent,ann,2026-02-01\n,nobody,2026-02-03\nBad date,ann,tomorrow\n'

    def test_preview_writes_nothing(self):
        result = self.app.import_csv('tasks', self.TASKS, dry_run=True)
        self.assertEqual((result['dry_run'], result['inserted'], result['failed'], result['duplicates']), (True, 2, 2, 1))
        self.assertEqual(self.app.read_table('tasks'), [])
        self.assertEqual([p['title'] for p in result['preview']], ['Pay rent', 'Call bank'])
        self.assertEqual(self.app.read_table('audit'), [])

    def test_real_import_matches_the_preview(self):
        preview = self.app.import_csv('tasks', self.TASKS, dry_run=True)
        real = self.app.import_csv('tasks', self.TASKS)
        self.assertEqual((real['inserted'], real['failed'], real['duplicates']), (preview['inserted'], preview['failed'], preview['duplicates']))
        self.assertEqual(sorted(t['title'] for t in self.app.read_table('tasks')), ['Call bank', 'Pay rent'])

    def test_rows_already_stored_are_skipped(self):
        self.app.add_row('tasks', {'title': 'Pay rent', 'owner': 'ANN', 'due_date': '2026-02-01'})     # case-insensitive match
        result = self.app.import_csv('tasks', self.TASKS)
        self.assertEqual((result['inserted'], result['skipped_duplicates'], result['duplicate_lines']), (1, 2, [2, 4]))
        self.assertEqual(len(self.app.read_table('tasks')), 2)

    def test_importing_the_same_file_twice_is_harmless(self):
        self.app.import_csv('tasks', self.TASKS)
        again = self.app.import_csv('tasks', self.TASKS)
        self.assertEqual((again['inserted'], again['skipped_duplicates']), (0, 3))
        self.assertEqual(len(self.app.read_table('tasks')), 2)

    def test_duplicates_can_be_allowed_on_purpose(self):
        result = self.app.import_csv('tasks', self.TASKS, skip_duplicates=False)
        self.assertEqual((result['inserted'], result['skipped_duplicates'], result['duplicates']), (3, 0, 1))
        self.assertEqual(len(self.app.read_table('tasks')), 3)

    def test_each_record_type_has_a_sensible_key(self):
        cases = {
            'tariffs': 'service,rate,customer\nS1,10,A\nS1,12,A\nS1,10,B\n',
            'transactions': 'ref,service,customer,billed\nI1,S,A,5\nI1,S,A,6\nI2,S,A,5\n',
            'quotations': 'rfq,supplier,item,unit_price\nR1,S1,Pen,1\nR1,S1,Pen,2\nR1,S2,Pen,2\n',
            'contracts': 'contract,obligation,due_date\nC,Pay,2026-01-01\nC,Pay,2026-01-01\nC,Pay,2026-02-01\n',
            'recurring_tasks': 'title,frequency,next_due\nWeekly,weekly,2026-01-01\nWeekly,weekly,2026-02-01\nWeekly,daily,2026-01-01\n',
        }
        expected = {'tariffs': 2, 'transactions': 2, 'quotations': 2, 'contracts': 2, 'recurring_tasks': 2}
        for table, csv_text in cases.items():
            self.assertEqual(self.app.import_csv(table, csv_text, dry_run=True)['inserted'], expected[table], table)

    def test_invalid_input(self):
        for bad in ('settings', 'users', 'audit', None):
            with self.assertRaises(ValueError):
                self.app.import_csv(bad, 'a\n1')
        with self.assertRaises(ValueError):
            self.app.import_csv('tasks', 12345)
        self.assertEqual(self.app.import_csv('tasks', 'title\n')['inserted'], 0)

    def test_approvals_import_still_enforces_the_rules(self):
        result = self.app.import_csv('approvals', 'title,requester,approver,amount\nA,X,Y,10\nB,X,X,1\n')
        self.assertEqual((result['inserted'], result['failed']), (1, 1))
        self.assertIn('different person', result['errors'][0]['error'])


class HttpInsightsTests(AppTestCase):
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
        data = json.loads(r.read())
        conn.close()
        return r.status, data

    def test_endpoints(self):
        self.app.add_row('tasks', {'title': 'T'})
        status, rows = self.call('GET', '/api/audit?entity=tasks&action=create&since=2000-01-01')
        self.assertEqual((status, len(rows)), (200, 1))
        self.assertEqual(self.call('GET', '/api/audit?since=nope')[0], 400)
        self.assertEqual(self.call('GET', '/api/audit/facets')[1]['entities'], ['tasks'])
        status, data = self.call('GET', '/api/trends?weeks=4')
        self.assertEqual((status, len(data['weeks'])), (200, 4))
        self.assertEqual(data['totals']['tasks_created'], 1)

    def test_import_preview_endpoint(self):
        body = {'table': 'tasks', 'csv': 'title\nA\nA\nB\n', 'dry_run': True}
        status, data = self.call('POST', '/api/import', body)
        self.assertEqual((status, data['inserted'], data['duplicates']), (200, 2, 1))
        self.assertEqual(self.app.read_table('tasks'), [])
        body['dry_run'] = False
        self.assertEqual(self.call('POST', '/api/import', body)[1]['inserted'], 2)
        body['skip_duplicates'] = False
        self.assertEqual(self.call('POST', '/api/import', body)[1]['inserted'], 3)


if __name__ == '__main__':
    unittest.main()
