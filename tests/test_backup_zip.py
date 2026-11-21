"""Zip backups with attachments, restore safety, audit text search, attachment notifications."""
import base64
import io
import json
import unittest
import zipfile

from test_app import AppTestCase

PW = 'correct-horse-battery'
b64 = lambda b: base64.b64encode(b).decode()


class BackupZipTests(AppTestCase):
    def setUp(self):
        super().setUp()
        self.t = self.app.add_row('tasks', {'title': 'Contract paperwork'})['id']
        self.app.add_attachment('tasks', self.t, 'quote.pdf', b64(b'%PDF-quote'))

    def wipe_files(self):
        for p in self.app.config.ATTACH_DIR.glob('*'):
            p.unlink()

    def test_zip_contains_json_and_files_and_round_trips(self):
        raw = self.app.backup_zip()
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            names = z.namelist()
            self.assertIn('backup.json', names)
            self.assertEqual(len([n for n in names if n.startswith('attachments/')]), 1)
        self.wipe_files()
        r = self.app.restore_zip(b64(raw))
        self.assertEqual(r['attachments_missing'], 0)
        att = self.app.list_attachments('tasks', self.t)[0]
        self.assertEqual(self.app.read_attachment(att['id']), ('quote.pdf', b'%PDF-quote'))

    def test_json_restore_warns_about_missing_files(self):
        data = self.app.backup_export()
        self.wipe_files()
        r = self.app.restore_backup(data)
        self.assertEqual(r['attachments_missing'], 1)

    def test_json_restore_on_same_machine_keeps_files(self):
        data = self.app.backup_export()
        r = self.app.restore_backup(data)
        self.assertEqual(r['attachments_missing'], 0)

    def test_unreferenced_files_are_removed_after_restore(self):
        data = self.app.backup_export()
        stray = self.app.config.ATTACH_DIR / ('a' * 32)
        stray.write_bytes(b'junk')
        self.app.restore_backup(data)
        self.assertFalse(stray.exists())

    def test_hostile_zips_are_rejected(self):
        def make(entries):
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, 'w') as z:
                for n, d in entries.items():
                    z.writestr(n, d)
            return b64(buf.getvalue())
        good = json.dumps(self.app.backup_export())
        for entries in ({'backup.json': good, '../evil.txt': 'x'}, {'backup.json': good, 'attachments/../../x': 'x'},
                        {'backup.json': good, 'attachments/short': 'x'}, {'attachments/' + 'a' * 32: 'x'}):
            with self.assertRaises(ValueError):
                self.app.restore_zip(make(entries))
        with self.assertRaises(ValueError):
            self.app.restore_zip(b64(b'not a zip'))
        with self.assertRaises(ValueError):
            self.app.restore_zip(make({'backup.json': good, 'attachments/' + 'b' * 32: '0' * (self.app.config.MAX_ATTACHMENT + 1)}))

    def test_restored_attachment_rows_cannot_point_outside_the_folder(self):
        data = self.app.backup_export()
        data['data']['attachments'].append({'id': 99, 'entity': 'tasks', 'entity_id': self.t, 'name': 'x', 'stored': '../../secret', 'size': 1, 'uploader': 'a', 'at': 'now'})
        data['data']['attachments'].append({'id': 98, 'entity': 'quotations', 'entity_id': 1, 'name': 'x', 'stored': 'c' * 32, 'size': 1, 'uploader': 'a', 'at': 'now'})
        self.app.restore_backup(data)
        self.assertEqual(len(self.app.list_attachments('tasks', self.t)), 1)

    def test_audit_text_search(self):
        self.assertTrue(any('quote.pdf' in r['details'] for r in self.app.audit_query(q='quote.pdf')))
        self.assertEqual(self.app.audit_query(q='zzz-nothing-zzz'), [])
        self.assertEqual(self.app.audit_query(q='100%'), [])         # wildcard characters are literal
        self.assertTrue(self.app.audit_query(q='ATTACH'))            # case-insensitive, matches the action too

    def test_attachment_notifies_the_owner(self):
        for name in ('ann', 'bob'):
            self.app.create_user({'username': name, 'display_name': name.title(), 'role': 'member', 'password': PW})
        users = {u['username']: u for u in self.app.list_users()}
        ann, bob = (self.app.session_user(self.app.start_session(users[n]['id'])) for n in ('ann', 'bob'))
        t = self.app.add_row('tasks', {'title': 'Ann task', 'owner': 'ann'})['id']
        self.app.add_attachment('tasks', t, 'invoice.pdf', b64(b'x'), bob)
        items = self.app.comment_notifications(ann)
        self.assertTrue(any('attached' in i['detail'] and 'invoice.pdf' in i['detail'] for i in items))
        self.assertEqual(self.app.comment_notifications(bob), [])


if __name__ == '__main__':
    unittest.main()
