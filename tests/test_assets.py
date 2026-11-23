"""Equipment register: validation, trash, search, import, backup."""
import unittest

from test_app import AppTestCase


class AssetTests(AppTestCase):
    def add(self, **kw):
        row = {'name': 'Baggage tug', 'tag': 'TUG-001', 'location': 'Apron A', 'next_service': '2026-12-15'}
        row.update(kw)
        return self.app.add_row('assets', row)['id']

    def test_create_read_update(self):
        a = self.add()
        row = self.app.read_table('assets')[0]
        self.assertEqual((row['name'], row['state']), ('Baggage tug', 'in_service'))
        self.app.update_row('assets', a, {'state': 'maintenance', 'location': 'Workshop'})
        row = self.app.read_table('assets')[0]
        self.assertEqual((row['state'], row['location']), ('maintenance', 'Workshop'))

    def test_bad_input_is_refused(self):
        for bad in ({'name': ''}, {'tag': ''}, {'state': 'broken'}, {'next_service': '15/12/2026'}):
            with self.assertRaises(ValueError, msg=str(bad)):
                self.add(**bad)
        a = self.add()
        for bad in ({'state': 'broken'}, {'next_service': 'soon'}, {'name': ' '}):
            with self.assertRaises(ValueError, msg=str(bad)):
                self.app.update_row('assets', a, bad)

    def test_delete_goes_to_trash_and_comes_back(self):
        a = self.add()
        gone = self.app.delete_row('assets', a)
        self.assertEqual(self.app.read_table('assets'), [])
        self.assertEqual(self.app.list_trash()[0]['title'], 'Baggage tug')
        self.app.restore_item(gone['trash_id'])
        self.assertEqual(self.app.read_table('assets')[0]['tag'], 'TUG-001')

    def test_search_and_bulk_delete(self):
        a, b = self.add(), self.add(name='Forklift', tag='FLT-014')
        self.assertEqual([r['title'] for r in self.app.search('FLT-014')], ['Forklift'])
        self.assertEqual(self.app.bulk_action('assets', [a, b], 'delete')['affected'], 2)

    def test_csv_import_skips_duplicate_tags(self):
        csv = 'name,tag,location\nTug,T1,A\nTug copy,T1,A\nLift,L1,B\n'
        r = self.app.import_csv('assets', csv)
        self.assertEqual(len(self.app.read_table('assets')), 2)
        self.assertTrue(r)

    def test_assets_survive_backup_and_restore(self):
        self.add()
        snapshot = self.app.backup_export()
        self.app.delete_row('assets', self.app.read_table('assets')[0]['id'])
        self.app.restore_backup(snapshot)
        self.assertEqual([r['tag'] for r in self.app.read_table('assets')], ['TUG-001'])


if __name__ == '__main__':
    unittest.main()
