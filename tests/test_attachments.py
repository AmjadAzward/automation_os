"""Attachments: safe storage, safe serving, cleanup."""
import base64
import http.client
import threading
import unittest
from http.server import ThreadingHTTPServer

from test_app import AppTestCase

PW = 'correct-horse-battery'
b64 = lambda b: base64.b64encode(b).decode()


class AttachmentTests(AppTestCase):
    def task(self):
        return self.app.add_row('tasks', {'title': 'Needs paperwork'})['id']

    def test_attach_list_read_delete(self):
        t = self.task()
        a = self.app.add_attachment('tasks', t, 'quote.pdf', b64(b'%PDF-1.4 hello'))
        listed = self.app.list_attachments('tasks', t)
        self.assertEqual([x['name'] for x in listed], ['quote.pdf'])
        self.assertEqual(self.app.attachment_counts('tasks'), {str(t): 1})
        name, data = self.app.read_attachment(a['id'])
        self.assertEqual((name, data), ('quote.pdf', b'%PDF-1.4 hello'))
        self.app.delete_attachment(a['id'])
        self.assertEqual(self.app.list_attachments('tasks', t), [])
        self.assertEqual(list(self.app.config.ATTACH_DIR.glob('*')), [])

    def test_names_are_sanitised_and_stored_randomly(self):
        t = self.task()
        a = self.app.add_attachment('tasks', t, r'..\..\evil/../report:v1?.txt', b64(b'x'))
        self.assertEqual(self.app.list_attachments('tasks', t)[0]['name'], 'reportv1.txt')
        files = [p.name for p in self.app.config.ATTACH_DIR.glob('*')]
        self.assertEqual(len(files), 1)
        self.assertRegex(files[0], r'^[0-9a-f]{32}$')

    def test_dangerous_empty_and_oversize_files_are_refused(self):
        t = self.task()
        for bad in ('run.exe', 'page.HTML', 'x.svg', 'a.js'):
            with self.assertRaises(ValueError):
                self.app.add_attachment('tasks', t, bad, b64(b'x'))
        with self.assertRaises(ValueError):
            self.app.add_attachment('tasks', t, 'a.txt', '')
        with self.assertRaises(ValueError):
            self.app.add_attachment('tasks', t, 'a.txt', 'not base64!!')
        with self.assertRaises(ValueError):
            self.app.add_attachment('tasks', t, 'big.bin', b64(b'0' * (self.app.config.MAX_ATTACHMENT + 1)))
        with self.assertRaises(ValueError):
            self.app.add_attachment('quotations', 1, 'a.txt', b64(b'x'))
        with self.assertRaises(ValueError):
            self.app.add_attachment('tasks', 9999, 'a.txt', b64(b'x'))

    def test_per_record_limit(self):
        t = self.task()
        for i in range(self.app.config.MAX_ATTACHMENTS_PER_RECORD):
            self.app.add_attachment('tasks', t, f'f{i}.txt', b64(b'x'))
        with self.assertRaises(ValueError):
            self.app.add_attachment('tasks', t, 'one-too-many.txt', b64(b'x'))

    def test_deleting_the_record_removes_its_files(self):
        t = self.task()
        self.app.add_attachment('tasks', t, 'a.txt', b64(b'x'))
        t2 = self.task()
        self.app.add_attachment('tasks', t2, 'b.txt', b64(b'y'))
        self.app.delete_row('tasks', t)
        self.assertEqual(len(list(self.app.config.ATTACH_DIR.glob('*'))), 1)
        self.app.bulk_action('tasks', [t2], 'delete')
        self.assertEqual(list(self.app.config.ATTACH_DIR.glob('*')), [])

    def test_only_uploader_or_manager_can_remove(self):
        for name, role in (('ann', 'member'), ('bob', 'member'), ('mia', 'manager')):
            self.app.create_user({'username': name, 'display_name': name, 'role': role, 'password': PW})
        users = {u['username']: u for u in self.app.list_users()}
        # open-mode creates an admin only when accounts exist, so build full user dicts as the server would
        ann, bob, mia = (self.app.session_user(self.app.start_session(users[n]['id'])) for n in ('ann', 'bob', 'mia'))
        t = self.task()
        a = self.app.add_attachment('tasks', t, 'a.txt', b64(b'x'), ann)
        with self.assertRaises(self.app.Forbidden):
            self.app.delete_attachment(a['id'], bob)
        self.app.delete_attachment(a['id'], mia)
        b = self.app.add_attachment('tasks', t, 'b.txt', b64(b'x'), ann)
        self.app.delete_attachment(b['id'], ann)

    def test_download_is_served_as_inert_attachment(self):
        t = self.task()
        a = self.app.add_attachment('tasks', t, 'ünï "q".txt', b64(b'<script>alert(1)</script>'))
        srv = ThreadingHTTPServer(('127.0.0.1', 0), self.app.Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            c = http.client.HTTPConnection('127.0.0.1', srv.server_address[1])
            c.request('GET', f"/api/attachments/{a['id']}/download")
            r = c.getresponse(); body = r.read()
            self.assertEqual(r.status, 200)
            self.assertEqual(body, b'<script>alert(1)</script>')
            self.assertEqual(r.getheader('Content-Type'), 'application/octet-stream')
            self.assertTrue(r.getheader('Content-Disposition').startswith('attachment;'))
            self.assertNotIn('\n', r.getheader('Content-Disposition'))
            self.assertEqual(r.getheader('X-Content-Type-Options'), 'nosniff')
            self.assertIn('sandbox', r.getheader('Content-Security-Policy'))
            c.request('GET', '/api/attachments/999/download')
            self.assertEqual(c.getresponse().status, 400)
        finally:
            srv.shutdown(); srv.server_close()


if __name__ == '__main__':
    unittest.main()
