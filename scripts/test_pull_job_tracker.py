import json
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from pull_job_tracker import import_snapshot, rows_from_snapshot


class TrackerPullTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        import database_maintenance as maintenance
        original_backup=maintenance.backup_database
        backup_patch=patch.object(maintenance,'backup_database',side_effect=lambda db:original_backup(db,folder=self.root/'backups'))
        backup_patch.start();self.addCleanup(backup_patch.stop)
        self.db = self.root / 'jobs.sqlite3'
        with closing(sqlite3.connect(self.db)) as c:
            c.execute('CREATE TABLE jobs (id INTEGER PRIMARY KEY, source TEXT, company TEXT, '
                      'title TEXT, url TEXT, canonical_url TEXT, status TEXT)')
            c.execute("INSERT INTO jobs VALUES (1,'indeed','Acme','Old title','old','old','new')")
            c.commit()
        self.snapshot = self.root / 'snapshot.json'
        self.headers = ['ID','Source','Company','Job Title','Job URL','Notes','Resume Created','Cost','Custom']
        self.record = [1,'indeed','Acme','New title','new-url','User notes','X','x','manual']
        self.write()

    def write(self):
        self.data = {'spreadsheet_id':'book','sheet_id':7,'sheet_title':'Job List',
                     'fetched_at_utc':'now','values':[self.headers,self.record],
                     'formula_values':[self.headers,[*self.record[:7], '=IF(TRUE,"x","")', 'manual']]}
        self.snapshot.write_text(json.dumps(self.data),encoding='utf-8')

    def test_preview_does_not_change_database(self):
        before = self.db.read_bytes()
        result = import_snapshot(self.snapshot,self.db)
        self.assertFalse(result['applied'])
        self.assertEqual(self.db.read_bytes(),before)

    def test_apply_preserves_every_cell_and_formula_and_is_idempotent(self):
        first = import_snapshot(self.snapshot,self.db,apply=True)
        self.assertTrue(first['verified'])
        self.assertTrue(Path(first['database_backup']).is_file())
        with closing(sqlite3.connect(self.db)) as c:
            self.assertEqual(c.execute('SELECT title,url,status FROM jobs').fetchone(),('New title','new-url','new'))
            cells, formulas = c.execute('SELECT cells_json,formulas_json FROM google_tracker_rows').fetchone()
            self.assertEqual(json.loads(cells)['Resume Created'],'X')
            self.assertEqual(json.loads(cells)['Notes'],'User notes')
            self.assertEqual(json.loads(cells)['Custom'],'manual')
            self.assertEqual(json.loads(formulas)[7],'=IF(TRUE,"x","")')
        self.assertEqual(import_snapshot(self.snapshot,self.db,apply=True)['discovery_jobs_changed'],0)

    def test_identity_conflict_is_mirrored_without_overwriting_discovery_job(self):
        self.record[1] = 'linkedin'
        self.write()
        result = import_snapshot(self.snapshot,self.db,apply=True)
        self.assertEqual(len(result['source_conflicts']),1)
        with closing(sqlite3.connect(self.db)) as c:
            self.assertEqual(c.execute('SELECT title FROM jobs').fetchone()[0],'Old title')
            self.assertEqual(json.loads(c.execute('SELECT cells_json FROM google_tracker_rows').fetchone()[0])['Source'],'linkedin')

    def test_duplicate_ids_stop_before_any_mutation(self):
        self.data['values'].append(self.record)
        self.data['formula_values'].append(self.record)
        self.snapshot.write_text(json.dumps(self.data),encoding='utf-8')
        before = self.db.read_bytes()
        with self.assertRaises(ValueError):
            import_snapshot(self.snapshot,self.db,apply=True)
        self.assertEqual(self.db.read_bytes(),before)


if __name__ == '__main__':
    unittest.main()
