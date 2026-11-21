"""Trash: deletes are recoverable for 30 days, with comments and files."""
import base64
import sqlite3
import unittest
from datetime import datetime, timedelta

from test_app import AppTestCase

PW = 'correct-horse-battery'
b64 = lambda b: base64.b64encode(b).decode()


class TrashTests(AppTestCase):
    def setUp(self):
        super().setUp()
        self.t = self.app.add_row('tasks', {'title': 'Fragile task', 'owner': 'ann', 'status': 'blocked'})['id']
        self.app.add_comment('tasks', self.t, 'remember this')
        self.app.add_attachment('tasks', self.t, 'plan.txt', b64(b'plan'))

    def files(self):
        return list(self.app.config.ATTACH_DIR.glob('*'))

    def test_delete_goes_to_trash_and_restores_everything(self):
        r = self.app.delete_row('tasks', self.t)
        self.assertTrue(r['trash_id'])
        self.assertEqual(self.app.read_table('tasks'), [])
        self.assertEqual(len(self.files()), 1)                       # the file is kept while the record is in the trash
        listed = self.app.list_trash()
        self.assertEqual((listed[0]['title'], listed[0]['files'], listed[0]['days_left']), ('Fragile task', 1, 30))
        back = self.app.restore_item(r['trash_id'])
        row = self.app.read_table('tasks')[0]
        self.assertEqual((row['title'], row['status'], row['id']), ('Fragile task', 'blocked', back['id']))
        self.assertEqual([c['body'] for c in self.app.list_comments('tasks', back['id'])], ['remember this'])
        att = self.app.list_attachments('tasks', back['id'])[0]
        self.assertEqual(self.app.read_attachment(att['id']), ('plan.txt', b'plan'))
        self.assertEqual(self.app.list_trash(), [])

    def test_restore_takes_a_new_number_if_the_old_one_is_used(self):
        r = self.app.delete_row('tasks', self.t)
        with sqlite3.connect(self.app.DB) as c:
            c.execute('INSERT INTO tasks(id,title,department,owner,due_date,status,priority,created_at) VALUES(?,?,?,?,?,?,?,?)', (self.t, 'Squatter', '', '', '', 'open', 'medium', 'x'))
        back = self.app.restore_item(r['trash_id'])
        self.assertNotEqual(back['id'], self.t)
        self.assertEqual(len(self.app.read_table('tasks')), 2)

    def test_bulk_delete_is_recoverable(self):
        other = self.app.add_row('tasks', {'title': 'Second'})['id']
        self.app.bulk_action('tasks', [self.t, other], 'delete')
        self.assertEqual(len(self.app.list_trash()), 2)
        for item in self.app.list_trash():
            self.app.restore_item(item['id'])
        self.assertEqual(len(self.app.read_table('tasks')), 2)

    def test_delete_forever_removes_files(self):
        r = self.app.delete_row('tasks', self.t)
        self.app.delete_item(r['trash_id'])
        self.assertEqual(self.files(), [])
        with self.assertRaises(ValueError):
            self.app.restore_item(r['trash_id'])

    def test_old_items_are_purged(self):
        r = self.app.delete_row('tasks', self.t)
        old = (datetime.now().astimezone() - timedelta(days=31)).isoformat(timespec='seconds')
        with sqlite3.connect(self.app.DB) as c:
            c.execute('UPDATE trash SET deleted_at=? WHERE id=?', (old, r['trash_id']))
        self.assertEqual(self.app.purge_old(), 1)
        self.assertEqual((self.app.list_trash(), self.files()), ([], []))

    def test_approvals_are_not_trashable(self):
        a = self.app.add_row('approvals', {'title': 'Crane', 'requester': 'ann', 'approver': 'bob'})['id']
        self.assertIsNone(self.app.delete_row('approvals', a)['trash_id'])
        self.assertEqual(self.app.list_trash(), [])

    def test_backup_restore_keeps_trashed_files(self):
        r = self.app.delete_row('tasks', self.t)
        self.app.restore_backup(self.app.backup_export())
        self.assertEqual(len(self.files()), 1)
        self.app.restore_item(r['trash_id'])

    def test_roles(self):
        for n, role in (('mem', 'member'), ('man', 'manager'), ('adm', 'admin')):
            self.app.create_user({'username': n, 'display_name': n, 'role': role, 'password': PW})
        f = lambda role, method, path: self.app.required_role(method, path)
        self.assertEqual(self.app.required_role('GET', '/api/trash'), 'manager')
        self.assertEqual(self.app.required_role('POST', '/api/trash/restore'), 'manager')
        self.assertEqual(self.app.required_role('DELETE', '/api/trash/3'), 'admin')


if __name__ == '__main__':
    unittest.main()
